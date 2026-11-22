// Tiny Markdown renderer for LLM answers: headings, bullet lists, bold, italic,
// inline code and horizontal rules. Builds React elements (no innerHTML), so any
// HTML the model writes is shown as plain text, never executed.
// `renderText` lets the caller decorate plain text runs (the Ask page uses it to
// turn every number into an evidence token).
import type { ReactNode } from "react";

type TextFn = (text: string, key: string) => ReactNode[];

function inline(text: string, key: string, rt?: TextFn): ReactNode[] {
  const out: ReactNode[] = [];
  const plain = (s: string, k: string) => { if (s) out.push(...(rt ? rt(s, k) : [s])); };
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    plain(text.slice(last, m.index), `${key}-t${i}`);
    const t = m[0];
    const k = `${key}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k}>{inline(t.slice(2, -2), k, rt)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else out.push(<em key={k}>{inline(t.slice(1, -1), k, rt)}</em>);
    last = m.index + t.length;
  }
  plain(text.slice(last), `${key}-end`);
  return out;
}

export function Markdown({ text, renderText }: { text: string; renderText?: TextFn }) {
  const blocks: ReactNode[] = [];
  let list: { depth: number; node: ReactNode }[] = [];
  let para: string[] = [];
  const rt = renderText;

  const flushPara = () => {
    if (para.length) blocks.push(<p key={`p${blocks.length}`}>{inline(para.join(" "), `p${blocks.length}`, rt)}</p>);
    para = [];
  };
  const flushList = () => {
    if (list.length) {
      const k = `l${blocks.length}`;
      blocks.push(<ul key={k}>{list.map((it, i) =>
        <li key={i} style={{ marginLeft: it.depth * 18 }}>{it.node}</li>)}</ul>);
    }
    list = [];
  };

  text.split("\n").forEach((raw, n) => {
    const line = raw.replace(/\s+$/, "");
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    const li = line.match(/^(\s*)(?:[*-]|\d+\.)\s+(.*)$/);
    if (!line.trim()) { flushPara(); flushList(); }
    else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { flushPara(); flushList(); blocks.push(<hr key={`hr${n}`} />); }
    else if (h) {
      flushPara(); flushList();
      blocks.push(<h3 key={`h${n}`} className="md-h">{inline(h[2].replace(/^\*\*(.*)\*\*$/, "$1"), `h${n}`, rt)}</h3>);
    } else if (li) {
      flushPara();
      list.push({ depth: Math.min(Math.floor(li[1].length / 2), 3), node: inline(li[2], `li${n}`, rt) });
    } else { flushList(); para.push(line.trim()); }
  });
  flushPara(); flushList();
  return <div className="md">{blocks}</div>;
}

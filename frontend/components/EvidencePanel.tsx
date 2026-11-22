"use client";
import { useEffect, useRef, useState } from "react";
import { API, api, docLabel, fmt, type Answer, type Doc, type Evidence } from "@/lib/api";
import { PageText } from "@/components/PageText";

export type View =
  | { kind: "page"; doc_id: string; page: number; highlight?: string }
  | { kind: "calc"; index: number };

/** Right-hand panel on the Ask page (a bottom sheet on phones): the real page with the
 *  number boxed, or the calculation with its inputs. */
export function EvidencePanel({ view, ans, docs, onOpen, onClose }: {
  view: View | null; ans: Answer; docs: Doc[];
  onOpen: (e: Evidence) => void; onClose: () => void;
}) {
  return (
    <aside className={`evidence ${view ? "is-open" : ""}`} aria-label="Evidence">
      {!view && <p className="evidence-empty">Select a number in the answer to see where it comes from.</p>}
      {view?.kind === "page" && <PageEvidence key={`${view.doc_id}#${view.page}#${view.highlight}`} view={view} docs={docs} onClose={onClose} />}
      {view?.kind === "calc" && <CalcEvidence index={view.index} ans={ans} onOpen={onOpen} onClose={onClose} />}
    </aside>
  );
}

function Head({ title, note, onClose }: { title: string; note?: string; onClose: () => void }) {
  return (
    <div className="evidence-head">
      <div>
        <div className="evidence-title">{title}</div>
        {note && <div className="evidence-note">{note}</div>}
      </div>
      <button type="button" className="ghost close" onClick={onClose} aria-label="Close evidence">Close</button>
    </div>
  );
}

export function PageEvidence({ view, docs, onClose }: { view: Extract<View, { kind: "page" }>; docs: Doc[]; onClose: () => void }) {
  const [img, setImg] = useState<{ url: string; hits: number; y: number | null } | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [mode, setMode] = useState<"image" | "text">("image");
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let url = "";
    const q = view.highlight ? `?highlight=${encodeURIComponent(view.highlight)}` : "";
    fetch(`${API}/documents/${encodeURIComponent(view.doc_id)}/pages/${view.page}/image${q}`)
      .then(async r => {
        if (!r.ok) throw new Error("no image");
        const hits = Number(r.headers.get("X-Highlight-Hits") || 0);
        const y = r.headers.get("X-Highlight-Y");
        url = URL.createObjectURL(await r.blob());
        setImg({ url, hits, y: y ? Number(y) : null });
        // a scanned page has no text layer, so the number cannot be boxed: show the OCR text instead
        if (view.highlight && hits === 0) setMode("text");
      })
      .catch(() => setMode("text"));
    api<{ text: string }>(`/documents/${encodeURIComponent(view.doc_id)}/pages/${view.page}`)
      .then(p => setText(p.text)).catch(e => setErr(e.message));
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [view.doc_id, view.page, view.highlight]);

  const scrollToHit = () => {
    const el = box.current;
    if (el && img?.y != null) el.scrollTop = Math.max(0, img.y * el.scrollHeight - el.clientHeight / 3);
  };

  const note = view.highlight
    ? (img?.hits ? `${view.highlight} is boxed on the page.` : mode === "text" && text !== null ? `${view.highlight} is marked in the page text (this page is scanned).` : undefined)
    : undefined;

  return (
    <>
      <Head title={`${docLabel(view.doc_id, docs)}, page ${view.page}`} note={note} onClose={onClose} />
      {img && text !== null && (
        <div className="seg" role="group" aria-label="Page view">
          <button type="button" aria-pressed={mode === "image"} onClick={() => setMode("image")}>Page</button>
          <button type="button" aria-pressed={mode === "text"} onClick={() => setMode("text")}>Text</button>
        </div>
      )}
      {err && <p className="err">{err}</p>}
      {mode === "image" && img && (
        <div className="page-image" ref={box}>
          <img src={img.url} alt={`Page ${view.page} of ${docLabel(view.doc_id, docs)}`} onLoad={scrollToHit} />
        </div>
      )}
      {mode === "image" && !img && <p className="loading"><span className="spinner" aria-hidden="true" />Rendering the page…</p>}
      {mode === "text" && (text === null ? <p className="loading"><span className="spinner" aria-hidden="true" />Loading the page…</p>
        : <PageText text={text} highlight={view.highlight} />)}
    </>
  );
}

function CalcEvidence({ index, ans, onOpen, onClose }: { index: number; ans: Answer; onOpen: (e: Evidence) => void; onClose: () => void }) {
  const c = ans.calculations[index];
  if (!c) return null;
  const pct = /pct|cagr/i.test(c.expression);
  return (
    <>
      <Head title="Computed by code" note="The AI chose the inputs. Python did the arithmetic." onClose={onClose} />
      <div className="calc-body">
        <code className="expr">{c.expression}</code>
        {Object.keys(c.variables).length > 0 && (
          <table className="inputs">
            <thead><tr><th>Input</th><th className="num">Value</th><th>Source</th></tr></thead>
            <tbody>
              {Object.entries(c.variables).map(([k, v]) => {
                const src = ans.evidence?.find(e => e.status === "found" && Math.abs(e.value - v) <= 0.005 * Math.abs(v));
                return (
                  <tr key={k}>
                    <td>{k}</td><td className="num">{fmt(v, 4)}</td>
                    <td>{src?.doc_id ? <button type="button" className="link" onClick={() => onOpen(src)}>page {src.page}</button> : <span className="muted">from the answer</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {c.error ? <p className="err">The calculation failed: {c.error}</p>
          : <p className="result"><span className="muted">Result</span> {fmt(c.result, 4)}{pct ? "%" : ""}</p>}
      </div>
    </>
  );
}

"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, postJSON, docLabel, shortName, type Answer, type Doc, type Evidence } from "@/lib/api";
import { MODE_NAME } from "@/lib/labels";
import { Markdown } from "@/lib/markdown";
import { EvidenceToken, ProvenanceLegend } from "@/components/EvidenceToken";
import { EvidencePanel, type View } from "@/components/EvidencePanel";

const MODES = [
  { id: "agent", help: "Searches the report, reads the pages it needs and lets code do every calculation. Recommended." },
  { id: "rag_calc", help: "One search, then the AI picks the figures and code does the maths." },
  { id: "rag_direct", help: "One search, and the AI does the maths itself. Used as a baseline in our experiment." },
  { id: "closed_book", help: "Answers from the AI's memory without reading any report. Used as a baseline." },
];

// Same number pattern as the backend, so tokens line up with its evidence list.
const NUM_RE = /\(?-?\$?\d(?:[\d,]*\d)?(?:\.\d+)?\)?/g;
// (LUCK_Q2026_288146, p. 22) or (LUCK_Q2026_288146, pp. 12, 25)
const CITE_RE = /\(?\b([A-Z][A-Z0-9]*_[A-Za-z0-9_]+)(?:,\s*(?:pp?\.|pages?)\s*(\d+)((?:\s*(?:,|–|-|and)\s*\d+)*))?\)?/g;

export default function AskPage() {
  const [docs, setDocs] = useState<Doc[] | null>(null);
  const [symbol, setSymbol] = useState("");
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [mode, setMode] = useState("agent");
  const [scope, setScope] = useState("");
  const [ans, setAns] = useState<Answer | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState("");
  const [view, setView] = useState<View | null>(null);

  const loadDocs = () => api<Doc[]>("/documents").then(setDocs).catch(e => { setDocs([]); setErr(e.message); });
  useEffect(() => { loadDocs(); }, []);
  useEffect(() => {
    if (!busy && !loading) return;
    const t0 = Date.now(); setElapsed(0);
    const t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(t);
  }, [busy, loading]);

  async function loadReport() {
    if (!symbol) { setErr("Type a PSX symbol first, for example LUCK."); return; }
    setLoading(true); setErr("");
    try {
      const r = await api<Doc[]>(`/ingest/psx/${symbol}?limit=2`, { method: "POST" });
      if (!r.length) setErr(`No new reports found for ${symbol}. Check the symbol on dps.psx.com.pk.`);
      await loadDocs();
    } catch (e: any) { setErr(e.message); }
    setLoading(false);
  }

  const examples = useMemo(() => {
    const d = docs?.[0];
    if (!d) return [];
    const n = shortName(d.company || d.symbol);
    return [
      `What was ${n}'s profit after tax, and how much did it grow?`,
      `How did ${n}'s gross margin change from last year?`,
      `What were ${n}'s total assets and total equity?`,
    ];
  }, [docs]);

  const evMap = useMemo(() => new Map((ans?.evidence || []).map(e => [e.text, e])), [ans]);
  const tally = useMemo(() => {
    const t = { found: 0, computed: 0, unverified: 0 };
    (ans?.evidence || []).forEach(e => { t[e.status] += 1; });
    return t;
  }, [ans]);
  const total = tally.found + tally.computed + tally.unverified;

  async function ask() {
    if (!q.trim() || busy) return;
    setBusy(true); setErr(""); setAns(null); setView(null);
    try {
      const a = await postJSON<Answer>("/ask", { question: q, mode, doc_ids: scope ? [scope] : null });
      setAns(a);
      const first = a.evidence?.find(e => e.status === "found");
      // open the evidence for the first printed number on wide screens only; on phones it is a sheet
      if (first?.doc_id && window.matchMedia("(min-width: 981px)").matches)
        setView({ kind: "page", doc_id: first.doc_id, page: first.page!, highlight: first.match });
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }

  function openEvidence(e: Evidence) {
    if (e.status === "found" && e.doc_id) setView({ kind: "page", doc_id: e.doc_id, page: e.page!, highlight: e.match });
    else if (e.status === "computed" && e.calc != null) setView({ kind: "calc", index: e.calc });
    else setView(null);
  }
  const isActive = (e: Evidence) =>
    (view?.kind === "page" && e.status === "found" && view.highlight === e.match && view.page === e.page) ||
    (view?.kind === "calc" && e.status === "computed" && view.index === e.calc);

  // Plain answer text -> citation buttons and evidence tokens.
  function decorate(text: string, key: string): ReactNode[] {
    const out: ReactNode[] = [];
    const numbers = (s: string, k: string) => {
      let l = 0, j = 0;
      for (const m of s.matchAll(NUM_RE)) {
        const e = evMap.get(m[0]);
        if (!e) continue;
        if (m.index! > l) out.push(s.slice(l, m.index));
        out.push(<EvidenceToken key={`${k}-n${j++}`} text={m[0]} ev={e} active={isActive(e)} onOpen={openEvidence} />);
        l = m.index! + m[0].length;
      }
      if (l < s.length) out.push(s.slice(l));
    };
    let last = 0, i = 0;
    for (const m of text.matchAll(CITE_RE)) {
      numbers(text.slice(last, m.index), `${key}-s${i}`);
      const [, doc, page, more] = m;
      const pages = page ? `p. ${page}${(more || "").replace(/\s+/g, " ")}` : "";
      out.push(
        <button key={`${key}-c${i++}`} type="button" className="cite" disabled={!page}
          onClick={() => page && setView({ kind: "page", doc_id: doc, page: +page })}>
          {docLabel(doc, docs || [])}{pages ? `, ${pages}` : ""}
        </button>);
      last = m.index! + m[0].length;
    }
    numbers(text.slice(last), `${key}-end`);
    return out;
  }

  if (docs === null) return <p className="loading"><span className="spinner" aria-hidden="true" />Connecting to Mizan…</p>;

  // First run: one clear first step.
  if (docs.length === 0) {
    return (
      <section className="first-step">
        <h1>Ask a company's report</h1>
        <p className="lede">Start by loading a report. Type a company's PSX symbol and Mizan downloads its latest results from the Pakistan Stock Exchange.</p>
        <div className="load-row">
          <label className="field">
            PSX symbol
            <input className="symbol" value={symbol} placeholder="e.g. LUCK" maxLength={10} autoFocus
              onChange={e => setSymbol(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
              onKeyDown={e => { if (e.key === "Enter") loadReport(); }} />
          </label>
          <button type="button" className="primary" onClick={loadReport} disabled={loading}>
            {loading ? <><span className="spinner on-dark" aria-hidden="true" />Loading… {elapsed}s</> : "Load a report"}
          </button>
        </div>
        <p className="hint">Scanned reports are read with OCR and can take a minute or two. You can also upload a PDF on the <Link href="/documents">Reports</Link> page.</p>
        {err && <p className="err" role="alert">{err}</p>}
      </section>
    );
  }

  const current = MODES.find(m => m.id === mode)!;

  return (
    <>
      <h1>Ask a company's report</h1>
      <p className="lede">Every number in the answer shows where it came from. Select a number to see its source.</p>

      <div className="ask-box">
        <textarea value={q} onChange={e => setQ(e.target.value)} aria-label="Your question" rows={2}
          placeholder={`e.g. ${examples[0] ?? "What was profit after tax?"}`}
          onKeyDown={e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) ask(); }} />
        <div className="ask-bar">
          <select value={scope} onChange={e => setScope(e.target.value)} aria-label="Which report">
            <option value="">All reports (picks the company and year from the question)</option>
            {docs.map(d => <option key={d.doc_id} value={d.doc_id}>{docLabel(d.doc_id, docs)}</option>)}
          </select>
          <span className="grow" />
          <button type="button" className="primary" onClick={ask} disabled={busy}>
            {busy ? <><span className="spinner on-dark" aria-hidden="true" />Reading the report… {elapsed}s</> : "Ask"}
          </button>
        </div>
      </div>

      <details className="method">
        <summary>Answer method: <strong>{MODE_NAME[mode]}</strong></summary>
        <fieldset>
          <legend className="sr-only">Answer method</legend>
          {MODES.map(m => (
            <label key={m.id} className="method-option">
              <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
              <span><strong>{MODE_NAME[m.id]}</strong><span className="help">{m.help}</span></span>
            </label>
          ))}
        </fieldset>
      </details>
      {mode !== "agent" && <p className="hint">{current.help}</p>}

      {!ans && !busy && examples.length > 0 && (
        <div className="examples">
          <span className="muted">Try:</span>
          <ul>{examples.map(x => <li key={x}><button type="button" className="text-btn" onClick={() => setQ(x)}>{x}</button></li>)}</ul>
        </div>
      )}
      {err && <p className="err" role="alert">{err}</p>}

      {ans && (
        <div className="workspace">
          <section className="answer-col" aria-label="Answer">
            {total > 0 && (
              <div className="provenance">
                <ProvenanceLegend />
                <p className={`tally ${tally.unverified ? "has-unverified" : ""}`}>
                  {total} {total === 1 ? "number" : "numbers"}: {tally.found} printed, {tally.computed} computed, {tally.unverified} unverified.
                  {tally.unverified > 0 && " Check the unverified ones before relying on this answer."}
                </p>
              </div>
            )}
            {ans.refused && <p className="notice">Mizan could not find enough in the report to answer. Try naming the company and the year.</p>}
            <div className="answer"><Markdown text={ans.answer} renderText={decorate} /></div>

            {ans.citations.length > 0 && (
              <div className="sources">
                <h2>Sources</h2>
                <ol>
                  {ans.citations.map((c, i) => (
                    <li key={i}><button type="button" className="link" onClick={() => setView({ kind: "page", doc_id: c.doc_id, page: c.page })}>
                      {docLabel(c.doc_id, docs)}, page {c.page}</button></li>
                  ))}
                </ol>
              </div>
            )}

            <details className="run">
              <summary>How this answer was produced</summary>
              <dl>
                <div><dt>Method</dt><dd>{MODE_NAME[ans.mode] ?? ans.mode}</dd></div>
                <div><dt>Steps</dt><dd>{ans.steps}</dd></div>
                <div><dt>Time</dt><dd>{ans.latency_s.toFixed(1)} s</dd></div>
                <div><dt>Tokens</dt><dd>{(ans.tokens_in + ans.tokens_out).toLocaleString()}</dd></div>
                <div><dt>Cost at paid-tier prices</dt><dd>${ans.cost_usd.toFixed(5)}</dd></div>
                <div><dt>Grounding</dt><dd>{(100 * ans.grounding).toFixed(0)}%</dd></div>
              </dl>
            </details>
          </section>

          <EvidencePanel view={view} ans={ans} docs={docs} onOpen={openEvidence} onClose={() => setView(null)} />
        </div>
      )}
    </>
  );
}

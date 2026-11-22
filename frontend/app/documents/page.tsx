"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, API, docLabel, shortName, type Doc } from "@/lib/api";
import { PageEvidence } from "@/components/EvidencePanel";

type Field = { value: number | null; page: number | null; label: string | null };
type Fin = { highlights: Record<string, any>; absolute: Record<string, number | null>; warnings: string[] };

const INCOME: [string, string][] = [
  ["revenue", "Revenue"], ["gross_profit", "Gross profit"], ["operating_profit", "Operating profit"],
  ["profit_before_tax", "Profit before tax"], ["net_profit", "Profit after tax"], ["eps_basic", "Earnings per share (Rs)"],
];
const BALANCE: [string, string][] = [
  ["total_assets", "Total assets"], ["total_liabilities", "Total liabilities"], ["total_equity", "Total equity"],
];
const UNIT: Record<string, string> = { units: "rupees", thousands: "Rs '000", millions: "Rs million", billions: "Rs billion" };
const n = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 2 });

export default function Reports() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [symbol, setSymbol] = useState("");
  const [busy, setBusy] = useState<"" | "psx" | "upload">("");
  const [elapsed, setElapsed] = useState(0);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [fin, setFin] = useState<{ data?: Fin; err?: string; loading?: boolean; extracting?: boolean }>({});
  const [page, setPage] = useState<{ page: number; highlight?: string } | null>(null);

  const load = () => api<Doc[]>("/documents").then(setDocs).catch(e => setMsg({ text: e.message, bad: true }));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now(); setElapsed(0);
    const t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 500);
    return () => clearInterval(t);
  }, [busy]);

  async function fromPSX() {
    if (busy) return;
    if (!symbol) { setMsg({ text: "Type a PSX symbol first, for example LUCK.", bad: true }); return; }
    setBusy("psx"); setMsg(null);
    try {
      const r = await api<Doc[]>(`/ingest/psx/${symbol}?limit=2`, { method: "POST" });
      setMsg({ text: r.length ? `Added ${r.length} ${r.length > 1 ? "reports" : "report"} for ${symbol}. Key figures are being extracted.` : `No new reports for ${symbol}. They may already be in the library.` });
      await load();
      if (r[0]) open(r[0].doc_id);
    } catch (e: any) { setMsg({ text: e.message, bad: true }); }
    setBusy("");
  }

  async function upload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (busy) return;
    setBusy("upload"); setMsg(null);
    const form = e.currentTarget;
    try {
      const r = await fetch(`${API}/documents/upload`, { method: "POST", body: new FormData(form) });
      const j = await r.json(); if (!r.ok) throw new Error(j.detail);
      setMsg({ text: `Added the report (${j.n_pages} pages). Key figures are being extracted.` });
      form.reset(); await load(); open(j.doc_id);
    } catch (er: any) { setMsg({ text: er.message || "The upload failed.", bad: true }); }
    setBusy("");
  }

  async function open(id: string, extract = false) {
    setSel(id); setPage(null);
    setFin({ loading: !extract, extracting: extract });
    try {
      setFin({ data: await api<Fin>(`/financials/${encodeURIComponent(id)}${extract ? "/extract" : ""}`, extract ? { method: "POST" } : undefined) });
    } catch (e: any) { setFin({ err: e.message }); }
  }

  const h = fin.data?.highlights;
  const v = (k: string): number | null => h?.[k]?.value ?? null;

  function Statement({ items }: { items: [string, string][] }) {
    return (
      <table className="statement">
        <tbody>
          {items.map(([k, label]) => {
            const f: Field | undefined = h?.[k];
            return (
              <tr key={k}>
                <th scope="row">{label}</th>
                <td className="num">{f?.value != null ? n(f.value) : <span className="muted">not found</span>}</td>
                <td className="src">{f?.value != null && f.page ? <button type="button" className="link" onClick={() => setPage({ page: f.page!, highlight: n(f.value) })}>page {f.page}</button> : null}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }

  // The deterministic checks from validate() in the backend, with the two sides shown.
  const ale = v("total_liabilities") != null && v("total_equity") != null ? v("total_liabilities")! + v("total_equity")! : null;
  const checks = h ? [
    { label: "Total assets = liabilities + equity (within 2%)", left: v("total_assets"), right: ale,
      leftName: "assets", rightName: "liabilities + equity", key: "total_assets" },
    { label: "Profit after tax is not above profit before tax", left: v("net_profit"), right: v("profit_before_tax"),
      leftName: "after tax", rightName: "before tax", key: "net_profit greater" },
    { label: "Earnings per share has the same sign as profit", left: v("eps_basic"), right: v("net_profit"),
      leftName: "EPS", rightName: "profit", key: "eps sign" },
  ].map(c => ({ ...c, state: c.left == null || c.right == null ? "skip" : fin.data!.warnings.some(w => w.includes(c.key)) ? "fail" : "pass" })) : [];

  const selDoc = docs.find(d => d.doc_id === sel);

  return (
    <>
      <h1>Reports</h1>
      <p className="lede">Add a company's annual or quarterly report. Mizan reads every page, scanned pages included, and extracts the key figures with their page numbers.</p>

      <div className="add-grid">
        <section className="panel" aria-labelledby="psx-h">
          <h2 id="psx-h">Get the latest reports from PSX</h2>
          <div className="load-row">
            <label className="field">
              PSX symbol
              <input className="symbol" value={symbol} placeholder="e.g. LUCK" maxLength={10}
                onChange={e => setSymbol(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
                onKeyDown={e => { if (e.key === "Enter") fromPSX(); }} />
            </label>
            <button type="button" className="primary" onClick={fromPSX} disabled={!!busy}>
              {busy === "psx" ? <><span className="spinner on-dark" aria-hidden="true" />Fetching… {elapsed}s</> : "Fetch reports"}
            </button>
          </div>
          <p className="hint">Downloads the two newest reports from dps.psx.com.pk. Scanned reports need OCR and can take a minute or two.</p>
        </section>

        <section className="panel" aria-labelledby="up-h">
          <h2 id="up-h">Upload a PDF</h2>
          <form onSubmit={upload} className="upload-form">
            <label className="field full">Company name<input name="company" placeholder="e.g. Lucky Cement Limited" required /></label>
            <label className="field">PSX symbol<input name="symbol" placeholder="e.g. LUCK" /></label>
            <label className="field">Period<input name="period" placeholder="e.g. FY2026" /></label>
            <label className="field">Report type
              <select name="doc_type"><option value="annual">Annual</option><option value="quarterly">Quarterly</option><option value="half-yearly">Half-yearly</option></select>
            </label>
            <label className="field">PDF file<input type="file" name="file" accept="application/pdf" required /></label>
            <div className="full"><button className="secondary" disabled={!!busy}>{busy === "upload" ? <><span className="spinner" aria-hidden="true" />Reading… {elapsed}s</> : "Upload and read"}</button></div>
          </form>
        </section>
      </div>

      {msg && <p className={msg.bad ? "err" : "notice"} role="status">{msg.text}</p>}

      <section className="block" aria-labelledby="lib-h">
        <div className="block-head">
          <h2 id="lib-h">Library</h2>
          <p className="hint">Reports are kept in memory and cleared when the server restarts.</p>
        </div>
        {docs.length === 0 ? (
          <p className="muted">No reports yet. Fetch one from PSX or upload a PDF above.</p>
        ) : (
          <table className="library">
            <thead><tr><th>Company</th><th>Report</th><th className="num">Pages</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {docs.map(d => (
                <tr key={d.doc_id} aria-selected={sel === d.doc_id}>
                  <td><strong>{shortName(d.company || d.symbol)}</strong> <span className="muted">{d.symbol}</span></td>
                  <td>{docLabel(d.doc_id, docs).split(", ").slice(1).join(", ") || d.doc_type}</td>
                  <td className="num">{d.n_pages}</td>
                  <td className="actions">
                    <button type="button" className="secondary small" onClick={() => open(d.doc_id)}>Key figures</button>
                    {d.source_url && <a href={d.source_url} target="_blank" rel="noreferrer">Original PDF</a>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {sel && (
        <section className="block" aria-labelledby="fig-h">
          <div className="block-head">
            <h2 id="fig-h">Key figures for {selDoc ? docLabel(selDoc.doc_id, docs) : sel}</h2>
            {h && <p className="hint">{h.consolidated ? "Consolidated statements" : "Company-only statements"}, in {UNIT[h.unit] || h.unit} as printed{h.period_end ? `, period ending ${h.period_end}` : ""}.</p>}
          </div>

          {(fin.loading || fin.extracting) && <p className="loading"><span className="spinner" aria-hidden="true" />{fin.extracting ? "Extracting figures from the statement pages…" : "Loading…"}</p>}

          {fin.err && (
            <div className="notice">
              <p><strong>{/no extracted/i.test(fin.err) ? "The figures are not ready yet." : "The figures could not be loaded."}</strong>{" "}
                {/no extracted/i.test(fin.err) ? "Extraction runs in the background after a report is added. Check again in a moment, or run it now." : fin.err}</p>
              <div className="row">
                <button type="button" className="secondary" onClick={() => open(sel)}>Check again</button>
                <button type="button" className="primary" onClick={() => open(sel, true)}>Extract now</button>
              </div>
            </div>
          )}

          {h && (
            <div className={`figures ${page ? "with-page" : ""}`}>
              <div>
                <div className="statements">
                  <div><h3>Income statement</h3><Statement items={INCOME} /></div>
                  <div><h3>Balance sheet</h3><Statement items={BALANCE} /></div>
                </div>
                <h3 className="checks-h">Checks done by code</h3>
                <ul className="checks">
                  {checks.map(c => (
                    <li key={c.label} className={`check-${c.state}`}>
                      <span className="check-icon" aria-hidden="true">{c.state === "pass" ? "✓" : c.state === "fail" ? "✕" : "–"}</span>
                      <span className="check-label">{c.label}<span className="sr-only">: {c.state === "pass" ? "passed" : c.state === "fail" ? "failed" : "not checked"}</span></span>
                      <span className="check-values">
                        {c.state === "skip" ? "not checked, a figure is missing"
                          : <>{c.leftName} {n(c.left)} <span className="muted">vs</span> {c.rightName} {n(c.right)}</>}
                      </span>
                    </li>
                  ))}
                </ul>
                <p><Link href="/">Ask a question about this report</Link></p>
              </div>
              {page && sel && (
                <div className="page-viewer">
                  <PageEvidence key={`${page.page}#${page.highlight}`} view={{ kind: "page", doc_id: sel, page: page.page, highlight: page.highlight }} docs={docs} onClose={() => setPage(null)} />
                </div>
              )}
            </div>
          )}
        </section>
      )}
    </>
  );
}

"use client";
import { useEffect, useMemo, useState } from "react";
import { api, shortName } from "@/lib/api";
import { PageEvidence } from "@/components/EvidencePanel";
import { CalcCell } from "@/components/CalcCell";
import { ChartFrame, type Tip } from "@/components/charts/ChartFrame";
import {
  METRICS, factDocs, fmtShown, freqName, metric, periodName, printed, shown, unitLabel,
  type Cell, type Company, type CompareRes,
} from "@/lib/facts";

const DEFAULT_METRICS = ["revenue", "net_profit", "eps_basic", "net_margin", "roe"];

type Open = { kind: "page"; doc_id: string; page: number; highlight?: string } | { kind: "calc"; cell: Cell };

export default function ComparePage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [months, setMonths] = useState(12);
  const [periodEnd, setPeriodEnd] = useState("");
  const [metrics, setMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [basis, setBasis] = useState("");
  const [res, setRes] = useState<CompareRes | null>(null);
  const [chartMetric, setChartMetric] = useState("revenue");
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Company[]>("/facts").then(cs => {
      setCompanies(cs);
      const annual = cs.filter(c => c.periods.some(p => p.months === 12));
      setPicked(annual.slice(0, 3).map(c => c.symbol));
    }).catch(e => { setCompanies([]); setErr(e.message); });
  }, []);

  // periods every picked company could have, for the chosen length (annual / quarter / ...)
  const periodOptions = useMemo(() => {
    const ends = new Map<string, number>();
    (companies || []).filter(c => picked.includes(c.symbol)).forEach(c =>
      c.periods.filter(p => p.months === months).forEach(p => ends.set(p.period_end, (ends.get(p.period_end) || 0) + 1)));
    return [...ends.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [companies, picked, months]);
  const freqs = useMemo(() => [...new Set((companies || []).flatMap(c => c.periods.map(p => p.months)))].sort((a, b) => b - a), [companies]);

  useEffect(() => {
    if (!periodOptions.length) { setPeriodEnd(""); return; }
    if (!periodOptions.some(([e]) => e === periodEnd)) {
      // latest period that most picked companies have
      const best = [...periodOptions].sort((a, b) => b[1] - a[1] || b[0].localeCompare(a[0]))[0];
      setPeriodEnd(best[0]);
    }
  }, [periodOptions]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    if (picked.length < 2) { setErr("Pick at least two companies."); return; }
    if (!metrics.length) { setErr("Pick at least one figure or ratio."); return; }
    setBusy(true); setErr(""); setOpen(null);
    const q = new URLSearchParams({ symbols: picked.join(","), metrics: metrics.join(",") });
    if (periodEnd) q.set("period_end", periodEnd);
    if (basis) q.set("basis", basis);
    try {
      const r = await api<CompareRes>(`/compare?${q}`);
      setRes(r);
      if (!r.metrics.includes(chartMetric)) setChartMetric(r.metrics[0]);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }
  useEffect(() => { if (companies?.length && picked.length >= 2 && periodEnd) run(); }, [periodEnd]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (list: string[], set: (v: string[]) => void, id: string, max = 99) =>
    set(list.includes(id) ? list.filter(x => x !== id) : list.length >= max ? list : [...list, id]);

  if (companies === null) return <p className="loading"><span className="spinner" aria-hidden="true" />Loading the verified figures…</p>;
  if (!companies.length) return (
    <section className="first-step">
      <h1>Compare companies</h1>
      <p className="lede">No verified figures yet. Comparisons use only figures a person has checked against the report (eval/data/psx_labels.csv).</p>
      {err && <p className="err" role="alert">{err}</p>}
    </section>
  );

  const docs = factDocs(companies, (res?.rows || []).flatMap(c => [c.doc_id, ...(c.operands || []).map(o => o.doc_id)]));
  const name = (s: string) => shortName(companies.find(c => c.symbol === s)?.company || s);
  const refusals = (res?.rows || []).filter(c => c.refused);

  return (
    <>
      <h1>Compare companies</h1>
      <p className="lede">Figures come only from checked report pages, and ratios are calculated by code. Select a figure to see the page it came from.</p>

      <div className="controls panel">
        <fieldset className="pick">
          <legend>Companies <span className="muted">(2 to 4)</span></legend>
          <div className="chips">
            {companies.map(c => (
              <label key={c.symbol} className="chip">
                <input type="checkbox" checked={picked.includes(c.symbol)}
                  disabled={!picked.includes(c.symbol) && picked.length >= 4}
                  onChange={() => toggle(picked, setPicked, c.symbol, 4)} />
                <span>{shortName(c.company)} <span className="muted">{c.symbol}</span></span>
              </label>
            ))}
          </div>
        </fieldset>

        <div className="row controls-row">
          <label className="field">Period length
            <select value={months} onChange={e => setMonths(+e.target.value)}>
              {freqs.map(m => <option key={m} value={m}>{freqName[m] ?? `${m} months`}</option>)}
            </select>
          </label>
          <label className="field">Period
            <select value={periodEnd} onChange={e => setPeriodEnd(e.target.value)} disabled={!periodOptions.length}>
              {!periodOptions.length && <option value="">No shared period</option>}
              {periodOptions.map(([e, n]) => (
                <option key={e} value={e}>{periodName({ period_end: e, period_type: "", months })} ({n} of {picked.length})</option>
              ))}
            </select>
          </label>
          <label className="field">Statements
            <select value={basis} onChange={e => setBasis(e.target.value)}>
              <option value="">Consolidated where published</option>
              <option value="consolidated">Consolidated only</option>
              <option value="unconsolidated">Unconsolidated only</option>
            </select>
          </label>
        </div>

        <fieldset className="pick">
          <legend>Figures and ratios</legend>
          <div className="chips">
            {METRICS.map(m => (
              <label key={m.id} className="chip">
                <input type="checkbox" checked={metrics.includes(m.id)} onChange={() => toggle(metrics, setMetrics, m.id)} />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <button type="button" className="primary" onClick={run} disabled={busy}>
          {busy ? <><span className="spinner on-dark" aria-hidden="true" />Comparing…</> : "Compare"}
        </button>
        <p className="hint">Mizan never compares a quarter with a year, or consolidated with unconsolidated figures: such cells are left empty with the reason.</p>
      </div>
      {err && <p className="err" role="alert">{err}</p>}

      {res && (
        <div className="workspace">
          <section className="answer-col wide" aria-label="Comparison">
            <div className="table-scroll">
              <table className="cmp">
                <thead>
                  <tr>
                    <th scope="col">{periodEnd ? periodName({ period_end: periodEnd, period_type: "", months }) : "Latest year"}</th>
                    {res.symbols.map(s => <th key={s} scope="col" className="num">{name(s)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {res.metrics.map(m => (
                    <tr key={m}>
                      <th scope="row">{metric(m).label} <span className="muted unit">{unitLabel(m)}</span></th>
                      {res.symbols.map(s => {
                        const c = res.table[s]?.[m];
                        const v = shown(c);
                        if (!c || c.refused) return (
                          <td key={s} className="num refused-cell" title={c?.reason}>
                            <span aria-hidden="true">—</span><span className="sr-only">Not available: {c?.reason}</span>
                          </td>);
                        const isCalc = !!c.formula;
                        return (
                          <td key={s} className="num">
                            <button type="button" className={`ev ${isCalc ? "ev-computed" : "ev-found"}`}
                              title={isCalc ? `Calculated: ${c.formula}` : `${c.doc_id}, page ${c.page}`}
                              onClick={() => isCalc ? setOpen({ kind: "calc", cell: c })
                                : c.doc_id && c.page && setOpen({ kind: "page", doc_id: c.doc_id, page: c.page, highlight: printed(c.value!, c.unit) })}>
                              {fmtShown(v, m)}
                            </button>
                          </td>);
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">
              <span className="ev ev-found legend-swatch">green</span> printed in the report ·
              <span className="ev ev-computed legend-swatch">blue</span> calculated by code from printed figures ·
              — not available. Money is shown in Rs million because reports print in rupees, thousands or millions.
            </p>

            {refusals.length > 0 && (
              <details className="run">
                <summary>Why {refusals.length} {refusals.length === 1 ? "cell is" : "cells are"} empty</summary>
                <ul className="reasons">
                  {refusals.map((c, i) => <li key={i}><strong>{name(c.symbol)}, {metric(c.metric).label}:</strong> {c.reason}</li>)}
                </ul>
              </details>
            )}

            <CompareChart res={res} metricId={chartMetric} setMetricId={setChartMetric} name={name} />
          </section>

          <aside className={`evidence ${open ? "is-open" : ""}`} aria-label="Evidence">
            {!open && <p className="evidence-empty">Select a figure to see the report page it came from, or a ratio to see how it was calculated.</p>}
            {open?.kind === "page" && <PageEvidence key={`${open.doc_id}#${open.page}#${open.highlight}`} view={open} docs={docs} onClose={() => setOpen(null)} />}
            {open?.kind === "calc" && <CalcCell cell={open.cell} name={name}
              onPage={(doc_id, page, highlight) => setOpen({ kind: "page", doc_id, page, highlight })} onClose={() => setOpen(null)} />}
          </aside>
        </div>
      )}
    </>
  );
}

function CompareChart({ res, metricId, setMetricId, name }: {
  res: CompareRes; metricId: string; setMetricId: (m: string) => void; name: (s: string) => string;
}) {
  const [tip, setTip] = useState<Tip>(null);
  const rows = res.symbols.map(s => ({ s, v: shown(res.table[s]?.[metricId]) }));
  const have = rows.filter(r => r.v != null) as { s: string; v: number }[];
  const picker = (
    <label className="field chart-pick">Chart
      <select value={metricId} onChange={e => setMetricId(e.target.value)}>
        {res.metrics.map(m => <option key={m} value={m}>{metric(m).label}</option>)}
      </select>
    </label>
  );
  if (have.length < 2) return <div className="block">{picker}<p className="hint">Not enough companies have this figure for this period to draw a chart.</p></div>;

  const W = 760, L = 210, R = 110, T = 8, barH = 26, gap = 18, H = T + rows.length * (barH + gap) + 26;
  const lo = Math.min(0, ...have.map(r => r.v)), hi = Math.max(0, ...have.map(r => r.v));
  const x = (v: number) => L + ((v - lo) / (hi - lo || 1)) * (W - L - R);
  const top = [...have].sort((a, b) => b.v - a.v)[0];
  const lbl = metric(metricId).label;
  const takeaway = `${name(top.s)} has the highest ${lbl.toLowerCase()}: ${fmtShown(top.v, metricId)}${metric(metricId).kind === "money" ? " million rupees" : ""}.`;

  return (
    <div className="block">
      {picker}
      <ChartFrame takeaway={takeaway} note={`${lbl}, ${unitLabel(metricId)}. Values from checked report pages; ratios calculated by code.`}
        tip={tip} head={["Company", `${lbl} (${unitLabel(metricId)})`]}
        rows={rows.map(r => [name(r.s), fmtShown(r.v, metricId)])}>
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={takeaway} onMouseLeave={() => setTip(null)}>
          <line x1={x(0)} x2={x(0)} y1={T} y2={H - 20} className="grid" />
          {rows.map((r, i) => {
            const y = T + i * (barH + gap);
            const show = () => r.v != null && setTip({ x: (x(r.v) / W) * 100, y: (y / H) * 100, text: `${name(r.s)}: ${fmtShown(r.v, metricId)}` });
            return (
              <g key={r.s}>
                <text x={L - 12} y={y + barH / 2 + 5} textAnchor="end" className="row-label">{name(r.s)}</text>
                {r.v == null
                  ? <text x={x(0) + 6} y={y + barH / 2 + 5} className="tick">not available</text>
                  : <>
                      <rect x={Math.min(x(0), x(r.v))} y={y} width={Math.abs(x(r.v) - x(0))} height={barH}
                        className={`bar ${r.s === top.s ? "best" : ""}`} tabIndex={0}
                        aria-label={`${name(r.s)}, ${fmtShown(r.v, metricId)}`} onMouseEnter={show} onFocus={show} onBlur={() => setTip(null)} />
                      <text x={Math.max(x(0), x(r.v)) + 8} y={y + barH / 2 + 5} className="bar-value">{fmtShown(r.v, metricId)}</text>
                    </>}
              </g>
            );
          })}
        </svg>
      </ChartFrame>
    </div>
  );
}

"use client";
import { useEffect, useMemo, useState } from "react";
import { api, shortName } from "@/lib/api";
import { PageEvidence } from "@/components/EvidencePanel";
import { CalcCell } from "@/components/CalcCell";
import { ChartFrame, type Tip } from "@/components/charts/ChartFrame";
import {
  METRICS, factDocs, fmtShown, freqName, metric, periodName, printed, shown, unitLabel,
  type Cell, type Company, type TrendsRes,
} from "@/lib/facts";

const DEFAULT_METRICS = ["revenue", "net_profit", "eps_basic", "net_margin", "revenue_growth"];
type Open = { kind: "page"; doc_id: string; page: number; highlight?: string } | { kind: "calc"; cell: Cell };

export default function TrendsPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [symbol, setSymbol] = useState("");
  const [months, setMonths] = useState(12);
  const [metrics, setMetrics] = useState<string[]>(DEFAULT_METRICS);
  const [res, setRes] = useState<TrendsRes | null>(null);
  const [open, setOpen] = useState<Open | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    api<Company[]>("/facts").then(cs => { setCompanies(cs); if (cs[0]) setSymbol(cs[0].symbol); })
      .catch(e => { setCompanies([]); setErr(e.message); });
  }, []);

  const company = companies?.find(c => c.symbol === symbol);
  const freqs = useMemo(() => [...new Set((company?.periods || []).map(p => p.months))].sort((a, b) => b - a), [company]);
  useEffect(() => { if (freqs.length && !freqs.includes(months)) setMonths(freqs[0]); }, [freqs]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!symbol || !metrics.length) return;
    setBusy(true); setErr(""); setOpen(null);
    api<TrendsRes>(`/trends/${symbol}?metrics=${metrics.join(",")}`)
      .then(setRes).catch(e => { setRes(null); setErr(e.message); }).finally(() => setBusy(false));
  }, [symbol, metrics]);

  // a trend only makes sense between periods of the same length: never a quarter next to a year
  const periods = useMemo(() => (res?.periods || []).filter(p => company?.periods.some(x => x.period_end === p && x.months === months)), [res, company, months]);

  if (companies === null) return <p className="loading"><span className="spinner" aria-hidden="true" />Loading the verified figures…</p>;
  if (!companies.length) return (
    <section className="first-step">
      <h1>Trends</h1>
      <p className="lede">No verified figures yet. Trends use only figures a person has checked against the report.</p>
      {err && <p className="err" role="alert">{err}</p>}
    </section>
  );

  const docs = factDocs(companies, Object.values(res?.series || {}).flatMap(r => Object.values(r).flatMap(c => [c.doc_id, ...(c.operands || []).map(o => o.doc_id)])));
  const name = (s: string) => shortName(companies.find(c => c.symbol === s)?.company || s);

  return (
    <>
      <h1>Trends</h1>
      <p className="lede">Each chart is drawn from checked report figures, and ratios are calculated by code. Nothing here is estimated by the AI.</p>

      <div className="controls panel">
        <div className="row controls-row">
          <label className="field">Company
            <select value={symbol} onChange={e => setSymbol(e.target.value)}>
              {companies.map(c => <option key={c.symbol} value={c.symbol}>{shortName(c.company)} ({c.symbol})</option>)}
            </select>
          </label>
          <label className="field">Period length
            <select value={months} onChange={e => setMonths(+e.target.value)}>
              {freqs.map(m => <option key={m} value={m}>{freqName[m] ?? `${m} months`}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="pick">
          <legend>Figures and ratios</legend>
          <div className="chips">
            {METRICS.map(m => (
              <label key={m.id} className="chip">
                <input type="checkbox" checked={metrics.includes(m.id)}
                  onChange={() => setMetrics(metrics.includes(m.id) ? metrics.filter(x => x !== m.id) : [...metrics, m.id])} />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {res?.basis && <p className="hint">Using {res.basis} statements.</p>}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      {busy && <p className="loading"><span className="spinner" aria-hidden="true" />Loading…</p>}

      {res && !busy && (
        <div className="workspace">
          <section className="answer-col wide" aria-label="Trends">
            {periods.length < 2 && (
              <p className="notice">Only {periods.length} {freqName[months]?.toLowerCase() ?? ""} period is available for {name(symbol)}, so there is no trend to draw yet. Each verified report adds its current and prior period.</p>
            )}
            {periods.length >= 1 && res.metrics.map(m => (
              <TrendChart key={m} m={m} periods={periods} cells={periods.map(p => res.series[p]?.[m])} months={months}
                onOpen={c => c.formula ? setOpen({ kind: "calc", cell: c })
                  : c.doc_id && c.page && setOpen({ kind: "page", doc_id: c.doc_id, page: c.page, highlight: printed(c.value!, c.unit) })} />
            ))}
          </section>
          <aside className={`evidence ${open ? "is-open" : ""}`} aria-label="Evidence">
            {!open && <p className="evidence-empty">Select a point to see the report page it came from, or a ratio to see how it was calculated.</p>}
            {open?.kind === "page" && <PageEvidence key={`${open.doc_id}#${open.page}#${open.highlight}`} view={open} docs={docs} onClose={() => setOpen(null)} />}
            {open?.kind === "calc" && <CalcCell cell={open.cell} name={name}
              onPage={(doc_id, page, highlight) => setOpen({ kind: "page", doc_id, page, highlight })} onClose={() => setOpen(null)} />}
          </aside>
        </div>
      )}
    </>
  );
}

function TrendChart({ m, periods, cells, months, onOpen }: {
  m: string; periods: string[]; cells: (Cell | undefined)[]; months: number; onOpen: (c: Cell) => void;
}) {
  const [tip, setTip] = useState<Tip>(null);
  const vals = cells.map(shown);
  const have = vals.filter((v): v is number => v != null);
  const lbl = metric(m).label;
  const when = (p: string) => periodName({ period_end: p, period_type: "", months });
  const year = (p: string) => (months === 12 ? "FY" : "") + p.slice(0, 4) + (months === 12 ? "" : `-${p.slice(5, 7)}`);

  let takeaway = `${lbl}: not enough checked figures to show a change.`;
  const firstI = vals.findIndex(v => v != null), lastI = vals.length - 1 - [...vals].reverse().findIndex(v => v != null);
  if (have.length >= 2 && firstI < lastI) {
    const a = vals[firstI]!, b = vals[lastI]!;
    const dir = b > a ? "rose" : b < a ? "fell" : "was unchanged";
    const pct = metric(m).kind !== "pct" && a > 0 ? ` (${b > a ? "+" : ""}${(((b - a) / a) * 100).toFixed(1)}%)` : "";
    takeaway = `${lbl} ${dir} from ${fmtShown(a, m)} to ${fmtShown(b, m)}${pct} between ${year(periods[firstI])} and ${year(periods[lastI])}.`;
  } else if (have.length === 1) {
    takeaway = `${lbl}: ${fmtShown(have[0], m)} in ${year(periods[firstI])}.`;
  }

  const W = 720, L = 70, R = 20, T = 24, B = 34, H = 220;
  const lo = Math.min(0, ...have), hi = Math.max(0, ...have);
  const y = (v: number) => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  const step = (W - L - R) / Math.max(periods.length, 1);
  const bw = Math.min(64, step * 0.5);

  return (
    <ChartFrame takeaway={takeaway} note={`${lbl}, ${unitLabel(m)}, ${(freqName[months] ?? "").toLowerCase()} periods. Select a bar to see its source.`}
      tip={tip} head={["Period", `${lbl} (${unitLabel(m)})`, "Note"]}
      rows={periods.map((p, i) => [when(p), fmtShown(vals[i], m), cells[i]?.refused ? (cells[i]?.reason ?? "") : cells[i]?.formula ? "calculated" : "printed"])}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={takeaway} onMouseLeave={() => setTip(null)}>
        <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} className="grid" />
        {periods.map((p, i) => {
          const cx = L + step * (i + 0.5), v = vals[i], c = cells[i];
          return (
            <g key={p}>
              <text x={cx} y={H - 10} textAnchor="middle" className="tick">{year(p)}</text>
              {v == null
                ? <text x={cx} y={y(0) - 8} textAnchor="middle" className="tick">{c?.refused ? "refused" : "—"}</text>
                : <>
                    <rect x={cx - bw / 2} y={Math.min(y(0), y(v))} width={bw} height={Math.max(1, Math.abs(y(v) - y(0)))}
                      className={`bar ${c?.formula ? "calc" : ""}`} tabIndex={0} role="button"
                      aria-label={`${when(p)}: ${fmtShown(v, m)}. Show source.`}
                      onClick={() => c && onOpen(c)} onKeyDown={e => { if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen(c); } }}
                      onMouseEnter={() => setTip({ x: (cx / W) * 100, y: (y(v) / H) * 100, text: `${when(p)}: ${fmtShown(v, m)}` })}
                      onFocus={() => setTip({ x: (cx / W) * 100, y: (y(v) / H) * 100, text: `${when(p)}: ${fmtShown(v, m)}` })}
                      onBlur={() => setTip(null)} />
                    <text x={cx} y={v >= 0 ? y(v) - 6 : y(v) + 16} textAnchor="middle" className="bar-value">{fmtShown(v, m)}</text>
                  </>}
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

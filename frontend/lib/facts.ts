// Verified facts, /compare and /trends (all numbers come from the facts store and
// ratios.py in the backend; nothing here is produced by the LLM).
import type { Doc } from "@/lib/api";

export type Period = { period_end: string; period_type: string; months: number };
export type Company = { symbol: string; company: string; bases: string[]; periods: Period[] };

export type Operand = { field: string; period: string; value: number; doc_id: string; page: number | null; basis?: string; unit?: string };
export type Cell = {
  symbol: string; metric: string; period_end: string | null; basis: string | null;
  value: number | null; unit?: string; doc_id: string | null; page: number | null;
  period_type?: string; months?: number; source?: string;
  formula?: string; operands?: Operand[]; refused: boolean; reason?: string;
};
export type CompareRes = { period_end: string | null; symbols: string[]; metrics: string[]; rows: Cell[]; table: Record<string, Record<string, Cell>> };
export type TrendsRes = { symbol: string; company: string; basis: string | null; metrics: string[]; periods: string[]; series: Record<string, Record<string, Cell>> };

export type Metric = { id: string; label: string; kind: "money" | "eps" | "pct" };
// Raw fields we label for every report, then the ratios ratios.py can compute from them.
export const METRICS: Metric[] = [
  { id: "revenue", label: "Revenue", kind: "money" },
  { id: "profit_before_tax", label: "Profit before tax", kind: "money" },
  { id: "net_profit", label: "Profit after tax", kind: "money" },
  { id: "eps_basic", label: "Earnings per share", kind: "eps" },
  { id: "total_assets", label: "Total assets", kind: "money" },
  { id: "total_equity", label: "Total equity", kind: "money" },
  { id: "net_margin", label: "Net margin", kind: "pct" },
  { id: "roe", label: "Return on equity", kind: "pct" },
  { id: "roa", label: "Return on assets", kind: "pct" },
  { id: "revenue_growth", label: "Revenue growth", kind: "pct" },
  { id: "earnings_growth", label: "Profit growth", kind: "pct" },
  { id: "eps_growth", label: "EPS growth", kind: "pct" },
];
export const metric = (id: string): Metric => METRICS.find(m => m.id === id) ?? { id: String(id ?? ""), label: String(id ?? "").replaceAll("_", " "), kind: "pct" };

const SCALE: Record<string, number> = { units: 1, rupees: 1, thousands: 1e3, millions: 1e6, billions: 1e9 };

/** A cell's value in the unit its row is shown in: Rs million for money, Rs for EPS, % for ratios.
 *  Reports print in rupees, thousands or millions, so money is rescaled in code before comparing. */
export function shown(c: Cell | undefined): number | null {
  if (!c || c.refused || c.value == null) return null;
  const k = metric(c.metric).kind;
  if (k === "money") return (c.value * (SCALE[(c.unit || "thousands").toLowerCase()] ?? 1)) / 1e6;
  return c.value;
}
export const unitLabel = (id: string) => ({ money: "Rs million", eps: "Rs per share", pct: "%" }[metric(id).kind]);

export function fmtShown(v: number | null, id: string): string {
  if (v == null) return "—";
  const k = metric(id).kind;
  if (k === "pct") return `${v.toFixed(1)}%`;
  if (k === "eps") return v.toFixed(2);
  return v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) < 100 ? 1 : 0 });
}

/** The number exactly as printed in the report, so the page image can box it. */
export function printed(v: number, unit?: string): string {
  if (unit && /per share/i.test(unit)) return Math.abs(v).toFixed(2);
  return Number.isInteger(v) ? Math.abs(v).toLocaleString("en-US") : Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export const periodName = (p: Period) => {
  const d = new Date(p.period_end + "T00:00:00");
  const when = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  const kind = p.months === 12 ? "year" : p.months === 9 ? "nine months" : p.months === 6 ? "six months" : p.months === 3 ? "quarter" : p.period_type;
  return `${kind} to ${when}`;
};
export const freqName: Record<number, string> = { 12: "Annual", 9: "Nine months", 6: "Half-year", 3: "Quarter" };

/** Library-style labels for labelled reports that were never ingested ("LUCK_FY2026"). */
export function factDocs(companies: Company[], ids: (string | null | undefined)[]): Doc[] {
  return [...new Set(ids.filter(Boolean) as string[])].map(id => {
    const sym = id.split("_")[0];
    const c = companies.find(x => x.symbol === sym);
    const per = id.slice(sym.length + 1);
    const type = /^Q\d/.test(per) ? "quarterly" : /^H1/.test(per) ? "half-yearly" : /^9M/.test(per) ? "nine-months" : "annual";
    return { doc_id: id, company: c?.company ?? sym, symbol: sym, doc_type: type, period: per, n_pages: 0, source_url: "" };
  });
}

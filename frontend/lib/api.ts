export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Citation = { doc_id: string; page: number; quote?: string };
export type Calculation = { expression: string; variables: Record<string, number>; result: number | null; error: string | null };
/** Where one number in the answer came from (worked out by the backend, not the LLM). */
export type Evidence = {
  text: string; value: number; status: "found" | "computed" | "unverified";
  doc_id?: string; page?: number; match?: string; calc?: number;
};
export type Answer = {
  question: string; answer: string; citations: Citation[]; calculations: Calculation[];
  context_pages: Citation[]; mode: string; steps: number; latency_s: number;
  tokens_in: number; tokens_out: number; cost_usd: number; refused: boolean; grounding: number;
  evidence?: Evidence[];
  // v2 three-part answer (backend): figures printed in the report, values computed by code,
  // and an explanation that may only quote the report
  reported_figures?: ReportedFigure[];
  calculated_values?: CalculatedValue[];
  explanation?: string;
  refusal_reason?: string | null;
  basis?: string | null;
};
export type ReportedFigure = { field: string; value: number; unit?: string; statement?: string; period?: string; page?: number | null; doc_id?: string };
export type CalculatedValue = { name: string; formula: string; result: number | null;
  operands?: { field: string; period: string; value: number; doc_id?: string; page?: number | null; basis?: string }[] };
export type Doc = { doc_id: string; company: string; symbol: string; doc_type: string; period: string; n_pages: number; source_url: string };

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, { cache: "no-store", ...init });
  } catch {
    // The browser only says "Failed to fetch": either the server is down or it crashed mid-request.
    throw new Error("No response from the Mizan server. Check that uvicorn is running, and look in its window for an error.");
  }
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

export const postJSON = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/** "LUCK_Q2026_288146" -> "Lucky Cement, quarterly 2026" using the library list. */
export function docLabel(doc_id: string, docs: Doc[]): string {
  const d = docs.find(x => x.doc_id === doc_id);
  if (!d) return doc_id;
  const year = (d.period.match(/20\d\d/) || [""])[0];
  const name = d.company && d.company !== d.symbol ? shortName(d.company) : d.symbol;
  return `${name}, ${d.doc_type}${year ? " " + year : ""}`;
}

export function shortName(company: string): string {
  return company.replace(/\b(Company )?Limited\b|\bLtd\.?\b/gi, "").replace(/^The /, "").trim();
}

export const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: Math.abs(v) < 1000 ? digits : 0 });

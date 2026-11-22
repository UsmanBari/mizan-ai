// Human names for the IDs that come out of the experiments and the API.

const METHOD: Record<string, string> = {
  "bm25": "BM25",
  "bm25:expand": "BM25 + finance glossary",
  "bm25:route": "BM25 + company/year routing",
  "bm25x": "BM25 + glossary + routing",
  "dense": "Dense embeddings (BGE)",
  "hybrid": "Hybrid (BM25 + dense)",
  "hybrid:rerank": "Hybrid + reranker",
  "rerank": "Hybrid + reranker",
};
const SCOPE: Record<string, string> = { scoped: "scoped to company and year", open: "across all 84 filings" };

/** "bm25:expand|scoped" -> { method: "BM25 + finance glossary", scope: "scoped to company and year" } */
export function systemName(id: string) {
  const [m, sc] = id.split("|");
  return { method: METHOD[m] ?? m, scope: sc ? (SCOPE[sc] ?? sc) : "", scoped: sc === "scoped", key: m };
}
export const systemLabel = (id: string) => { const s = systemName(id); return s.scope ? `${s.method}, ${s.scope}` : s.method; };

export const MODE_NAME: Record<string, string> = {
  agent: "Agent with calculator",
  rag_calc: "Search + calculator",
  rag_direct: "Search only (AI does the maths)",
  closed_book: "No search (AI from memory)",
};
export const modeName = (id: string) => MODE_NAME[id] ?? id;

export const COLUMN: Record<string, string> = {
  "recall@1": "Recall@1", "recall@3": "Recall@3", "recall@5": "Recall@5", "recall@10": "Recall@10",
  "mrr@10": "MRR@10", "ndcg@10": "nDCG@10", "latency_p50_ms": "Median latency (ms)", "latency_p95_ms": "95th pct latency (ms)",
  "failures_at5": "Misses at 5", "n": "Questions",
  "accuracy_mean": "Accuracy", "accuracy_std": "Std. dev.", "hallucination_rate": "Hallucination rate",
  "refusal_rate": "Refusal rate", "citation_correct": "Correct citation", "latency_p50_s": "Median latency (s)",
  "latency_p95_s": "95th pct latency (s)", "cost_per_request_usd": "Cost per question (USD)", "steps_mean": "Mean steps",
  "field_accuracy": "Field accuracy", "n_examples": "Examples", "coverage": "Coverage", "schema_valid_rate": "Valid JSON",
  "unit_accuracy": "Unit accuracy", "statement_page_located": "Statement page found", "cost_per_report_usd": "Cost per report (USD)",
};
export const columnName = (k: string) => COLUMN[k] ?? k.replaceAll("_", " ");

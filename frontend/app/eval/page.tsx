"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { columnName, modeName, systemLabel } from "@/lib/labels";
import { DotPlot } from "@/components/charts/DotPlot";
import { Scatter } from "@/components/charts/Scatter";
import { BarChart } from "@/components/charts/BarChart";

type Section = Record<string, Record<string, any>>;
const SIG = ["recall@1", "recall@3", "recall@5", "recall@10", "mrr@10", "ndcg@10", "accuracy_mean", "field_accuracy"];

function sameAs(rows: [string, Record<string, any>][], i: number): string | null {
  const sig = (v: Record<string, any>) => SIG.map(k => v[k]).join("|");
  const s = sig(rows[i][1]);
  if (!SIG.some(k => rows[i][1][k] != null)) return null;
  const j = rows.findIndex(([, v], idx) => idx < i && sig(v) === s);
  return j >= 0 ? rows[j][0] : null;
}

function ResultsTable({ data, cols, name }: { data: Section; cols: string[]; name: (id: string) => string }) {
  const rows = Object.entries(data).filter(([, v]) => v && typeof v === "object" && !Array.isArray(v) && cols.some(c => c in v));
  if (!rows.length) return <p className="muted">No results yet.</p>;
  const fmt = (v: any, k: string) => typeof v !== "number" ? (v ?? "—")
    : k.includes("latency") || k === "n" || k.startsWith("failures") || k.startsWith("n_") ? v.toLocaleString()
    : k.includes("cost") ? `$${v.toFixed(5)}` : v.toFixed(3);
  return (
    <div className="table-scroll">
      <table className="results">
        <thead><tr><th>System</th>{cols.map(c => <th key={c} className="num">{columnName(c)}</th>)}</tr></thead>
        <tbody>
          {rows.map(([id, v], i) => {
            const dup = sameAs(rows, i);
            const routing = dup && /route|bm25x/.test(id) && id.endsWith("|scoped");
            return (
              <tr key={id} className={dup ? "dup" : ""}>
                <th scope="row">{name(id)}
                  {dup && <span className="dup-note">Same scores as {name(dup)}{routing ? ": routing changes nothing when the search is already limited to one company and year." : "."}</span>}
                </th>
                {cols.map(c => <td key={c} className="num">{fmt(v[c], c)}</td>)}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Eval() {
  const [s, setS] = useState<Record<string, Section> | null>(null);
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Record<string, Section>>("/eval/summary").then(setS).catch(e => setErr(e.message));
    api("/metrics").then(setM).catch(() => {});
  }, []);

  const qaRows = s?.qa ? Object.fromEntries(Object.entries(s.qa).filter(([k]) => k !== "paired_tests")) as Section : undefined;

  return (
    <>
      <h1>Evaluation</h1>
      <p className="lede">Results from our experiments, loaded from eval/results/summary.json. Every number can be reproduced with the scripts in eval/. Test sets: FinanceBench (140 questions over 84 filings) and our hand-labelled PSX set.</p>
      {err && <p className="err">{err}</p>}

      {s?.retrieval && (
        <section className="block">
          <h2>Finding the right page</h2>
          <DotPlot data={s.retrieval as Record<string, Record<string, number>>} />
          <Scatter data={s.retrieval as Record<string, Record<string, number>>} />
          <ResultsTable data={s.retrieval} name={systemLabel}
            cols={["recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10", "latency_p50_ms", "failures_at5"]} />
        </section>
      )}

      <section className="block">
        <h2>Answering questions</h2>
        <BarChart data={qaRows as Record<string, Record<string, number>> | undefined} />
        {qaRows && <ResultsTable data={qaRows} name={modeName}
          cols={["accuracy_mean", "accuracy_std", "hallucination_rate", "refusal_rate", "citation_correct", "latency_p50_s", "cost_per_request_usd", "steps_mean"]} />}
        {s?.qa?.paired_tests && (<><h3 className="sub-h">Paired McNemar tests</h3>
          <ResultsTable data={s.qa.paired_tests as Section} name={id => id.split("_vs_").map(modeName).join(" vs ")}
            cols={Object.keys(Object.values(s.qa.paired_tests as Section)[0] || {}).filter(k => typeof (Object.values(s.qa.paired_tests as Section)[0] as any)[k] !== "object")} /></>)}
      </section>

      {s?.qa_psx && (
        <section className="block">
          <h2>Answering questions on PSX reports</h2>
          <ResultsTable data={s.qa_psx} name={modeName} cols={["accuracy_mean", "hallucination_rate", "refusal_rate", "latency_p50_s", "cost_per_request_usd"]} />
        </section>
      )}

      <section className="block">
        <h2>Extracting key figures</h2>
        {s?.extraction
          ? <ResultsTable data={s.extraction} name={id => id.replace(/^api:/, "Gemini API: ").replace(/^local:/, "Local model: ").replace(/^rules$/, "Rules (no AI)")}
              cols={["field_accuracy", "n_examples", "coverage", "schema_valid_rate", "unit_accuracy", "statement_page_located", "latency_p50_s", "cost_per_report_usd"]} />
          : <p className="muted">Extraction results appear here once notebook 03 (eval/run_extraction.py) has run on the labelled PSX reports.</p>}
      </section>

      {m && m.requests > 0 && (
        <section className="block">
          <h2>This server, live</h2>
          <dl className="stats">
            <div><dt>Questions answered</dt><dd>{m.requests}</dd></div>
            <div><dt>Median time</dt><dd>{m.latency_p50_s.toFixed(1)} s</dd></div>
            <div><dt>95th percentile time</dt><dd>{m.latency_p95_s.toFixed(1)} s</dd></div>
            <div><dt>Mean cost at paid-tier prices</dt><dd>${m.mean_cost_usd.toFixed(5)}</dd></div>
            <div><dt>Refused</dt><dd>{(100 * m.refusal_rate).toFixed(0)}%</dd></div>
          </dl>
        </section>
      )}
    </>
  );
}

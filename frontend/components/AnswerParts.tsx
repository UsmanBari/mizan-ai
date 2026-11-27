"use client";
import { docLabel, fmt, type Answer, type Doc } from "@/lib/api";
import { metric } from "@/lib/facts";

const fieldName = (f: string) => { const m = metric(f); return m.label === f.replaceAll("_", " ") ? f.replaceAll("_", " ") : m.label; };
const printedAs = (v: number) => Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 2 });

/** The answer split into its three parts, so the reader can see which numbers were read from
 *  the report, which were calculated by code, and that any "why" is quoted, not invented. */
export function AnswerParts({ ans, docs, openPage }: {
  ans: Answer; docs: Doc[]; openPage: (doc_id: string, page: number, highlight?: string) => void;
}) {
  const rep = ans.reported_figures || [];
  const calc = ans.calculated_values || [];
  const docFor = (page?: number | null, doc?: string) =>
    doc || ans.citations.find(c => c.page === page)?.doc_id || ans.citations[0]?.doc_id || "";
  if (!rep.length && !calc.length && !ans.explanation && !ans.refusal_reason) return null;

  return (
    <section className="parts" aria-label="Answer in three parts">
      {ans.refused && ans.refusal_reason && (
        <div className="refusal" role="note">
          <h2>Mizan did not answer</h2>
          <p>{ans.refusal_reason}</p>
          <p className="hint">It refuses instead of guessing when a figure is missing, the periods do not match, or two pages disagree.</p>
        </div>
      )}

      {rep.length > 0 && (
        <div className="part">
          <h2><span className="part-mark found" aria-hidden="true" />Reported in the filing</h2>
          <div className="table-scroll">
            <table className="inputs">
              <thead><tr><th>Figure</th><th>Period</th><th className="num">As printed</th><th>Source</th></tr></thead>
              <tbody>
                {rep.map((r, i) => {
                  const d = docFor(r.page, r.doc_id);
                  return (
                    <tr key={i}>
                      <td>{fieldName(r.field)}{r.statement ? <span className="muted"> · {r.statement}</span> : null}</td>
                      <td>{r.period || "—"}</td>
                      <td className="num">{printedAs(r.value)}{r.unit ? <span className="muted"> {r.unit === "thousands" ? "Rs '000" : r.unit}</span> : null}</td>
                      <td>{r.page && d
                        ? <button type="button" className="link" onClick={() => openPage(d, r.page!, printedAs(r.value))}>{docLabel(d, docs)}, p. {r.page}</button>
                        : <span className="muted">—</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {calc.length > 0 && (
        <div className="part">
          <h2><span className="part-mark computed" aria-hidden="true" />Calculated by code</h2>
          <ul className="calc-list">
            {calc.map((c, i) => (
              <li key={i}>
                <strong>{fieldName(c.name)}</strong> = <code>{c.formula}</code> = <strong>{fmt(c.result, 4)}{/margin|growth|ro[ae]|pct/i.test(c.name) ? "%" : ""}</strong>
                {c.operands && c.operands.length > 0 && (
                  <span className="muted"> using {c.operands.map((o, j) => (
                    <span key={j}>{j ? ", " : ""}{fieldName(o.field)} {o.period} = {o.page && (o.doc_id || docFor(o.page))
                      ? <button type="button" className="link" onClick={() => openPage(o.doc_id || docFor(o.page), o.page!, printedAs(o.value))}>{printedAs(o.value)}</button>
                      : printedAs(o.value)}</span>))}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {(ans.explanation || "").trim() && (
        <div className="part">
          <h2><span className="part-mark quote" aria-hidden="true" />Explanation</h2>
          <p className={/does not state a reason/i.test(ans.explanation!) ? "muted" : ""}>{ans.explanation}</p>
          <p className="hint">Only text quoted from a cited page may appear here. If the report gives no reason, Mizan says so instead of inventing one.</p>
        </div>
      )}
      {ans.basis && <p className="hint">Figures from the {ans.basis} statements.</p>}
    </section>
  );
}

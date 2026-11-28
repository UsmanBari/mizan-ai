"use client";
import { docLabel, fmt, type Answer, type Doc } from "@/lib/api";
import { metric } from "@/lib/facts";

// The agent's structured parts come from the model and code together, so any field can be
// missing or the wrong type: render what is there, never crash the page.
const fieldName = (f: unknown) => metric(String(f ?? "value")).label || "value";
const num = (v: unknown): number | null => { const n = typeof v === "number" ? v : Number(String(v ?? "").replace(/,/g, "")); return Number.isFinite(n) ? n : null; };
const printedAs = (v: unknown) => { const n = num(v); return n == null ? String(v ?? "—") : Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 }); };

/** The answer split into its three parts, so the reader can see which numbers were read from
 *  the report, which were calculated by code, and that any "why" is quoted, not invented. */
export function AnswerParts({ ans, docs, openPage }: {
  ans: Answer; docs: Doc[]; openPage: (doc_id: string, page: number, highlight?: string) => void;
}) {
  const rep = (Array.isArray(ans.reported_figures) ? ans.reported_figures : []).filter(r => r && typeof r === "object");
  const calc = (Array.isArray(ans.calculated_values) ? ans.calculated_values : []).filter(c => c && typeof c === "object");
  const cites = Array.isArray(ans.citations) ? ans.citations : [];
  const docFor = (page?: number | null, doc?: string) =>
    doc || cites.find(c => c.page === page)?.doc_id || cites[0]?.doc_id || "";
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
                      <td>{fieldName(r.field)}{r.statement ? <span className="muted"> · {String(r.statement)}</span> : null}</td>
                      <td>{String(r.period ?? "") || "—"}</td>
                      <td className="num">{printedAs(r.value)}{r.unit ? <span className="muted"> {r.unit === "thousands" ? "Rs '000" : String(r.unit)}</span> : null}</td>
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
                <strong>{fieldName(c.name)}</strong> = <code>{String(c.formula ?? "")}</code> = <strong>{fmt(num(c.result), 4)}{/margin|growth|ro[ae]|pct/i.test(String(c.name ?? "")) ? "%" : ""}</strong>
                {Array.isArray(c.operands) && c.operands.length > 0 && (
                  <span className="muted"> using {c.operands.map((o, j) => (
                    <span key={j}>{j ? ", " : ""}{fieldName(o.field)} {String(o.period ?? "")} = {o.page && (o.doc_id || docFor(o.page))
                      ? <button type="button" className="link" onClick={() => openPage(o.doc_id || docFor(o.page), o.page!, printedAs(o.value))}>{printedAs(o.value)}</button>
                      : printedAs(o.value)}</span>))}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {String(ans.explanation ?? "").trim() !== "" && (
        <div className="part">
          <h2><span className="part-mark quote" aria-hidden="true" />Explanation</h2>
          <p className={/does not state a reason/i.test(String(ans.explanation)) ? "muted" : ""}>{String(ans.explanation)}</p>
          <p className="hint">Only text quoted from a cited page may appear here. If the report gives no reason, Mizan says so instead of inventing one.</p>
        </div>
      )}
      {ans.basis && <p className="hint">Figures from the {ans.basis} statements.</p>}
    </section>
  );
}

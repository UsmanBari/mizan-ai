"use client";
import { fmtShown, metric, printed, type Cell } from "@/lib/facts";

/** Evidence panel content for a ratio cell: the formula, each input as printed with its page, the result. */
export function CalcCell({ cell, name, onPage, onClose }: {
  cell: Cell; name: (s: string) => string; onPage: (doc: string, page: number, hl?: string) => void; onClose: () => void;
}) {
  return (
    <>
      <div className="evidence-head">
        <div>
          <div className="evidence-title">{name(cell.symbol)}: {metric(cell.metric).label}</div>
          <div className="evidence-note">Calculated by code from figures printed in the report. No AI involved.</div>
        </div>
        <button type="button" className="ghost close" onClick={onClose} aria-label="Close">Close</button>
      </div>
      <div className="calc-body">
        <code className="expr">{cell.formula}</code>
        <table className="inputs">
          <thead><tr><th>Input</th><th>Period</th><th className="num">As printed</th><th>Source</th></tr></thead>
          <tbody>
            {(cell.operands || []).map((o, i) => (
              <tr key={i}>
                <td>{metric(o.field).label}</td>
                <td>{o.period}</td>
                <td className="num">{printed(o.value, o.unit)}</td>
                <td>{o.page ? <button type="button" className="link" onClick={() => onPage(o.doc_id, o.page!, printed(o.value, o.unit))}>page {o.page}</button> : <span className="muted">—</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="result"><span className="muted">Result</span> {fmtShown(cell.value, cell.metric)}</p>
      </div>
    </>
  );
}

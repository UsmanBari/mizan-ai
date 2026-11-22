"use client";
import { useId, useState, type ReactNode } from "react";

export type Tip = { x: number; y: number; text: string } | null;   // x, y in % of the chart box

/** Shared chart shell: a one-sentence takeaway as the heading, the SVG, a tooltip
 *  that works on hover and keyboard focus, and a "Show table" toggle with the same data. */
export function ChartFrame({ takeaway, note, tip, head, rows, children }: {
  takeaway: string; note?: string; tip: Tip; head: string[]; rows: (string | number)[][]; children: ReactNode;
}) {
  const [table, setTable] = useState(false);
  const id = useId();
  return (
    <figure className="chart">
      <figcaption>
        <h3 id={id}>{takeaway}</h3>
        {note && <p className="hint">{note}</p>}
      </figcaption>
      <div className="chart-box" aria-labelledby={id}>
        {children}
        {tip && <div className="tip" role="status" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>{tip.text}</div>}
      </div>
      <button type="button" className="text-btn" aria-expanded={table} onClick={() => setTable(!table)}>
        {table ? "Hide table" : "Show table"}
      </button>
      {table && (
        <table className="chart-table">
          <thead><tr>{head.map(h => <th key={h} className={h === head[0] ? "" : "num"}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j ? "num" : ""}>{c}</td>)}</tr>)}</tbody>
        </table>
      )}
    </figure>
  );
}

export const f2 = (v: number) => v.toFixed(2);

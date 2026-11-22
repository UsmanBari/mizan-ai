"use client";
import { useState } from "react";
import { ChartFrame, type Tip } from "./ChartFrame";
import { modeName } from "@/lib/labels";

type Row = Record<string, number>;
const ORDER = ["closed_book", "rag_direct", "rag_calc", "agent"];
const rank = (k: string) => { const i = ORDER.indexOf(k); return i < 0 ? 99 : i; };

/** QA accuracy per answer method, with ±1 standard deviation across runs when available. */
export function BarChart({ data }: { data: Record<string, Row> | undefined }) {
  const [tip, setTip] = useState<Tip>(null);
  const rows = Object.entries(data || {}).filter(([k, v]) => v && typeof v.accuracy_mean === "number" && k !== "paired_tests")
    .sort((a, b) => rank(a[0]) - rank(b[0]));
  if (!rows.length) {
    return (
      <figure className="chart">
        <figcaption><h3>Answer accuracy per method will appear here once the QA experiment has run.</h3>
          <p className="hint">Run notebook 02 (eval/run_qa.py) to compare the four answer methods on FinanceBench.</p></figcaption>
      </figure>
    );
  }
  const W = 760, L = 250, R = 70, T = 10, barH = 28, gap = 22, H = T + rows.length * (barH + gap) + 30;
  const x = (v: number) => L + v * (W - L - R);
  const best = [...rows].sort((a, b) => b[1].accuracy_mean - a[1].accuracy_mean)[0];
  const takeaway = `${modeName(best[0])} answers ${Math.round(100 * best[1].accuracy_mean)}% of questions correctly, the highest of the methods tested.`;
  const show = (k: string, v: Row, cy: number) => setTip({ x: (x(v.accuracy_mean) / W) * 100, y: (cy / H) * 100,
    text: `${modeName(k)}: ${(100 * v.accuracy_mean).toFixed(1)}%${v.accuracy_std ? ` ± ${(100 * v.accuracy_std).toFixed(1)}` : ""}` });

  return (
    <ChartFrame takeaway={takeaway} note="Share of FinanceBench test questions answered correctly. Whiskers show ±1 standard deviation across runs."
      tip={tip} head={["Method", "Accuracy", "Std. dev."]}
      rows={rows.map(([k, v]) => [modeName(k), `${(100 * v.accuracy_mean).toFixed(1)}%`, v.accuracy_std != null ? `${(100 * v.accuracy_std).toFixed(1)}` : "—"])}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={takeaway} onMouseLeave={() => setTip(null)}>
        {[0, 0.25, 0.5, 0.75, 1].map(t => <g key={t}><line x1={x(t)} x2={x(t)} y1={T} y2={H - 24} className="grid" />
          <text x={x(t)} y={H - 8} textAnchor="middle" className="tick">{t * 100}%</text></g>)}
        {rows.map(([k, v], i) => {
          const y = T + i * (barH + gap);
          const sd = v.accuracy_std || 0;
          return (
            <g key={k}>
              <text x={L - 12} y={y + barH / 2 + 5} textAnchor="end" className="row-label">{modeName(k)}</text>
              <rect x={L} y={y} width={x(v.accuracy_mean) - L} height={barH} className={`bar ${k === best[0] ? "best" : ""}`} tabIndex={0}
                aria-label={`${modeName(k)}, ${(100 * v.accuracy_mean).toFixed(1)} percent correct`}
                onMouseEnter={() => show(k, v, y)} onFocus={() => show(k, v, y)} onBlur={() => setTip(null)} />
              {sd > 0 && (() => { const wy = y + barH + 5, a = x(Math.max(0, v.accuracy_mean - sd)), b = x(Math.min(1, v.accuracy_mean + sd));
                return <g className="whisker" aria-hidden="true"><line x1={a} x2={b} y1={wy} y2={wy} /><line x1={a} x2={a} y1={wy - 3} y2={wy + 3} /><line x1={b} x2={b} y1={wy - 3} y2={wy + 3} /></g>; })()}
              <text x={x(v.accuracy_mean) + 8} y={y + barH / 2 + 5} className="bar-value">{Math.round(100 * v.accuracy_mean)}%</text>
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

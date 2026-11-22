"use client";
import { useState } from "react";
import { ChartFrame, f2, type Tip } from "./ChartFrame";
import { systemName } from "@/lib/labels";

type Row = Record<string, number>;

/** Recall@1, @5 and @10 per retrieval method, in three small panels.
 *  Filled dot = scoped to the right company and year, hollow dot = all filings. */
export function DotPlot({ data }: { data: Record<string, Row> }) {
  const [tip, setTip] = useState<Tip>(null);
  const metrics = ["recall@1", "recall@5", "recall@10"];
  const methods = [...new Set(Object.keys(data).map(k => k.split("|")[0]))];
  const W = 760, L = 230, PW = (W - L - 20) / 3, top = 34, rowH = 34, H = top + methods.length * rowH + 30;
  const x = (panel: number, v: number) => L + panel * PW + 12 + v * (PW - 24);

  const base = data["bm25|scoped"]?.["recall@5"];
  const best = Object.entries(data).filter(([k]) => k.endsWith("|scoped")).sort((a, b) => b[1]["recall@5"] - a[1]["recall@5"])[0];
  const takeaway = base != null && best
    ? `${systemName(best[0]).method} finds the right page in the top 5 for ${Math.round(100 * best[1]["recall@5"])}% of questions, up from ${Math.round(100 * base)}% for plain BM25.`
    : "Recall at 1, 5 and 10 results for each retrieval method.";

  const show = (px: number, py: number, text: string) => setTip({ x: (px / W) * 100, y: (py / H) * 100, text });

  return (
    <ChartFrame takeaway={takeaway} note="Filled dots: search limited to the right company and year. Hollow dots: search across all 84 filings."
      tip={tip} head={["Method", "Scope", ...metrics.map(m => m.replace("recall", "Recall"))]}
      rows={Object.entries(data).map(([k, v]) => { const s = systemName(k); return [s.method, s.scope, ...metrics.map(m => f2(v[m]))]; })}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={takeaway} onMouseLeave={() => setTip(null)}>
        {metrics.map((m, p) => (
          <g key={m}>
            <text x={L + p * PW + PW / 2} y={18} textAnchor="middle" className="axis-title">{m.replace("recall", "Recall")}</text>
            {[0, 0.5, 1].map(t => (
              <g key={t}>
                <line x1={x(p, t)} x2={x(p, t)} y1={top - 6} y2={H - 26} className="grid" />
                <text x={x(p, t)} y={H - 10} textAnchor="middle" className="tick">{t}</text>
              </g>
            ))}
          </g>
        ))}
        {methods.map((meth, r) => {
          const y = top + r * rowH + rowH / 2;
          const sc = data[`${meth}|scoped`], op = data[`${meth}|open`];
          return (
            <g key={meth}>
              <text x={L - 12} y={y + 4} textAnchor="end" className="row-label">{systemName(meth).method}</text>
              {metrics.map((m, p) => (
                <g key={m}>
                  {sc && op && <line x1={x(p, op[m])} x2={x(p, sc[m])} y1={y} y2={y} className="connector" />}
                  {op && <circle cx={x(p, op[m])} cy={y} r={6} className="dot hollow" tabIndex={0}
                    aria-label={`${systemName(meth).method}, all filings, ${m} ${f2(op[m])}`}
                    onMouseEnter={() => show(x(p, op[m]), y, `${systemName(meth).method}, all filings: ${f2(op[m])}`)}
                    onFocus={() => show(x(p, op[m]), y, `${systemName(meth).method}, all filings: ${f2(op[m])}`)} onBlur={() => setTip(null)} />}
                  {sc && <circle cx={x(p, sc[m])} cy={y} r={6} className="dot filled" tabIndex={0}
                    aria-label={`${systemName(meth).method}, scoped, ${m} ${f2(sc[m])}`}
                    onMouseEnter={() => show(x(p, sc[m]), y, `${systemName(meth).method}, scoped: ${f2(sc[m])}`)}
                    onFocus={() => show(x(p, sc[m]), y, `${systemName(meth).method}, scoped: ${f2(sc[m])}`)} onBlur={() => setTip(null)} />}
                </g>
              ))}
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}

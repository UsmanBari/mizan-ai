"use client";
import { useState } from "react";
import { ChartFrame, f2, type Tip } from "./ChartFrame";
import { systemName } from "@/lib/labels";

type Row = Record<string, number>;

/** Recall@10 against median latency (log scale), each point labelled directly. */
export function Scatter({ data }: { data: Record<string, Row> }) {
  const [tip, setTip] = useState<Tip>(null);
  const pts = Object.entries(data).filter(([, v]) => v["latency_p50_ms"] > 0 && v["recall@10"] != null)
    .map(([k, v]) => ({ k, lat: v["latency_p50_ms"], r: v["recall@10"], s: systemName(k) }));
  if (!pts.length) return null;
  const W = 760, H = 380, L = 56, R = 210, T = 20, B = 46;
  const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...pts.map(p => p.lat))))),
        hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...pts.map(p => p.lat)))));
  const yMax = Math.min(1, Math.ceil(Math.max(...pts.map(p => p.r)) * 10) / 10 + 0.1);
  const x = (v: number) => L + (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * (W - L - R);
  const y = (v: number) => T + (1 - v / yMax) * (H - T - B);
  const ticks: number[] = []; for (let t = lo; t <= hi; t *= 10) ticks.push(t);
  const yt: number[] = []; for (let t = 0; t <= yMax + 1e-9; t += 0.2) yt.push(+t.toFixed(1));

  // points with identical scores and near-identical speed share one label
  const groups: { x: number; y: number; items: typeof pts }[] = [];
  pts.forEach(p => {
    const g = groups.find(g => Math.abs(g.x - x(p.lat)) < 14 && Math.abs(g.y - y(p.r)) < 10);
    g ? g.items.push(p) : groups.push({ x: x(p.lat), y: y(p.r), items: [p] });
  });
  // nudge labels apart vertically so they never overlap
  const labels = groups.map(g => ({ ...g, ly: g.y })).sort((a, b) => a.ly - b.ly);
  for (let i = 1; i < labels.length; i++) if (labels[i].ly - labels[i - 1].ly < 15) labels[i].ly = labels[i - 1].ly + 15;

  const best = [...pts].sort((a, b) => b.r - a.r || a.lat - b.lat)[0];
  const takeaway = `${best.s.method} (${best.s.scoped ? "scoped" : "all filings"}) has the best recall@10, ${f2(best.r)}, at a median ${best.lat.toFixed(1)} ms.`;
  const show = (p: typeof pts[number]) => setTip({ x: (x(p.lat) / W) * 100, y: (y(p.r) / H) * 100,
    text: `${p.s.method}, ${p.s.scoped ? "scoped" : "all filings"}: recall@10 ${f2(p.r)}, ${p.lat.toFixed(1)} ms` });

  return (
    <ChartFrame takeaway={takeaway} note="Further right is slower (log scale), higher is better. Filled: scoped, hollow: all filings."
      tip={tip} head={["Method", "Scope", "Recall@10", "Median latency (ms)"]}
      rows={pts.map(p => [p.s.method, p.s.scope, f2(p.r), p.lat.toFixed(1)])}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={takeaway} onMouseLeave={() => setTip(null)}>
        {yt.map(t => <g key={t}><line x1={L} x2={W - R} y1={y(t)} y2={y(t)} className="grid" />
          <text x={L - 8} y={y(t) + 4} textAnchor="end" className="tick">{t}</text></g>)}
        {ticks.map(t => <g key={t}><line x1={x(t)} x2={x(t)} y1={T} y2={H - B} className="grid" />
          <text x={x(t)} y={H - B + 18} textAnchor="middle" className="tick">{t >= 1 ? t : t.toFixed(1)}</text></g>)}
        <text x={(L + W - R) / 2} y={H - 6} textAnchor="middle" className="axis-title">Median latency (ms, log scale)</text>
        <text x={14} y={(T + H - B) / 2} textAnchor="middle" className="axis-title" transform={`rotate(-90 14 ${(T + H - B) / 2})`}>Recall@10</text>
        {pts.map(p => (
          <circle key={p.k} cx={x(p.lat)} cy={y(p.r)} r={6} className={`dot ${p.s.scoped ? "filled" : "hollow"}`} tabIndex={0}
            aria-label={`${p.s.method}, ${p.s.scoped ? "scoped" : "all filings"}, recall@10 ${f2(p.r)}, ${p.lat.toFixed(1)} milliseconds`}
            onMouseEnter={() => show(p)} onFocus={() => show(p)} onBlur={() => setTip(null)} />
        ))}
        {labels.map((g, i) => (
          <g key={i}>
            <line x1={g.x + 8} x2={W - R + 8} y1={g.y} y2={g.ly} className="leader" />
            <text x={W - R + 12} y={g.ly + 4} className="point-label">
              {g.items.map(p => p.s.method.replace("BM25 + ", "+ ")).join(" = ")}{g.items[0].s.scoped ? ", scoped" : ", all"}
            </text>
          </g>
        ))}
      </svg>
    </ChartFrame>
  );
}

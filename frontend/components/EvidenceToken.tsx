"use client";
import type { Evidence } from "@/lib/api";

const SAYS = {
  found: "printed in the report",
  computed: "computed by code",
  unverified: "not found in the cited pages",
} as const;

/** One number in an answer, carrying where it came from.
 *  Colour plus a second, non-colour signal: solid underline (printed),
 *  dotted underline and ƒ (computed), dashed underline and ? (not found). */
export function EvidenceToken({ text, ev, active, onOpen }: {
  text: string; ev: Evidence; active: boolean; onOpen: (e: Evidence) => void;
}) {
  return (
    <button type="button" className={`ev ev-${ev.status}`} aria-pressed={active}
      aria-label={`${text}, ${SAYS[ev.status]}. Show source.`} title={`${text}: ${SAYS[ev.status]}`}
      onClick={() => onOpen(ev)}>
      {text}
      {ev.status === "computed" && <span className="ev-mark" aria-hidden="true">ƒ</span>}
      {ev.status === "unverified" && <span className="ev-mark" aria-hidden="true">?</span>}
    </button>
  );
}

export function ProvenanceLegend() {
  return (
    <ul className="legend" aria-label="What the number styles mean">
      <li><span className="ev ev-found ev-sample">123</span> printed in the report</li>
      <li><span className="ev ev-computed ev-sample">12<span className="ev-mark">ƒ</span></span> computed by code</li>
      <li><span className="ev ev-unverified ev-sample">1<span className="ev-mark">?</span></span> not found, check it</li>
    </ul>
  );
}

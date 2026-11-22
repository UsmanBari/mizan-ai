"use client";
import { useEffect } from "react";

/** Raw page text with one number highlighted and scrolled into view. */
export function PageText({ text, highlight }: { text: string; highlight?: string }) {
  const parts = highlight ? text.split(highlight) : [text];
  useEffect(() => {
    document.getElementById("hl-0")?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [text, highlight]);
  return (
    <pre className="page">
      {parts.map((p, i) => (
        <span key={i}>{p}{i < parts.length - 1 && <mark id={`hl-${i}`}>{highlight}</mark>}</span>
      ))}
    </pre>
  );
}

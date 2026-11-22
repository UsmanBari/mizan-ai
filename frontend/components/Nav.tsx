"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Ask" },
  { href: "/documents", label: "Reports" },
  { href: "/watchlist", label: "Watchlist" },
  { href: "/eval", label: "Evaluation" },
];

type Health = { status: string; store: string; llm: string | null; documents: number };

export function Nav() {
  const path = usePathname();
  const [h, setH] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    const check = () => api<Health>("/health").then(x => { setH(x); setDown(false); }).catch(() => setDown(true));
    check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, [path]);

  return (
    <header className="top">
      <Link href="/" className="brand" aria-label="Mizan AI home">
        <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
          <path d="M16 5v20M7 10h18M10 27h12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
          <path d="M7 10l-4 8h8zM25 10l-4 8h8z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" fill="none" />
          <circle cx="16" cy="5" r="1.8" fill="currentColor" />
        </svg>
        <span>Mizan</span>
      </Link>
      <nav aria-label="Main">
        {LINKS.map(l => (
          <Link key={l.href} href={l.href} aria-current={path === l.href ? "page" : undefined}>{l.label}</Link>
        ))}
      </nav>
      <Link href="/documents" className={`status-chip ${down ? "is-down" : ""}`} role="status"
        title={down ? "The backend at localhost:8000 is not responding" : "Open the report library"}>
        <span className="status-dot" aria-hidden="true" />
        {down ? "Server offline" : h ? `${h.documents} ${h.documents === 1 ? "report" : "reports"}` : "Connecting…"}
      </Link>
    </header>
  );
}

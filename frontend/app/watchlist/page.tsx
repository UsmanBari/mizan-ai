"use client";
import { useEffect, useState } from "react";
import { api, postJSON } from "@/lib/api";

type W = { symbol: string; chat_id: string; email: string };
type A = { symbol: string; doc_id: string; title: string; summary: string; created_at: string; channels: string[] };

export default function Watchlist() {
  const [list, setList] = useState<W[]>([]);
  const [alerts, setAlerts] = useState<A[]>([]);
  const [form, setForm] = useState({ symbol: "", telegram_chat_id: "", email: "" });
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    api<W[]>("/watchlist").then(setList).catch(e => setMsg({ text: e.message, bad: true }));
    api<A[]>("/alerts").then(setAlerts).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  async function watch(e: React.FormEvent) {
    e.preventDefault();
    if (!form.symbol) { setMsg({ text: "Type a PSX symbol to watch, for example LUCK.", bad: true }); return; }
    if (!form.email && !form.telegram_chat_id) { setMsg({ text: "Add an email address so Mizan can send the alert.", bad: true }); return; }
    try {
      setList(await postJSON<W[]>("/watchlist", form));
      setMsg({ text: `Watching ${form.symbol}. You will get an alert when it posts new results.` });
      setForm({ ...form, symbol: "" });
    } catch (er: any) { setMsg({ text: er.message, bad: true }); }
  }

  async function checkNow() {
    setBusy(true); setMsg(null);
    try {
      const r = await postJSON<A[]>("/alerts/run", {});
      setMsg({ text: r.length ? `${r.length} new ${r.length > 1 ? "alerts" : "alert"} sent.` : "No new results since the last check." });
      load();
    } catch (er: any) { setMsg({ text: er.message, bad: true }); }
    setBusy(false);
  }

  return (
    <>
      <h1>Watchlist</h1>
      <p className="lede">When a company you watch posts new results on PSX, Mizan reads them, works out the changes in code and sends you a short summary. It checks every 30 minutes.</p>

      <section className="panel">
        <form className="watch-form" onSubmit={watch}>
          <label className="field">PSX symbol
            <input value={form.symbol} placeholder="e.g. LUCK" maxLength={10}
              onChange={e => setForm({ ...form, symbol: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "") })} />
          </label>
          <label className="field">Email for alerts
            <input type="email" value={form.email} placeholder="you@example.com" onChange={e => setForm({ ...form, email: e.target.value })} />
          </label>
          <details className="extra full">
            <summary>Add Telegram (optional)</summary>
            <label className="field">Telegram chat ID
              <input value={form.telegram_chat_id} placeholder="e.g. 123456789" onChange={e => setForm({ ...form, telegram_chat_id: e.target.value })} />
            </label>
          </details>
          <div className="full row">
            <button type="submit" className="primary">Watch</button>
            <button type="button" className="secondary" onClick={checkNow} disabled={busy}>
              {busy ? <><span className="spinner" aria-hidden="true" />Checking PSX…</> : "Check now"}
            </button>
          </div>
        </form>
        {msg && <p className={msg.bad ? "err" : "notice"} role="status">{msg.text}</p>}
      </section>

      <section className="block">
        <h2>Watching</h2>
        {list.length === 0 ? <p className="muted">Nothing yet. Add a company above.</p> : (
          <table>
            <thead><tr><th>Company</th><th>Email</th><th>Telegram</th></tr></thead>
            <tbody>{list.map(w => <tr key={w.symbol}><td><strong>{w.symbol}</strong></td><td>{w.email || "—"}</td><td>{w.chat_id || "—"}</td></tr>)}</tbody>
          </table>
        )}
      </section>

      <section className="block">
        <h2>Alerts sent</h2>
        {alerts.length === 0 && <p className="muted">No alerts yet. Watch a company, then press "Check now" to test.</p>}
        <ul className="alerts">
          {alerts.map((a, i) => (
            <li key={i}>
              <div className="alert-head"><strong>{a.title}</strong>
                <span className="muted">{new Date(a.created_at).toLocaleString()}, sent by {a.channels.join(" and ") || "the app only"}</span></div>
              <p>{a.summary}</p>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

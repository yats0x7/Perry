import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Desktop, Health } from "../lib/types";
import { Cross } from "./icons";

function ago(ts?: number | null): string {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

type Tab = "devices" | "activity" | "about";

export function Sheet({ open, onClose, desktops, health, voiceOn, setVoiceOn, onRevoke, onSignOut, onPairAnother, currentId, onChoose }: {
  open: boolean;
  currentId: string | null;
  onChoose: (id: string) => void;
  onClose: () => void;
  desktops: Desktop[];
  health: Health | null;
  voiceOn: boolean;
  setVoiceOn: (v: boolean) => void;
  onRevoke: (id: string) => void;
  onSignOut: () => void;
  onPairAnother: () => void;
}) {
  const [tab, setTab] = useState<Tab>("devices");
  const [events, setEvents] = useState<any[] | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  useEffect(() => {
    if (open && tab === "activity") {
      setEvents(null);
      api<{ events: any[] }>("/api/audit?limit=80").then((r) => setEvents(r.events)).catch(() => setEvents([]));
    }
  }, [open, tab]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div className="cut-in fixed inset-0 z-40 bg-[#040b1c]/70" onClick={onClose} />
      <section
        role="dialog"
        aria-modal="true"
        aria-label="Devices, activity and settings"
        className="sheet-in fixed inset-x-0 bottom-0 z-50 mx-auto flex max-h-[88dvh] max-w-xl flex-col border-t-2 border-ivory bg-studio-deep safe-bottom"
      >
        <div className="flex items-end justify-between px-5 pt-3">
          <div role="tablist" className="flex gap-5">
            {(["devices", "activity", "about"] as const).map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`border-b-2 pb-2 pt-1 text-[15px] font-semibold capitalize ${tab === t ? "border-ivory text-ivory" : "border-transparent text-haze"}`}
              >
                {t}
              </button>
            ))}
          </div>
          <button onClick={onClose} aria-label="Close" className="mb-1 grid h-9 w-9 place-items-center text-mist"><Cross /></button>
        </div>
        <div className="border-t border-rule" />

        <div className="thin-scroll flex-1 overflow-y-auto px-5 pb-6">
          {tab === "devices" && (
            <div className="pt-1">
              <ul>
                {desktops.map((d) => {
                  const twins = desktops.filter((x) => x.name === d.name).length > 1;
                  return (
                    <li key={d.id} className="border-b border-rule py-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="flex items-center gap-2 text-[19px] font-semibold">
                            <span className={`h-2 w-2 shrink-0 ${d.online ? "bg-onair" : "bg-haze"}`} aria-hidden />
                            <span className="truncate">{d.name}</span>
                          </p>
                          <p className="mt-0.5 text-[15px] text-mist">
                            {d.online ? "On air" : `Offline · ${ago(d.last_seen_at)}`}
                            {" · "}{d.platform === "macos" ? "macOS" : d.platform}{d.platform_version ? ` ${d.platform_version}` : ""}
                            {d.platform_supported === false && " · not supported yet"}
                          </p>
                          <p className="mt-0.5 text-[15px] text-haze">
                            {d.tools.length} tools · {d.projects.length} project{d.projects.length === 1 ? "" : "s"}
                            {twins && d.paired_at ? ` · paired ${new Date(d.paired_at * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
                          </p>
                          {d.projects.length > 0 && (
                            <p className="mt-1.5 text-[15px]">{d.projects.map((p) => p.name).join(" · ")}</p>
                          )}
                        </div>
                        {d.id === currentId && <span className="slug shrink-0 bg-ivory px-2 py-1 text-ink">In use</span>}
                      </div>
                      <div className="mt-3 flex items-center justify-between">
                        {d.id !== currentId ? (
                          <button onClick={() => onChoose(d.id)} className="border border-rule-strong px-3 py-2 text-[15px] font-semibold">
                            Use this Mac
                          </button>
                        ) : <span />}
                        {confirm === d.id ? (
                          <span className="flex items-center gap-3 text-[15px]">
                            <span className="text-mist">Remove its access?</span>
                            <button onClick={() => setConfirm(null)} className="px-2 py-2 text-mist">Keep</button>
                            <button onClick={() => { onRevoke(d.id); setConfirm(null); }} className="bg-fault px-3 py-2 font-semibold text-ink">Revoke</button>
                          </span>
                        ) : (
                          <button onClick={() => setConfirm(d.id)} className="px-2 py-2 text-[15px] text-fault">Revoke</button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <button onClick={onPairAnother} className="mt-4 w-full border border-dashed border-rule-strong py-3.5 text-[15px] font-semibold text-mist">
                Pair another Mac
              </button>
              <button onClick={onSignOut} className="mt-6 w-full py-2 text-[15px] text-fault">Sign out this phone</button>
            </div>
          )}

          {tab === "activity" && (
            <div className="pt-2">
              {events === null && <p className="py-8 text-[15px] text-mist">Loading activity…</p>}
              {events?.length === 0 && <p className="py-8 text-[15px] text-mist">Nothing has run yet.</p>}
              <ol>
                {events?.map((e, i) => (
                  <li key={i} className="grid grid-cols-[52px_1fr] gap-3 border-b border-rule py-2.5 text-[15px]">
                    <span className="text-haze">{new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    <span className="min-w-0">
                      <span className={e.detail?.ok === false || e.event.includes("blocked") ? "text-fault" : ""}>{e.event}</span>
                      {e.detail?.tool && <span className="ml-1.5 font-mono text-[14px] text-mist">{e.detail.tool}</span>}
                      {e.detail?.error && <span className="block truncate text-fault/80">{e.detail.error}</span>}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {tab === "about" && (
            <div className="pt-2">
              <label className="flex items-center justify-between border-b border-rule py-4">
                <span className="text-[15px]">Speak replies</span>
                <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} className="h-5 w-5" />
              </label>
              <dl className="text-[15px]">
                {[
                  ["Speech recognition", health?.gnani_configured ? `Gnani Prisma ${health.stt_model.replace("prisma-", "v")}` : "Not configured on the server"],
                  ["Spoken replies", health?.gnani_configured ? `Gnani Timbre ${health.tts_model.replace("timbre-", "v")}` : "Not configured on the server"],
                  ["Understanding", health?.planner?.replace("openai-compat:", "") ?? "—"],
                  ["Asks before", health?.approval_mode === "strict" ? "every action" : "processes, file writes, power and terminal"],
                ].map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[140px_1fr] gap-3 border-b border-rule py-3">
                    <dt className="text-haze">{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-5 text-[15px] leading-snug text-haze">Perry · One assistant. Any phone. Any computer.</p>
            </div>
          )}
        </div>
      </section>
    </>
  );
}

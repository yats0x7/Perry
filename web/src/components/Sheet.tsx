import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Desktop, Health } from "../lib/types";
import { Cross, Laptop } from "./icons";

function ago(ts?: number | null): string {
  if (!ts) return "never";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

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
  const [tab, setTab] = useState<"devices" | "activity">("devices");
  const [events, setEvents] = useState<any[] | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);

  useEffect(() => {
    if (open && tab === "activity") {
      setEvents(null);
      api<{ events: any[] }>("/api/audit?limit=80").then((r) => setEvents(r.events)).catch(() => setEvents([]));
    }
  }, [open, tab]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/55" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <motion.section
            role="dialog" aria-label="Devices and settings"
            className="fixed inset-x-0 bottom-0 z-50 mx-auto max-h-[86dvh] max-w-xl overflow-hidden rounded-t-3xl border border-line bg-panel safe-bottom"
            initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", damping: 32, stiffness: 340 }}
          >
            <div className="flex items-center justify-between px-5 pb-2 pt-4">
              <div className="flex gap-1 rounded-full bg-ink/60 p-1 text-[13px]">
                {(["devices", "activity"] as const).map((t) => (
                  <button key={t} onClick={() => setTab(t)}
                    className={`rounded-full px-3.5 py-1.5 capitalize ${tab === t ? "bg-raised text-fg" : "text-dim"}`}>{t}</button>
                ))}
              </div>
              <button onClick={onClose} aria-label="Close" className="flex h-8 w-8 items-center justify-center rounded-full text-dim"><Cross /></button>
            </div>

            <div className="no-scrollbar max-h-[72dvh] overflow-y-auto px-5 pb-6">
              {tab === "devices" ? (
                <div className="space-y-6 pt-2">
                  <div className="space-y-2.5">
                    {desktops.map((d) => (
                      <div key={d.id} className="rounded-2xl border border-line bg-raised/60 p-4">
                        <div className="flex items-start gap-3">
                          <Laptop className="mt-0.5 text-dim" />
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="truncate text-[15px] font-medium">{d.name}</span>
                              <span className={`h-1.5 w-1.5 rounded-full ${d.online ? "bg-ok" : "bg-mute"}`} />
                              <span className="text-[12px] text-dim">{d.online ? "Online" : `Offline · ${ago(d.last_seen_at)}`}</span>
                              {d.id === currentId && <span className="rounded-full bg-ember/15 px-2 py-0.5 text-[11px] font-medium text-ember">In use</span>}
                            </div>
                            <div className="mt-1 text-[12.5px] text-dim">
                              {d.platform === "macos" ? "macOS" : d.platform}{d.platform_version ? ` ${d.platform_version}` : ""}
                              {d.platform_supported === false && " · automation not implemented on this OS yet"}
                              {" · "}{d.tools.length} tools · {d.projects.length} project{d.projects.length === 1 ? "" : "s"}
                              {desktops.filter((x) => x.name === d.name).length > 1 && d.paired_at
                                ? ` · paired ${new Date(d.paired_at * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`
                                : ""}
                            </div>
                            {d.projects.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1.5">
                                {d.projects.map((p) => <span key={p.id} className="rounded-md bg-ink/70 px-2 py-0.5 font-mono text-[11px] text-dim">{p.name}</span>)}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="mt-3 flex items-center justify-between">
                          {d.id !== currentId ? (
                            <button onClick={() => onChoose(d.id)} className="rounded-lg border border-line-strong px-3 py-1.5 text-[13px] text-fg">
                              Use this computer
                            </button>
                          ) : <span />}
                          {confirm === d.id ? (
                            <div className="flex items-center gap-2 text-[13px]">
                              <span className="text-dim">Remove access?</span>
                              <button onClick={() => setConfirm(null)} className="rounded-lg px-3 py-1.5 text-dim">Keep</button>
                              <button onClick={() => { onRevoke(d.id); setConfirm(null); }} className="rounded-lg bg-bad/15 px-3 py-1.5 font-medium text-bad">Revoke</button>
                            </div>
                          ) : (
                            <button onClick={() => setConfirm(d.id)} className="rounded-lg px-3 py-1.5 text-[13px] text-bad/90">Revoke device</button>
                          )}
                        </div>
                      </div>
                    ))}
                    <button onClick={onPairAnother} className="w-full rounded-2xl border border-dashed border-line-strong py-3 text-[14px] text-dim">
                      + Pair another computer
                    </button>
                  </div>

                  <div className="divide-y divide-line rounded-2xl border border-line">
                    <label className="flex items-center justify-between px-4 py-3.5">
                      <span className="text-[14.5px]">Speak replies</span>
                      <input type="checkbox" checked={voiceOn} onChange={(e) => setVoiceOn(e.target.checked)} className="h-5 w-5 accent-[#f2b46d]" />
                    </label>
                    <Row k="Speech-to-text" v={health?.gnani_configured ? `Gnani Prisma ${health.stt_model.replace("prisma-", "v")}` : "Not configured on server"} />
                    <Row k="Text-to-speech" v={health?.gnani_configured ? `Gnani Timbre ${health.tts_model.replace("timbre-", "v")}` : "Not configured on server"} />
                    <Row k="Planner" v={health?.planner ?? "—"} />
                    <Row k="Approvals" v={health?.approval_mode === "strict" ? "Every action" : "Processes & file writes"} />
                  </div>

                  <button onClick={onSignOut} className="w-full rounded-2xl border border-line py-3 text-[14px] text-bad">Sign out this phone</button>
                </div>
              ) : (
                <div className="pt-2">
                  {events === null && <p className="py-8 text-center text-[13px] text-dim">Loading…</p>}
                  {events?.length === 0 && <p className="py-8 text-center text-[13px] text-dim">No activity yet.</p>}
                  <ol className="space-y-1">
                    {events?.map((e, i) => (
                      <li key={i} className="flex gap-3 border-b border-line py-2 text-[12.5px]">
                        <span className="w-14 shrink-0 font-mono text-mute">{new Date(e.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                        <span className="min-w-0 flex-1">
                          <span className={e.detail?.ok === false || e.event.includes("blocked") ? "text-bad" : "text-fg"}>{e.event}</span>
                          {e.detail?.tool && <span className="ml-1.5 font-mono text-dim">{e.detail.tool}</span>}
                          {e.detail?.error && <span className="block truncate text-bad/80">{e.detail.error}</span>}
                        </span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          </motion.section>
        </>
      )}
    </AnimatePresence>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between px-4 py-3.5 text-[14.5px]">
      <span>{k}</span><span className="text-[13.5px] text-dim">{v}</span>
    </div>
  );
}

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pair } from "./components/Pair";
import { Sheet } from "./components/Sheet";
import { TaskCard } from "./components/TaskCard";
import { Cross, Menu, Send, Speaker, SpeakerOff, Spinner } from "./components/icons";
import { api, store } from "./lib/api";
import { player } from "./lib/player";
import { MAX_SECONDS, WavRecorder } from "./lib/recorder";
import { ClientSocket, type LinkState } from "./lib/socket";
import { TERMINAL, type Desktop, type Health, type Task } from "./lib/types";

const LANGS = [
  { code: "en-IN", label: "Hinglish", hint: "Hindi + English, Latin script" },
  { code: "hi-IN", label: "हिंदी", hint: "Hindi, Devanagari" },
  { code: "en-IN", label: "English", hint: "Indian English" },
  { code: "mr-IN", label: "मराठी", hint: "Marathi" },
  { code: "ta-IN", label: "தமிழ்", hint: "Tamil" },
  { code: "te-IN", label: "తెలుగు", hint: "Telugu" },
  { code: "kn-IN", label: "ಕನ್ನಡ", hint: "Kannada" },
  { code: "bn-IN", label: "বাংলা", hint: "Bengali" },
  { code: "gu-IN", label: "ગુજરાતી", hint: "Gujarati" },
  { code: "ml-IN", label: "മലയാളം", hint: "Malayalam" },
  { code: "pa-IN", label: "ਪੰਜਾਬੀ", hint: "Punjabi" },
];

type Voice = "idle" | "listening" | "transcribing";

export default function App() {
  const params = new URLSearchParams(location.search);
  const [token, setToken] = useState<string | null>(store.token);
  const [pairing, setPairing] = useState<boolean>(!store.token || !!params.get("code"));

  if (!token || pairing) {
    return (
      <Pair
        initialCode={params.get("code") ?? undefined}
        onPaired={(t) => { history.replaceState(null, "", "/"); setToken(t); setPairing(false); }}
        onCancel={token ? () => { history.replaceState(null, "", "/"); setPairing(false); } : undefined}
      />
    );
  }
  return <Console key={token} token={token} onSignedOut={() => { store.token = null; setToken(null); }}
    onPairAnother={() => setPairing(true)} />;
}

function Console({ token, onSignedOut, onPairAnother }: { token: string; onSignedOut: () => void; onPairAnother: () => void }) {
  const [link, setLink] = useState<LinkState>("connecting");
  const [desktops, setDesktops] = useState<Desktop[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [selected, setSelected] = useState<string | null>(store.pref("desktop", "") || null);
  const [voice, setVoice] = useState<Voice>("idle");
  const [level, setLevel] = useState(0);
  const [secs, setSecs] = useState(0);
  const [text, setText] = useState("");
  const [notice, setNotice] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const [langIdx, setLangIdx] = useState(() => Number(store.pref("lang", "0")) || 0);
  const [langOpen, setLangOpen] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [voiceOn, setVoiceOnState] = useState(store.pref("voice", "1") === "1");
  const [speakingUrl, setSpeakingUrl] = useState<string | null>(null);
  const sock = useRef<ClientSocket | null>(null);
  const rec = useRef<WavRecorder | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const spoken = useRef<Set<string>>(new Set());
  const voiceOnRef = useRef(voiceOn);
  voiceOnRef.current = voiceOn;

  // The chosen computer if it still exists; otherwise the most recently connected online one.
  const desktop = desktops.find((d) => d.id === selected)
    ?? [...desktops].filter((d) => d.online).sort((a, b) => (b.connected_at ?? 0) - (a.connected_at ?? 0))[0]
    ?? desktops[0];
  const chooseDesktop = (id: string) => { setSelected(id); store.setPref("desktop", id); };
  const lang = LANGS[langIdx] ?? LANGS[0];

  // ---- socket --------------------------------------------------------------------------
  useEffect(() => {
    const s = new ClientSocket(token);
    sock.current = s;
    s.onState((st) => {
      setLink(st);
      if (st === "unauthorized") { setNotice({ kind: "error", text: "This phone was signed out or revoked." }); setTimeout(onSignedOut, 1500); }
    });
    s.on((m) => {
      if (m.type === "ready") {
        setDesktops(m.desktops);
        setHealth(m.health);
        const sorted = [...m.tasks].reverse() as Task[];
        sorted.forEach((t) => spoken.current.add(t.id)); // never auto-play history
        setTasks(sorted);
      } else if (m.type === "desktop") {
        setDesktops((ds) => {
          const i = ds.findIndex((d) => d.id === m.desktop.id);
          return i < 0 ? [...ds, m.desktop] : ds.map((d) => (d.id === m.desktop.id ? m.desktop : d));
        });
      } else if (m.type === "task") {
        const t: Task = m.task;
        setTasks((ts) => {
          const i = ts.findIndex((x) => x.id === t.id);
          return i < 0 ? [...ts, t] : ts.map((x) => (x.id === t.id ? t : x));
        });
        if (TERMINAL.includes(t.status) && t.speech?.status === "ready" && !spoken.current.has(t.id)) {
          spoken.current.add(t.id);
          if (voiceOnRef.current) speak(t.speech.url!);
        }
      } else if (m.type === "error") {
        setNotice({ kind: "error", text: m.message });
      }
    });
    s.start();
    return () => s.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    const off = player.subscribe(() => setSpeakingUrl(player.playing ? player.currentUrl : null));
    return () => { off(); };
  }, []);
  useEffect(() => { if (notice) { const t = setTimeout(() => setNotice(null), 6000); return () => clearTimeout(t); } }, [notice]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [tasks.length, tasks[tasks.length - 1]?.status, tasks[tasks.length - 1]?.plan?.steps.length]);

  const speak = useCallback((url: string) => {
    if (player.playing && player.currentUrl === url) { player.stop(); return; }
    player.play(url).catch(() => setNotice({ kind: "info", text: "Tap ▶ on the reply to hear it (the browser blocked autoplay)." }));
  }, []);

  // ---- commands ------------------------------------------------------------------------
  const send = useCallback((cmd: string, transcript?: Record<string, unknown>) => {
    if (!desktop) { setNotice({ kind: "error", text: "No computer paired." }); return; }
    if (!desktop.online) { setNotice({ kind: "error", text: `${desktop.name} is offline. Start \`perry-agent run\` on it.` }); return; }
    if (!sock.current?.send({ type: "command", desktop_id: desktop.id, text: cmd, transcript })) {
      setNotice({ kind: "error", text: "Not connected to the Perry server. Reconnecting…" });
    }
  }, [desktop]);

  const submitText = () => {
    player.unlock();
    const v = text.trim();
    if (!v) return;
    setText("");
    send(v);
  };

  const startListening = async () => {
    player.unlock();
    player.stop();
    if (!WavRecorder.supported()) { setNotice({ kind: "error", text: "This browser can't record audio. Type your command instead." }); return; }
    if (!window.isSecureContext) { setNotice({ kind: "error", text: "Microphone needs HTTPS. Open Perry over https://" }); return; }
    const r = new WavRecorder();
    r.onLevel = setLevel;
    r.onAutoStop = () => stopListening();
    rec.current = r;
    try {
      await r.start();
      setVoice("listening");
      setSecs(0);
    } catch (e: any) {
      setNotice({ kind: "error", text: e?.name === "NotAllowedError" ? "Microphone permission was denied." : `Microphone error: ${e?.message ?? e}` });
    }
  };

  const stopListening = async () => {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    const dur = r.seconds;
    const wav = await r.stop();
    if (dur < 0.6) { setVoice("idle"); setNotice({ kind: "info", text: "Tap the orb, speak, then tap again to send." }); return; }
    setVoice("transcribing");
    try {
      const fd = new FormData();
      fd.append("audio", wav, "command.wav");
      fd.append("language", lang.code);
      if (desktop) fd.append("desktop_id", desktop.id);
      const r2 = await api<{ text: string; model: string; language: string; request_id: string; latency_ms: number }>("/api/stt", { method: "POST", body: fd });
      if (!r2.text) { setNotice({ kind: "info", text: "Prisma didn't hear any speech. Try again a bit closer to the mic." }); return; }
      send(r2.text, { model: r2.model, language: r2.language, request_id: r2.request_id, latency_ms: r2.latency_ms });
    } catch (e: any) {
      setNotice({ kind: "error", text: `Speech recognition failed: ${e.message}` });
    } finally {
      setVoice("idle");
    }
  };

  const cancelListening = () => { rec.current?.cancel(); rec.current = null; setVoice("idle"); };

  useEffect(() => {
    if (voice !== "listening") return;
    const t = setInterval(() => setSecs(rec.current?.seconds ?? 0), 200);
    return () => clearInterval(t);
  }, [voice]);

  const onOrb = () => (voice === "listening" ? stopListening() : voice === "idle" ? startListening() : undefined);

  // ---- derived state -----------------------------------------------------------------------
  const active = [...tasks].reverse().find((t) => !TERMINAL.includes(t.status));
  const last = tasks[tasks.length - 1];
  const offline = link !== "open" || !desktop?.online;
  const state = useMemo(() => {
    if (link !== "open") return { key: "disconnected", label: link === "connecting" ? "Connecting to Perry…" : "Reconnecting…" };
    if (!desktop) return { key: "disconnected", label: "No computer paired" };
    if (!desktop.online) return { key: "disconnected", label: `${desktop.name} is offline` };
    if (voice === "listening") return { key: "listening", label: `Listening · ${secs.toFixed(0)}s / ${MAX_SECONDS}s — tap to send` };
    if (voice === "transcribing") return { key: "transcribing", label: "Transcribing with Gnani Prisma" };
    if (active) {
      const m: Record<string, string> = {
        thinking: "Thinking", planning: "Planning", awaiting_approval: "Waiting for your approval",
        executing: `Running on ${desktop.name}`, responding: "Writing reply",
      };
      return { key: active.status, label: m[active.status] ?? "Working" };
    }
    if (speakingUrl) return { key: "speaking", label: "Speaking · Gnani Timbre" };
    if (last && Date.now() / 1000 - last.updated_at < 8) {
      if (last.status === "completed") return { key: "completed", label: "Done" };
      if (last.status === "failed") return { key: "error", label: "Something went wrong" };
    }
    return { key: "idle", label: "Tap the orb and speak" };
  }, [link, desktop, voice, secs, active, speakingUrl, last]);

  const orbState = offline ? "offline" : voice === "listening" ? "listening"
    : (voice === "transcribing" || (active && active.status !== "awaiting_approval") || speakingUrl) ? "busy" : "idle";

  const examples = useMemo(() => {
    const p = desktop?.projects[0]?.name;
    return [
      p ? `${p} project kholo, git status check karo aur dev server start karo` : "Chrome kholo",
      p ? `${p} mein koi errors aa rahe hain kya?` : "YouTube kholo",
      "Brave mein YouTube pe Kesariya bajao",
      "Spotify pe gaana resume karo",
    ];
  }, [desktop]);

  const setVoiceOn = (v: boolean) => { setVoiceOnState(v); store.setPref("voice", v ? "1" : "0"); if (!v) player.stop(); };

  return (
    <div className="app-bg flex h-[100dvh] flex-col">
      {/* header */}
      <header className="safe-top z-20 flex items-center justify-between px-5 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="orb relative h-[18px] w-[18px]" data-state={orbState === "offline" ? "offline" : "idle"} />
          <span className="text-[17px] font-semibold tracking-[-0.01em]">Perry</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={() => setVoiceOn(!voiceOn)} aria-label={voiceOn ? "Mute voice replies" : "Unmute voice replies"}
            className="flex h-9 w-9 items-center justify-center rounded-full text-dim">
            {voiceOn ? <Speaker /> : <SpeakerOff />}
          </button>
          <button onClick={() => setSheet(true)}
            className="flex items-center gap-2 rounded-full border border-line bg-panel/70 py-1.5 pl-3 pr-2.5 text-[13px]">
            <span className={`h-2 w-2 rounded-full ${desktop?.online && link === "open" ? "bg-ok shadow-[0_0_8px_rgb(111_211_154/0.6)]" : "bg-mute"}`} />
            <span className="max-w-[9.5rem] truncate">{desktop?.name ?? "No computer"}</span>
            <Menu width={15} height={15} className="text-dim" />
          </button>
        </div>
      </header>

      {/* timeline */}
      <main ref={scroller} className="scroll-fade no-scrollbar flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-xl space-y-6 px-4 pb-6 pt-2">
          {tasks.length === 0 ? (
            <div className="flex min-h-[52dvh] flex-col justify-end pb-4">
              <h2 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">Namaste.<br /><span className="text-dim">Kya karna hai?</span></h2>
              <p className="mt-3 max-w-sm text-[14.5px] leading-relaxed text-dim">
                Speak in Hinglish, Hindi or English. Perry plans the steps, asks before running anything consequential, and
                does it on {desktop?.name ?? "your computer"}.
              </p>
              <div className="mt-6 flex flex-col items-start gap-2">
                {examples.map((e) => (
                  <button key={e} onClick={() => setText(e)}
                    className="rounded-full border border-line bg-panel/70 px-3.5 py-2 text-left text-[13.5px] text-fg/85 active:bg-raised">
                    “{e}”
                  </button>
                ))}
              </div>
            </div>
          ) : (
            tasks.map((t) => (
              <TaskCard key={t.id} task={t} desktop={desktops.find((d) => d.id === t.desktop_id)}
                speakingUrl={speakingUrl}
                onSpeak={(u) => { player.unlock(); speak(u); }}
                onApprove={() => { player.unlock(); sock.current?.send({ type: "approve", task_id: t.id, digest: t.plan_digest }); }}
                onReject={() => sock.current?.send({ type: "reject", task_id: t.id })}
                onCancel={() => sock.current?.send({ type: "cancel", task_id: t.id })} />
            ))
          )}
        </div>
      </main>

      {/* dock */}
      <footer className="glass safe-bottom z-20 border-t border-line">
        <div className="mx-auto w-full max-w-xl px-4 pt-3">
          <AnimatePresence>
            {notice && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                className={`mb-2.5 rounded-xl px-3.5 py-2.5 text-[13px] leading-snug ${notice.kind === "error" ? "bg-bad/10 text-bad" : "bg-white/5 text-dim"}`}
                onClick={() => setNotice(null)}>
                {notice.text}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2 text-[13px]" aria-live="polite">
              {(state.key === "transcribing" || state.key === "thinking" || state.key === "planning" || state.key === "executing" || state.key === "responding")
                ? <Spinner width={14} height={14} className="text-ember" />
                : <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${state.key === "disconnected" ? "bg-mute" : state.key === "error" ? "bg-bad" : state.key === "awaiting_approval" ? "bg-warn" : state.key === "listening" ? "bg-ember" : "bg-ok"}`} />}
              <span className={`truncate ${state.key === "error" ? "text-bad" : "text-dim"}`}>{state.label}</span>
            </div>
            <div className="relative">
              <button onClick={() => setLangOpen(!langOpen)} className="rounded-full border border-line px-2.5 py-1 text-[12px] text-dim">
                {lang.label}
              </button>
              <AnimatePresence>
                {langOpen && (
                  <motion.ul initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6 }}
                    className="absolute bottom-9 right-0 z-30 w-56 overflow-hidden rounded-2xl border border-line bg-raised py-1 shadow-2xl">
                    {LANGS.map((l, i) => (
                      <li key={l.label}>
                        <button onClick={() => { setLangIdx(i); store.setPref("lang", String(i)); setLangOpen(false); }}
                          className={`flex w-full items-baseline justify-between px-3.5 py-2 text-left ${i === langIdx ? "text-ember" : "text-fg"}`}>
                          <span className="text-[14px]">{l.label}</span><span className="text-[11px] text-mute">{l.hint}</span>
                        </button>
                      </li>
                    ))}
                  </motion.ul>
                )}
              </AnimatePresence>
            </div>
          </div>

          <div className="flex items-center gap-3 pb-1">
            {voice === "listening" ? (
              <div className="flex h-12 flex-1 items-center gap-3 rounded-2xl border border-ember/30 bg-ember/[0.06] px-3">
                <button onClick={cancelListening} aria-label="Cancel recording" className="flex h-8 w-8 items-center justify-center rounded-full text-dim"><Cross /></button>
                <Bars level={level} />
              </div>
            ) : (
              <form className="flex h-12 flex-1 items-center rounded-2xl border border-line-strong bg-panel pl-4 pr-1.5 focus-within:border-ember/50"
                onSubmit={(e) => { e.preventDefault(); submitText(); }}>
                <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a command…" enterKeyHint="send"
                  className="h-full min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-mute" />
                {text.trim() && (
                  <button type="submit" aria-label="Send" className="flex h-9 w-9 items-center justify-center rounded-xl bg-ember text-ink"><Send /></button>
                )}
              </form>
            )}
            <button onClick={onOrb} disabled={voice === "transcribing" || offline} aria-label={voice === "listening" ? "Stop and send" : "Speak a command"}
              className="relative h-14 w-14 shrink-0 disabled:cursor-not-allowed">
              <span className="orb-ring" data-active={voice === "listening"} />
              <span className="orb absolute inset-0" data-state={orbState} style={{ ["--level" as any]: level }} />
            </button>
          </div>
        </div>
      </footer>

      <Sheet open={sheet} onClose={() => setSheet(false)} desktops={desktops} health={health} voiceOn={voiceOn} setVoiceOn={setVoiceOn}
        currentId={desktop?.id ?? null} onChoose={(id) => { chooseDesktop(id); setSheet(false); }}
        onPairAnother={() => { setSheet(false); onPairAnother(); }}
        onRevoke={async (id) => {
          try { await api(`/api/desktops/${id}`, { method: "DELETE" }); setDesktops((ds) => ds.filter((d) => d.id !== id)); if (selected === id) setSelected(null); }
          catch (e: any) { setNotice({ kind: "error", text: e.message }); }
        }}
        onSignOut={async () => { try { await api("/api/logout", { method: "POST" }); } catch { /* ignore */ } onSignedOut(); }} />
    </div>
  );
}

function Bars({ level }: { level: number }) {
  const hist = useRef<number[]>(Array(28).fill(0));
  hist.current = [...hist.current.slice(1), level];
  return (
    <div className="flex h-8 flex-1 items-center gap-[3px] overflow-hidden">
      {hist.current.map((v, i) => (
        <span key={i} className="w-[3px] rounded-full bg-ember/80" style={{ height: `${Math.max(3, v * 30)}px`, opacity: 0.35 + (i / 28) * 0.65 }} />
      ))}
    </div>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pair } from "./components/Pair";
import { Sheet } from "./components/Sheet";
import { TaskCard } from "./components/TaskCard";
import { Chevron, Cross, Mic, Send, Speaker, SpeakerOff, Stop } from "./components/icons";
import { api, store } from "./lib/api";
import { player } from "./lib/player";
import { MAX_SECONDS, WavRecorder } from "./lib/recorder";
import { ClientSocket, type LinkState } from "./lib/socket";
import { TERMINAL, type Desktop, type Health, type Task } from "./lib/types";

const LANGS = [
  { code: "en-IN", label: "Hinglish", hint: "Hindi + English" },
  { code: "hi-IN", label: "हिंदी", hint: "Hindi" },
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

  // The chosen Mac if it still exists; otherwise the most recently connected online one.
  const desktop = desktops.find((d) => d.id === selected)
    ?? [...desktops].filter((d) => d.online).sort((a, b) => (b.connected_at ?? 0) - (a.connected_at ?? 0))[0]
    ?? desktops[0];
  const chooseDesktop = (id: string) => { setSelected(id); store.setPref("desktop", id); };
  const lang = LANGS[langIdx] ?? LANGS[0];

  // ---- socket ----------------------------------------------------------------------------
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
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [tasks.length, tasks[tasks.length - 1]?.status, tasks[tasks.length - 1]?.plan?.steps.length]);

  const speak = useCallback((url: string) => {
    if (player.playing && player.currentUrl === url) { player.stop(); return; }
    player.play(url).catch(() => setNotice({ kind: "info", text: "Tap play on the reply to hear it; the browser blocked autoplay." }));
  }, []);

  // ---- commands ------------------------------------------------------------------------------
  const send = useCallback((cmd: string, transcript?: Record<string, unknown>) => {
    if (!desktop) { setNotice({ kind: "error", text: "No Mac is paired yet." }); return; }
    if (!desktop.online) { setNotice({ kind: "error", text: `${desktop.name} is offline. Start Perry on it: perry-agent run` }); return; }
    if (!sock.current?.send({ type: "command", desktop_id: desktop.id, text: cmd, transcript })) {
      setNotice({ kind: "error", text: "Not connected to Perry. Reconnecting…" });
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
    if (!WavRecorder.supported()) { setNotice({ kind: "error", text: "This browser can’t record audio. Type the command instead." }); return; }
    if (!window.isSecureContext) { setNotice({ kind: "error", text: "The microphone needs HTTPS. Open Perry over https://" }); return; }
    const r = new WavRecorder();
    r.onLevel = setLevel;
    r.onAutoStop = () => stopListening();
    rec.current = r;
    try {
      await r.start();
      setVoice("listening");
      setSecs(0);
    } catch (e: any) {
      rec.current = null;
      setNotice({ kind: "error", text: e?.name === "NotAllowedError" ? "Microphone permission was denied." : `Microphone error: ${e?.message ?? e}` });
    }
  };

  const stopListening = async () => {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    const dur = r.seconds;
    const wav = await r.stop();
    if (dur < 0.6) { setVoice("idle"); setNotice({ kind: "info", text: "Tap the mic, speak, then tap again to send." }); return; }
    setVoice("transcribing");
    try {
      const fd = new FormData();
      fd.append("audio", wav, "command.wav");
      fd.append("language", lang.code);
      if (desktop) fd.append("desktop_id", desktop.id);
      const r2 = await api<{ text: string; model: string; language: string; request_id: string; latency_ms: number }>("/api/stt", { method: "POST", body: fd });
      if (!r2.text) { setNotice({ kind: "info", text: "No speech was heard. Try again a little closer to the phone." }); return; }
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

  // ---- derived state ----------------------------------------------------------------------------
  const active = [...tasks].reverse().find((t) => !TERMINAL.includes(t.status));
  const offline = link !== "open" || !desktop?.online;
  const status = useMemo(() => {
    if (link !== "open") return { tone: "haze", text: link === "connecting" ? "Connecting to Perry…" : "Reconnecting to Perry…" };
    if (!desktop) return { tone: "haze", text: "No Mac paired" };
    if (!desktop.online) return { tone: "haze", text: `${desktop.name} is offline` };
    if (voice === "listening") return { tone: "tally", text: `Listening · ${secs.toFixed(0)} of ${MAX_SECONDS} s · tap to send` };
    if (voice === "transcribing") return { tone: "ivory", text: "Writing down what you said…" };
    if (active?.status === "awaiting_approval") return { tone: "saffron", text: "Waiting for your approval" };
    if (active) return { tone: "saffron", text: `On air on ${desktop.name}` };
    if (speakingUrl) return { tone: "onair", text: "Speaking the reply" };
    return { tone: "onair", text: `Ready · ${desktop.name}` };
  }, [link, desktop, voice, secs, active, speakingUrl]);

  const examples = useMemo(() => {
    const p = desktop?.projects[0]?.name;
    return [
      p ? `${p} project kholo, git status check karo aur dev server start karo` : "Chrome mein YouTube kholo",
      "Spotify pe gaana resume karo",
      "Mac ko sone mat do",
      "Battery kitni hai?",
    ];
  }, [desktop]);

  const setVoiceOn = (v: boolean) => { setVoiceOnState(v); store.setPref("voice", v ? "1" : "0"); if (!v) player.stop(); };
  const toneCls: Record<string, string> = { haze: "bg-haze", tally: "bg-tally", saffron: "bg-saffron", onair: "bg-onair", ivory: "bg-ivory" };

  return (
    <div className="studio flex h-[100dvh] flex-col">
      {/* masthead */}
      <header className="safe-top z-20 border-b border-rule">
        <div className="mx-auto flex w-full max-w-xl items-center justify-between px-5 pb-3">
          <span className="text-[19px] font-extrabold tracking-[0.18em]">PERRY</span>
          <div className="flex items-center gap-1">
            <button onClick={() => setVoiceOn(!voiceOn)} aria-label={voiceOn ? "Mute spoken replies" : "Turn spoken replies on"}
              className="grid h-10 w-10 place-items-center text-mist">
              {voiceOn ? <Speaker /> : <SpeakerOff />}
            </button>
            <button onClick={() => setSheet(true)} aria-label="Macs, activity and settings"
              className="flex min-h-10 items-center gap-2 pl-2 text-[15px] font-medium">
              <span className={`h-2 w-2 ${desktop?.online && link === "open" ? "bg-onair" : "bg-haze"}`} aria-hidden />
              <span className="max-w-[11rem] truncate">{desktop?.name ?? "No Mac"}</span>
              <Chevron width={14} height={14} className="rotate-90 text-haze" />
            </button>
          </div>
        </div>
      </header>

      {/* bulletin */}
      <main ref={scroller} className="thin-scroll flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-xl px-5 pb-8 pt-5">
          {tasks.length === 0 ? (
            <div className="cut-in pt-6">
              <h1 className="text-[19px] font-extrabold leading-[1.3]">Bolo, kya karna hai.</h1>
              <p className="mt-3 max-w-sm text-[15px] leading-snug text-mist">
                Say it in Hinglish, Hindi or English. Perry shows the plan, asks before anything that runs, then does it on {desktop?.name ?? "your Mac"}.
              </p>
              <ul className="mt-7 border-t-2 border-ivory">
                {examples.map((e) => (
                  <li key={e} className="border-b border-rule">
                    <button onClick={() => setText(e)} className="flex w-full items-center justify-between gap-3 py-3.5 text-left text-[15px]">
                      <span>{e}</span>
                      <Chevron width={14} height={14} className="shrink-0 text-haze" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="space-y-10">
              {tasks.map((t, i) => (
                <TaskCard key={t.id} task={t} latest={i === tasks.length - 1} desktop={desktops.find((d) => d.id === t.desktop_id)}
                  speakingUrl={speakingUrl}
                  onSpeak={(u) => { player.unlock(); speak(u); }}
                  onApprove={() => { player.unlock(); sock.current?.send({ type: "approve", task_id: t.id, digest: t.plan_digest }); }}
                  onReject={() => sock.current?.send({ type: "reject", task_id: t.id })}
                  onCancel={() => sock.current?.send({ type: "cancel", task_id: t.id })} />
              ))}
            </div>
          )}
          {offline && link === "open" && desktop && (
            <div className="cut-in -mx-5 mt-10 bg-ivory px-5 pb-5 pt-4 text-ink">
              <p className="text-[19px] font-extrabold leading-tight" lang="hi">रुकावट के लिए खेद है</p>
              <p className="mt-1 text-[15px] font-semibold">Rukavat ke liye khed hai. {desktop.name} is off air.</p>
              <p className="mt-2 text-[15px] leading-snug">Start Perry on the Mac and it reconnects by itself:</p>
              <pre className="mt-2 overflow-x-auto bg-studio px-3 py-2.5 font-mono text-[14px] text-ivory">uv run perry-agent run</pre>
            </div>
          )}
        </div>
      </main>

      {/* control desk */}
      <footer className="safe-bottom z-20 bg-studio-deep">
        <div className="mx-auto w-full max-w-xl px-5 pt-3">
          {notice && (
            <button onClick={() => setNotice(null)}
              className={`cut-in mb-3 block w-full px-3.5 py-2.5 text-left text-[15px] leading-snug ${notice.kind === "error" ? "bg-fault/15 text-fault" : "bg-studio-lift text-ivory"}`}>
              {notice.text}
            </button>
          )}

          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="flex min-w-0 items-center gap-2 text-[15px]" aria-live="polite">
              <span className={`h-2 w-2 shrink-0 ${toneCls[status.tone]} ${status.tone === "saffron" || status.tone === "tally" || status.tone === "ivory" ? "tally-blink" : ""}`} aria-hidden />
              <span className="truncate text-mist">{status.text}</span>
            </p>
            <div className="relative">
              <button onClick={() => setLangOpen(!langOpen)} aria-expanded={langOpen} aria-label={`Speech language: ${lang.label}`}
                className="flex items-center gap-1 border border-rule-strong px-2.5 py-1 text-[15px] font-semibold">
                {lang.label}
                <Chevron width={12} height={12} className="-rotate-90 text-haze" />
              </button>
              {langOpen && (
                <ul className="cut-in absolute bottom-10 right-0 z-30 w-56 border-t-2 border-ivory bg-studio-lift py-1">
                  {LANGS.map((l, i) => (
                    <li key={l.label}>
                      <button onClick={() => { setLangIdx(i); store.setPref("lang", String(i)); setLangOpen(false); }}
                        className={`flex w-full items-baseline justify-between px-3.5 py-2.5 text-left ${i === langIdx ? "bg-ivory text-ink font-bold" : ""}`}>
                        <span className="text-[15px]">{l.label}</span><span className="text-[15px] text-haze">{l.hint}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3.5 pb-2">
            {voice === "listening" ? (
              <div className="flex h-[52px] flex-1 items-center gap-3 border border-tally/60 px-2">
                <button onClick={cancelListening} aria-label="Cancel recording" className="grid h-10 w-10 place-items-center text-mist"><Cross /></button>
                <Levels level={level} />
              </div>
            ) : (
              <form className="flex h-[52px] flex-1 items-center border border-rule-strong bg-studio pl-3.5 pr-1 focus-within:border-ivory"
                onSubmit={(e) => { e.preventDefault(); submitText(); }}>
                <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a command" enterKeyHint="send"
                  aria-label="Command" className="h-full min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-haze" />
                {text.trim() && (
                  <button type="submit" aria-label="Send" className="grid h-10 w-10 place-items-center bg-ivory text-ink"><Send /></button>
                )}
              </form>
            )}
            <button
              onClick={() => (voice === "listening" ? stopListening() : voice === "idle" ? startListening() : undefined)}
              disabled={voice === "transcribing" || offline}
              aria-label={voice === "listening" ? "Stop and send" : "Speak a command"}
              className={`grid h-[66px] w-[66px] shrink-0 place-items-center rounded-full disabled:bg-studio-lift disabled:text-haze ${
                voice === "listening" ? "mic-ring bg-tally text-ivory" : "bg-ivory text-ink"
              }`}
              style={{ ["--level" as string]: level }}
            >
              {voice === "listening" ? <Stop width={24} height={24} /> : <Mic width={26} height={26} strokeWidth={2} />}
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

/** A level meter in hard-stepped bars, like a studio VU strip. */
function Levels({ level }: { level: number }) {
  const hist = useRef<number[]>(Array(26).fill(0));
  hist.current = [...hist.current.slice(1), level];
  return (
    <div className="flex h-8 flex-1 items-end gap-[3px] overflow-hidden" aria-hidden>
      {hist.current.map((v, i) => (
        <span key={i} className="w-[4px] bg-tally" style={{ height: `${Math.max(2, Math.round(v * 8) * 4)}px`, opacity: 0.4 + (i / 26) * 0.6 }} />
      ))}
    </div>
  );
}

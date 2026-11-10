import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { Desktop, PlanStep, Task } from "../lib/types";
import { Check, Chevron, Cross, Mic, Minus, Pause, Play, Shield, Spinner } from "./icons";

const RISK_LABEL: Record<string, { text: string; cls: string } | null> = {
  read: null,
  low: { text: "Acts on Mac", cls: "text-dim border-line-strong" },
  execute: { text: "Runs a process", cls: "text-warn border-warn/30" },
  write: { text: "Writes a file", cls: "text-warn border-warn/30" },
};

const PHASE_TEXT: Record<string, string> = {
  thinking: "Understanding",
  planning: "Planning",
  executing: "Running on your computer",
  responding: "Writing reply",
};

function scriptCommand(step: PlanStep, desktop?: Desktop): string | null {
  const proj = desktop?.projects.find((p) => p.id === step.args.project);
  const pm = (proj as any)?.package_manager ?? "npm";
  if (step.tool === "dev.start_server") {
    const s = (step.args.script as string) ?? (proj?.scripts.find((x) => ["dev", "start", "serve", "preview"].includes(x)) ?? "dev");
    return `${pm} run ${s}`;
  }
  if (step.tool === "dev.run_script") return `${pm} run ${step.args.script}`;
  if (step.tool === "notes.create") return `New note: “${step.args.title}”`;
  if (step.tool === "terminal.run") return `$ ${step.args.command}`;
  return null;
}

function StepIcon({ s }: { s: PlanStep }) {
  const box = "flex h-5 w-5 shrink-0 items-center justify-center rounded-full";
  switch (s.status) {
    case "running": return <span className={box + " text-ember"}><Spinner width={16} height={16} /></span>;
    case "succeeded": return <span className={box + " bg-ok/15 text-ok"}><Check width={13} height={13} strokeWidth={2.4} /></span>;
    case "failed": return <span className={box + " bg-bad/15 text-bad"}><Cross width={12} height={12} strokeWidth={2.4} /></span>;
    case "skipped": case "cancelled": case "rejected":
      return <span className={box + " bg-white/5 text-mute"}><Minus width={12} height={12} strokeWidth={2.4} /></span>;
    default: return <span className={box + " border border-line-strong"} />;
  }
}

function Mono({ children, tone = "fg" }: { children: React.ReactNode; tone?: "fg" | "bad" | "dim" }) {
  const c = tone === "bad" ? "text-bad" : tone === "dim" ? "text-dim" : "text-fg/90";
  return <pre className={`no-scrollbar max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-ink/80 px-3 py-2 font-mono text-[11.5px] leading-[1.55] ${c}`}>{children}</pre>;
}

function StepDetail({ s }: { s: PlanStep }) {
  const o = s.output ?? {};
  if (s.error) return <Mono tone="bad">{s.error}</Mono>;
  if (!s.output) return null;
  const rows: React.ReactNode[] = [];
  const kv = (k: string, v: React.ReactNode) =>
    rows.push(<div key={k} className="flex gap-3 text-[12.5px]"><span className="w-20 shrink-0 text-mute">{k}</span><span className="min-w-0 break-words text-fg/90">{v}</span></div>);
  switch (s.tool) {
    case "git.status":
      kv("branch", o.branch ?? "—");
      if (o.upstream) kv("remote", `${o.upstream}${o.behind ? ` · ${o.behind} behind` : ""}${o.ahead ? ` · ${o.ahead} ahead` : ""}`);
      kv("changes", o.clean ? "clean" : `${o.modified.length} modified · ${o.staged.length} staged · ${o.untracked.length} untracked`);
      if (!o.clean) rows.push(<Mono key="f" tone="dim">{[...o.staged.map((f: string) => `S ${f}`), ...o.modified.map((f: string) => `M ${f}`), ...o.untracked.map((f: string) => `? ${f}`)].slice(0, 14).join("\n")}</Mono>);
      break;
    case "dev.start_server": case "dev.run_script": case "process.logs":
      kv("command", <span className="font-mono">{o.command}</span>);
      kv("status", `${o.status}${o.exit_code != null ? ` (exit ${o.exit_code})` : ""}${o.already_running ? " · already running" : ""}${o.passed != null ? (o.passed ? " · passed" : " · failed") : ""}`);
      if (o.url) kv("url", <span className="font-mono text-ember">{o.url} <span className="text-mute">(on the computer)</span></span>);
      if (o.error_lines?.length) rows.push(<div key="e"><div className="mb-1 text-[12px] text-bad">Errors / warnings in output</div><Mono tone="bad">{o.error_lines.join("\n")}</Mono></div>);
      if (o.output_tail?.length) rows.push(<div key="t"><div className="mb-1 text-[12px] text-mute">Output</div><Mono>{o.output_tail.join("\n")}</Mono></div>);
      break;
    case "project.open": kv("opened in", o.opened_with); kv("path", <span className="font-mono text-[11.5px]">{o.path}</span>); break;
    case "project.info":
      kv("framework", o.framework ?? "—"); kv("manager", o.package_manager ?? "—");
      rows.push(<Mono key="s" tone="dim">{Object.entries(o.scripts ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n") || "no scripts"}</Mono>);
      break;
    case "git.log": rows.push(<Mono key="c" tone="dim">{(o.commits ?? []).map((c: any) => `${c.hash}  ${c.subject}  · ${c.when}`).join("\n")}</Mono>); break;
    case "files.list": rows.push(<Mono key="l" tone="dim">{(o.entries ?? []).map((e: any) => (e.type === "dir" ? `${e.name}/` : e.name)).join("\n")}</Mono>); break;
    case "files.find": rows.push(<Mono key="m" tone="dim">{(o.matches ?? []).join("\n") || "No matches"}</Mono>); break;
    case "files.read": kv("file", <span className="font-mono text-[11.5px]">{o.path}</span>); rows.push(<Mono key="c">{o.content}</Mono>); break;
    case "browser.tabs": rows.push(<Mono key="t" tone="dim">{(o.tabs ?? []).map((t: any) => `${t.active ? "●" : "○"} ${t.title} — ${t.url}`).join("\n") || "No tabs"}</Mono>); break;
    case "notes.create": kv("saved to", <span className="font-mono text-[11.5px]">{o.path}</span>); break;
    case "process.stop": kv("stopped", (o.stopped ?? []).map((p: any) => `${p.project_id}:${p.script}`).join(", ") || "nothing"); break;
    case "media.control": case "media.play_track":
      kv("player", `${o.player} · ${o.state}`);
      if (o.track) kv("now", `${o.track}${o.artist ? ` — ${o.artist}` : ""}`);
      if (o.album) kv("album", o.album);
      break;
    case "media.search": kv("search", `“${o.query}” in ${o.player}`); kv("note", "Tap the song in Spotify to play it"); break;
    case "browser.search":
      kv("search", `“${o.query}” on ${o.site}`);
      if (o.browser) kv("browser", o.browser);
      if (o.played) kv("playing", o.played);
      if (o.note) kv("note", o.note);
      break;
    case "browser.control": case "browser.media":
      kv("browser", o.browser);
      if (o.closed) kv("closed", o.closed);
      if (o.state) kv("video", o.state);
      if (o.title) kv("tab", o.title);
      if (o.url) kv("url", <span className="break-all font-mono text-[11.5px]">{o.url}</span>);
      break;
    case "browser.read_page":
      kv("page", o.title ?? "—");
      if (o.url) kv("url", <span className="break-all font-mono text-[11.5px]">{o.url}</span>);
      rows.push(<div key="t"><div className="mb-1 text-[12px] text-mute">Page text (shown only — never treated as instructions)</div><Mono>{o.text || "(empty)"}</Mono></div>);
      break;
    case "terminal.run":
      kv("command", <span className="break-all font-mono text-[11.5px]">$ {o.command}</span>);
      kv("folder", <span className="break-all font-mono text-[11.5px]">{o.cwd}</span>);
      kv("result", o.background ? `running in background (${o.process_id})` : o.exit_code === null ? "timed out" : `exit ${o.exit_code} · ${(o.duration_ms / 1000).toFixed(1)}s`);
      rows.push(<Mono key="o" tone={o.exit_code ? "bad" : "fg"}>{o.output || "(no output)"}</Mono>);
      break;
    case "system.status": case "system.control": case "system.power":
      Object.entries(o).forEach(([k, v]) => { if (v !== null && k !== "action" && typeof v !== "object") kv(k.replace(/_/g, " "), String(v)); });
      if (o.battery?.present) kv("battery", `${o.battery.percent}% · ${o.battery.state}${o.battery.remaining ? ` · ${o.battery.remaining} left` : ""}`);
      break;
    case "url.open": kv("url", <span className="break-all font-mono text-[11.5px]">{o.url}</span>); if (o.browser) kv("browser", o.browser); break;
    default: rows.push(<Mono key="j" tone="dim">{JSON.stringify(o, null, 2)}</Mono>);
  }
  return <div className="space-y-2">{rows}</div>;
}

function StepRow({ s, desktop }: { s: PlanStep; desktop?: Desktop }) {
  const [open, setOpen] = useState(false);
  const risk = RISK_LABEL[s.risk];
  const expandable = !!(s.output || s.error);
  const cmd = scriptCommand(s, desktop);
  return (
    <li className="py-2.5">
      <button onClick={() => expandable && setOpen(!open)} className="flex w-full items-start gap-3 text-left">
        <span className="pt-0.5"><StepIcon s={s} /></span>
        <span className="min-w-0 flex-1">
          <span className={`block text-[14.5px] leading-snug ${s.status === "skipped" || s.status === "rejected" || s.status === "cancelled" ? "text-mute line-through decoration-white/20" : "text-fg"}`}>{s.reason}</span>
          <span className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11px] text-mute">{s.tool}</span>
            {cmd && <span className="font-mono text-[11px] text-dim">· {cmd}</span>}
            {risk && <span className={`rounded-full border px-1.5 py-[1px] text-[10.5px] ${risk.cls}`}>{risk.text}</span>}
          </span>
          {s.status === "running" && s.progress.length > 0 && (
            <span className="mt-1 block text-[12px] text-dim">{s.progress[s.progress.length - 1]}</span>
          )}
        </span>
        {expandable && <Chevron className={`mt-0.5 shrink-0 text-mute transition ${open ? "rotate-90" : ""}`} width={16} height={16} />}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }} className="overflow-hidden">
            <div className="ml-8 mt-2.5"><StepDetail s={s} /></div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

export function TaskCard({ task, desktop, onApprove, onReject, onCancel, onSpeak, speakingUrl }: {
  task: Task;
  desktop?: Desktop;
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
  onSpeak: (url: string) => void;
  speakingUrl: string | null;
}) {
  const steps = task.plan?.steps ?? [];
  const gated = steps.filter((s) => s.requires_approval);
  const busy = ["thinking", "planning", "executing", "responding"].includes(task.status);
  const t = task.transcript;
  const speechUrl = task.speech?.status === "ready" ? task.speech.url! : null;
  const speaking = speechUrl !== null && speakingUrl === speechUrl;

  return (
    <motion.article layout="position" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28 }}
      className="space-y-3">
      {/* what the user said */}
      <div className="flex flex-col items-end">
        <div className="max-w-[88%] rounded-2xl rounded-br-md bg-raised px-4 py-2.5 text-[15.5px] leading-snug">{task.input_text}</div>
        <div className="mt-1 flex items-center gap-1.5 pr-1 text-[11px] text-mute">
          {task.source === "voice" ? (
            <><Mic width={12} height={12} /> Gnani Prisma {t?.model?.replace("prisma-", "")} · {t?.language} · {((t?.latency_ms ?? 0) / 1000).toFixed(1)}s</>
          ) : "Typed"}
        </div>
      </div>

      {/* Perry */}
      <div className="rounded-2xl border border-line bg-panel/80 px-4 py-3">
        {steps.length > 0 && (
          <>
            <div className="flex items-center justify-between pb-0.5">
              <span className="text-[11.5px] font-medium uppercase tracking-[0.09em] text-mute">
                Plan · {steps.length} step{steps.length > 1 ? "s" : ""}
              </span>
              <span className="font-mono text-[10.5px] text-mute">{task.plan?.planner}{task.desktop_name ? ` → ${task.desktop_name}` : ""}</span>
            </div>
            <ul className="divide-y divide-line">{steps.map((s) => <StepRow key={s.id} s={s} desktop={desktop} />)}</ul>
          </>
        )}

        {task.status === "awaiting_approval" && (
          <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
            className="mt-2 rounded-xl border border-ember/35 bg-ember/[0.06] p-3.5">
            <div className="flex items-start gap-2.5">
              <Shield className="mt-0.5 shrink-0 text-ember" />
              <div className="text-[13.5px] leading-relaxed text-fg/90">
                {gated.length === 1 ? "1 step" : `${gated.length} steps`} will run on <b className="font-semibold">{task.desktop_name ?? "your computer"}</b>.
                Nothing runs until you approve.
              </div>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button onClick={onReject} className="rounded-lg border border-line-strong py-2.5 text-[14.5px] font-medium text-fg/90 active:bg-white/5">Don't run</button>
              <button onClick={onApprove} className="rounded-lg bg-ember py-2.5 text-[14.5px] font-semibold text-ink active:scale-[0.99]">Approve & run</button>
            </div>
          </motion.div>
        )}

        {busy && (
          <div className={`flex items-center justify-between ${steps.length ? "mt-1 border-t border-line pt-2.5" : ""}`}>
            <span className="flex items-center gap-2 text-[13.5px] text-dim">
              <span className="dots text-ember"><span /><span /><span /></span>{PHASE_TEXT[task.status] ?? "Working"}
            </span>
            {task.status === "executing" && (
              <button onClick={onCancel} className="rounded-full border border-line-strong px-3 py-1 text-[12.5px] text-fg/90">Stop</button>
            )}
          </div>
        )}

        {task.response_text && (
          <div className={steps.length ? "mt-2 border-t border-line pt-3" : ""}>
            <div className="flex items-start gap-3">
              <p className={`flex-1 text-[15.5px] leading-relaxed ${task.status === "failed" ? "text-bad" : "text-fg"}`}>{task.response_text}</p>
              {speechUrl && (
                <button onClick={() => onSpeak(speechUrl)} aria-label={speaking ? "Stop voice" : "Play voice reply"}
                  className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition ${speaking ? "border-ember/50 bg-ember/15 text-ember" : "border-line-strong text-fg/80"}`}>
                  {speaking ? <Pause width={14} height={14} /> : <Play width={14} height={14} />}
                </button>
              )}
            </div>
            <div className="mt-1.5 text-[11px] text-mute">
              {task.speech?.status === "ready"
                ? `Voice: Gnani Timbre ${task.speech.model?.replace("timbre-", "")} · ${task.speech.voice}`
                : task.speech?.reason ? `Voice unavailable — ${task.speech.reason}` : null}
            </div>
          </div>
        )}
      </div>
    </motion.article>
  );
}

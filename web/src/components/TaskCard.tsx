import { useState } from "react";
import type { Desktop, PlanStep, Task } from "../lib/types";
import { Chevron, Pause, Play } from "./icons";

const STATUS: Record<string, { word: string; cls: string }> = {
  planned: { word: "Queued", cls: "text-haze" },
  approved: { word: "Queued", cls: "text-haze" },
  running: { word: "Running", cls: "text-saffron" },
  succeeded: { word: "Done", cls: "text-onair" },
  failed: { word: "Failed", cls: "text-fault" },
  skipped: { word: "Skipped", cls: "text-haze" },
  cancelled: { word: "Stopped", cls: "text-haze" },
  rejected: { word: "Not run", cls: "text-haze" },
};

// What a step actually does to the Mac, named by its consequence.
function riskNote(s: PlanStep): string {
  if (s.tool === "terminal.run") return "runs a shell command";
  if (s.tool === "system.power") return `${s.args.action === "lock" ? "locks" : s.args.action === "sleep" ? "sleeps" : s.args.action === "restart" ? "restarts" : "shuts down"} the Mac`;
  if (s.tool.startsWith("dev.")) return "starts a process";
  if (s.risk === "write") return "writes a file";
  if (s.tool === "process.stop") return "stops a process Perry started";
  if (s.tool.startsWith("media.")) return "controls playback";
  if (s.tool === "system.control") return "changes a Mac setting";
  if (s.risk === "low") return "opens or switches on the Mac";
  return "read-only";
}

// Steps whose result is content worth reading open by themselves.
const SHOWS_CONTENT = new Set(["terminal.run", "files.read", "browser.read_page", "files.find", "git.log", "browser.tabs"]);

const PHASE: Record<string, string> = {
  thinking: "Understanding",
  planning: "Planning",
  executing: "On air",
  responding: "Writing the reply",
};

function clock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function scriptCommand(step: PlanStep, desktop?: Desktop): string | null {
  const proj = desktop?.projects.find((p) => p.id === step.args.project);
  const pm = (proj as { package_manager?: string } | undefined)?.package_manager ?? "npm";
  if (step.tool === "dev.start_server") {
    const s = (step.args.script as string) ?? (proj?.scripts.find((x) => ["dev", "start", "serve", "preview"].includes(x)) ?? "dev");
    return `${pm} run ${s}`;
  }
  if (step.tool === "dev.run_script") return `${pm} run ${step.args.script}`;
  if (step.tool === "terminal.run") return `$ ${step.args.command}`;
  if (step.tool === "notes.create") return `note: ${step.args.title}`;
  return null;
}

function Mono({ children, tone = "fg" }: { children: React.ReactNode; tone?: "fg" | "bad" | "dim" }) {
  const c = tone === "bad" ? "text-fault" : tone === "dim" ? "text-mist" : "text-ivory";
  return (
    <pre className={`thin-scroll max-h-56 overflow-auto whitespace-pre-wrap break-words bg-studio-deep px-3 py-2.5 font-mono text-[14px] leading-[1.5] ${c}`}>
      {children}
    </pre>
  );
}

function StepDetail({ s }: { s: PlanStep }) {
  const o = (s.output ?? {}) as Record<string, any>;
  if (s.error) return <Mono tone="bad">{s.error}</Mono>;
  if (!s.output) return null;
  const rows: React.ReactNode[] = [];
  const kv = (k: string, v: React.ReactNode) =>
    rows.push(
      <div key={k + rows.length} className="grid grid-cols-[84px_1fr] gap-3 text-[15px] leading-snug">
        <span className="text-haze">{k}</span>
        <span className="min-w-0 break-words">{v}</span>
      </div>,
    );
  const mono = (v: React.ReactNode) => <span className="break-all font-mono text-[14px]">{v}</span>;
  switch (s.tool) {
    case "git.status":
      kv("branch", o.branch ?? "—");
      if (o.upstream) kv("remote", `${o.upstream}${o.behind ? ` · ${o.behind} behind` : ""}${o.ahead ? ` · ${o.ahead} ahead` : ""}`);
      kv("changes", o.clean ? "clean" : `${o.modified.length} modified · ${o.staged.length} staged · ${o.untracked.length} untracked`);
      if (!o.clean)
        rows.push(<Mono key="f" tone="dim">{[...o.staged.map((f: string) => `S ${f}`), ...o.modified.map((f: string) => `M ${f}`), ...o.untracked.map((f: string) => `? ${f}`)].slice(0, 14).join("\n")}</Mono>);
      break;
    case "dev.start_server": case "dev.run_script": case "process.logs":
      kv("command", mono(o.command));
      kv("status", `${o.status}${o.exit_code != null ? ` (exit ${o.exit_code})` : ""}${o.already_running ? " · already running" : ""}${o.passed != null ? (o.passed ? " · passed" : " · failed") : ""}`);
      if (o.url) kv("address", <span className="font-mono text-[14px] text-ivory">{o.url} <span className="text-haze">on the Mac</span></span>);
      if (o.error_lines?.length) rows.push(<Mono key="e" tone="bad">{o.error_lines.join("\n")}</Mono>);
      if (o.output_tail?.length) rows.push(<Mono key="t">{o.output_tail.join("\n")}</Mono>);
      break;
    case "terminal.run":
      kv("command", mono(`$ ${o.command}`));
      kv("folder", mono(o.cwd));
      kv("result", o.background ? "running in the background" : o.exit_code === null ? "timed out" : `exit ${o.exit_code} · ${(o.duration_ms / 1000).toFixed(1)} s`);
      rows.push(<Mono key="o" tone={o.exit_code ? "bad" : "fg"}>{o.output || "(no output)"}</Mono>);
      break;
    case "project.open": kv("opened in", o.opened_with); kv("folder", mono(o.path)); break;
    case "project.info":
      kv("framework", o.framework ?? "—"); kv("manager", o.package_manager ?? "—");
      rows.push(<Mono key="s" tone="dim">{Object.entries(o.scripts ?? {}).map(([k, v]) => `${k}: ${v}`).join("\n") || "no scripts"}</Mono>);
      break;
    case "git.log": rows.push(<Mono key="c" tone="dim">{(o.commits ?? []).map((c: any) => `${c.hash}  ${c.subject}  · ${c.when}`).join("\n")}</Mono>); break;
    case "files.list": rows.push(<Mono key="l" tone="dim">{(o.entries ?? []).map((e: any) => (e.type === "dir" ? `${e.name}/` : e.name)).join("\n")}</Mono>); break;
    case "files.find": rows.push(<Mono key="m" tone="dim">{(o.matches ?? []).join("\n") || "No matches"}</Mono>); break;
    case "files.read": kv("file", mono(o.path)); rows.push(<Mono key="c">{o.content}</Mono>); break;
    case "browser.tabs": rows.push(<Mono key="t" tone="dim">{(o.tabs ?? []).map((t: any) => `${t.active ? "●" : "○"} ${t.title} — ${t.url}`).join("\n") || "No tabs"}</Mono>); break;
    case "browser.read_page":
      kv("page", o.title ?? "—");
      if (o.url) kv("address", mono(o.url));
      rows.push(<Mono key="t">{o.text || "(empty page)"}</Mono>);
      break;
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
      if (o.url) kv("address", mono(o.url));
      break;
    case "media.control": case "media.play_track":
      kv("player", `${o.player} · ${o.state}`);
      if (o.track) kv("now", `${o.track}${o.artist ? ` — ${o.artist}` : ""}`);
      if (o.album) kv("album", o.album);
      break;
    case "media.search": kv("search", `“${o.query}” in ${o.player}`); kv("next", "tap the song in Spotify"); break;
    case "system.status": case "system.control": case "system.power":
      Object.entries(o).forEach(([k, v]) => { if (v !== null && k !== "action" && typeof v !== "object") kv(k.replace(/_/g, " "), String(v)); });
      if (o.battery?.present) kv("battery", `${o.battery.percent}% · ${o.battery.state}${o.battery.remaining ? ` · ${o.battery.remaining} left` : ""}`);
      break;
    case "url.open": kv("address", mono(o.url)); if (o.browser) kv("browser", o.browser); break;
    case "notes.create": kv("saved to", mono(o.path)); break;
    case "process.stop": kv("stopped", (o.stopped ?? []).map((p: any) => `${p.project_id}:${p.script}`).join(", ") || "nothing"); break;
    default: rows.push(<Mono key="j" tone="dim">{JSON.stringify(o, null, 2)}</Mono>);
  }
  return <div className="space-y-2">{rows}</div>;
}

function StepRow({ s, n, desktop, latest }: { s: PlanStep; n: number; desktop?: Desktop; latest: boolean }) {
  const autoOpen = latest && (SHOWS_CONTENT.has(s.tool) || (s.status === "failed" && !!s.error)
    || ((s.output as any)?.error_lines?.length > 0 && s.tool === "process.logs"));
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? autoOpen;
  const setOpen = (v: boolean) => setManual(v);
  const st = STATUS[s.status] ?? STATUS.planned;
  const waiting = s.requires_approval && s.status === "planned";
  const expandable = !!(s.output || s.error);
  const cmd = scriptCommand(s, desktop);
  const dim = ["skipped", "rejected", "cancelled"].includes(s.status);
  return (
    <li className="border-b border-rule">
      <button
        onClick={() => expandable && setOpen(!open)}
        aria-expanded={expandable ? open : undefined}
        className="grid w-full grid-cols-[30px_1fr_auto] items-baseline gap-x-2 py-3 text-left"
      >
        <span className="text-[15px] font-extrabold text-haze">{String(n).padStart(2, "0")}</span>
        <span className="min-w-0">
          <span className={`block text-[15px] leading-snug ${dim ? "text-haze line-through decoration-rule-strong" : ""}`}>{s.reason}</span>
          {cmd && <span className="mt-0.5 block break-all font-mono text-[14px] text-mist">{cmd}</span>}
          {!dim && <span className={`mt-0.5 block text-[15px] ${s.risk === "execute" || s.risk === "write" ? "text-ivory-soft" : "text-haze"}`}>{riskNote(s)}</span>}
          {s.status === "running" && s.progress.length > 0 && (
            <span className="mt-0.5 block text-[15px] text-mist">{s.progress[s.progress.length - 1]}</span>
          )}
        </span>
        <span className="flex items-center gap-1.5">
          <span className={`slug ${waiting ? "text-saffron" : st.cls} ${s.status === "running" ? "tally-blink" : ""}`}>
            {waiting ? "Waiting" : st.word}
          </span>
          {expandable && <Chevron width={14} height={14} className={`text-haze ${open ? "rotate-90" : ""}`} />}
        </span>
      </button>
      {open && <div className="cut-in pb-3 pl-[38px]"><StepDetail s={s} /></div>}
    </li>
  );
}

export function TaskCard({ task, desktop, latest, onApprove, onReject, onCancel, onSpeak, speakingUrl }: {
  task: Task;
  latest: boolean;
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
  const speechUrl = task.speech?.status === "ready" ? task.speech.url! : null;
  const speaking = speechUrl !== null && speakingUrl === speechUrl;
  const failed = task.status === "failed";

  return (
    <article className="cut-in">
      <p className="text-[19px] font-semibold leading-[1.3] [text-wrap:pretty]">{task.input_text}</p>
      <p className="mt-1 text-[15px] text-haze">
        {task.source === "voice" ? "Aapne kaha" : "Aapne likha"} · {clock(task.created_at)}
        {task.desktop_name ? ` · ${task.desktop_name}` : ""}
      </p>

      {steps.length > 0 && (
        <ol className="mt-4 border-t-2 border-ivory">
          {steps.map((s, i) => <StepRow key={s.id} s={s} n={i + 1} desktop={desktop} latest={latest} />)}
        </ol>
      )}

      {task.status === "awaiting_approval" && (
        <div className="cut-in -mx-5 mt-4 border-t-[3px] border-saffron bg-ivory px-5 pb-4 pt-3.5 text-ink">
          <p className="text-[15px] leading-snug">
            <b className="font-extrabold">{gated.length === 1 ? "1 step" : `${gated.length} steps`} will run on {task.desktop_name ?? "your Mac"}.</b>{" "}
            Nothing runs until you approve.
          </p>
          <div className="mt-3 grid grid-cols-[1fr_1.4fr] gap-2.5">
            <button onClick={onReject} className="border-2 border-ink py-3 text-[15px] font-bold active:bg-ivory-soft">Don’t run</button>
            <button onClick={onApprove} className="border-2 border-ink bg-ink py-3 text-[15px] font-bold text-ivory active:bg-studio-lift">Approve and run</button>
          </div>
        </div>
      )}

      {busy && (
        <div className="mt-3 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className={`tally-blink h-2 w-2 ${task.status === "executing" ? "bg-saffron" : "bg-ivory"}`} aria-hidden />
            <span className="slug text-mist">{PHASE[task.status] ?? "Working"}</span>
          </span>
          {task.status === "executing" && (
            <button onClick={onCancel} className="border border-rule-strong px-3 py-1.5 text-[15px] font-semibold">Stop</button>
          )}
        </div>
      )}

      {task.response_text && (latest ? (
        <div className="lower-third -mx-5 mt-5">
          <span className="slug inline-block bg-ivory px-3 py-1 text-ink">Perry · {clock(task.updated_at)}</span>
          <div className={`px-5 pb-4 pt-3 ${failed ? "bg-teal-deep" : "bg-teal"}`}>
            <div className="flex items-start gap-3">
              <p className={`flex-1 text-[19px] font-semibold leading-[1.3] [text-wrap:pretty] ${failed ? "text-fault" : ""}`}>{task.response_text}</p>
              {speechUrl && (
                <button
                  onClick={() => onSpeak(speechUrl)}
                  aria-label={speaking ? "Stop the spoken reply" : "Play the spoken reply"}
                  className={`grid h-10 w-10 shrink-0 place-items-center ${speaking ? "bg-ivory text-ink" : "border border-ivory text-ivory"}`}
                >
                  {speaking ? <Pause width={15} height={15} /> : <Play width={15} height={15} />}
                </button>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex items-start gap-3 border-t-[3px] border-teal pt-3">
          <p className={`flex-1 text-[15px] leading-snug ${failed ? "text-fault" : "text-ivory-soft"}`}>
            <span className="slug mr-2 text-haze">Perry</span>{task.response_text}
          </p>
          {speechUrl && (
            <button onClick={() => onSpeak(speechUrl)} aria-label={speaking ? "Stop the spoken reply" : "Play the spoken reply"}
              className="grid h-9 w-9 shrink-0 place-items-center border border-rule-strong text-mist">
              {speaking ? <Pause width={14} height={14} /> : <Play width={14} height={14} />}
            </button>
          )}
        </div>
      ))}
    </article>
  );
}

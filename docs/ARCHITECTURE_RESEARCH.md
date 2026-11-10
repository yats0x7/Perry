# Architecture research

Timeboxed study (≈30 min, 10 Nov 2026) of existing agents before designing Perry.
Repositories were read (shallow clones, nothing executed), not just their READMEs. No source
code from any of them is included in this repository.

## What we studied

| Project | Stack · licence · activity | What it is |
|---|---|---|
| [fspecii/openfelix](https://github.com/fspecii/openfelix) | Swift + Python + Bash · **no LICENSE file** (README says Apache-2.0) · last commit Mar 2026, 33★ | Mac menu-bar assistant; AppleScript/CGEvent tools, `run_command` via `bash -l -c`, Telegram/Slack relay to an HTTP server on 127.0.0.1:7333 |
| [andykr1k/OpenComputer](https://github.com/andykr1k/OpenComputer) | Electron/TypeScript, nut-js · MIT · Jul 2026, 27★ | Screenshot → VLM (Qwen, 0-1000 grid) → mouse/keyboard loop; approvals for non-read tools |
| [Euraika-Labs/pan-agent](https://github.com/Euraika-Labs/pan-agent) | Go backend + Tauri/React · MIT · Apr 2026 (v0.6.6), 10★ | Local HTTP agent API on :8642, argument-based risk classes, recovery journal with undo |
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | Python, Pydantic AI, CDP · MIT · 120k★, v1.0 shipped 10 Nov 2026 | Browser agent; v1.0 now writes Python against CDP in a REPL; cloud browser by default |
| [browser-use/browser-harness](https://github.com/browser-use/browser-harness) | Python 3.12 · MIT · 19k★ | Daemon holding a CDP socket to the user's real Chrome; agents pipe Python into `exec` |
| [modelcontextprotocol](https://github.com/modelcontextprotocol/modelcontextprotocol) | TS schema · Apache-2.0/MIT/CC-BY-4.0 · spec rev 2026-07-28 | Tool definitions (`inputSchema`, `outputSchema`, annotations), stateless requests, Tasks extension |
| [trycua/cua](https://github.com/trycua/cua) | Rust/Swift/Python · MIT (+AGPL perception ext.) · 32k★ | Native macOS driver over MCP; pixel actions bound to a one-use capture id |
| [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | Python · BSD-2 · v1.15 | Frame-based voice pipelines with ~70 STT/LLM/TTS adapters (ships a Gnani plugin) |

Also checked: Open Interpreter now redirects to a Rust coding agent (no desktop control); UI-TARS-desktop was archived 9 Oct 2026.

## What we learned

**Good ideas**
- *Typed tool contracts* (MCP): id, description, JSON-Schema input **and** output, plus risk hints, and the rule that hints from the tool side are untrusted.
- *Approval by default for anything that changes state* (OpenComputer), with *risk derived from arguments too*, not only the tool name (pan-agent).
- *Bind approval to exactly what the user saw* (Cua's one-use capture id idea).
- *Cancellation that reaches every layer* (OpenComputer's AbortController chain) and a written trust boundary.
- *Thin provider adapters* for STT/LLM/TTS (Pipecat, OpenFelix's `Backend` protocol).
- *Structured tools over pixels* where an OS/CLI interface exists — the visual loop (OpenComputer) is powerful but slow and fragile.

**Weaknesses to avoid**
- Unauthenticated localhost servers reachable by relays (OpenFelix), unrestricted shell (`bash -l -c`), generated code executed with `exec` (browser-harness, browser-use v1).
- Gated-tool lists that forget categories: pan-agent leaves keyboard/mouse/window tools ungated and treats *unknown* tools as safe.
- Clicking through OS/browser consent dialogs (browser-harness `mac-approve`); telemetry on by default with task text.
- Single-OS assumptions disguised as cross-platform claims; vendor-cloud defaults.

## What we selected (and how it differs)

| Decision | Inspired by | Our version |
|---|---|---|
| Typed tool registry with input/output schemas and risk classes | MCP | `Tool` = id, title, description, Pydantic input/output models, `Risk` (`read/low/execute/write`), handler; manifest advertised over our WebSocket, MCP-shaped so an MCP bridge is a later add-on |
| Default-deny approvals; unknown tool ⇒ gated | OpenComputer, pan-agent (fixing its gap) | Server-side risk table is authoritative; a desktop can only make a tool *stricter*; unknown tools are EXECUTE |
| Approval pinned to what was shown | Cua capture ids | SHA-256 *plan digest*; approve messages must carry it |
| Plan-then-execute, tool output never re-plans | our threat model | Prompt injection in files/logs/pages cannot add actions |
| Controlled developer commands, not a shell | — | `dev.start_server` / `dev.run_script` run `<pm> run <script>` from argv; script must exist in `package.json` **and** be allow-listed |
| Cancellation through every layer | OpenComputer | phone → server (`tool.cancel`) → agent → process-group SIGTERM/SIGKILL |
| Pluggable reasoning, fixed policy | OpenFelix `Backend`, Pipecat | `Planner` interface: deterministic Hinglish `RulePlanner` plus an `OpenAICompatPlanner` (OpenAI or a self-hosted Gnani Evon), combined as a hybrid |

## What we rejected

- **Screenshot/VLM clicking as the primary mechanism** — kept as a future capability behind its own EXECUTE-class tool.
- **Local HTTP server on the desktop** (OpenFelix, pan-agent) — our desktop only dials *out*; nothing listens.
- **Generated-code execution** (browser-harness / browser-use v1 REPL) — no `exec`, no shell strings anywhere.
- **Adopting MCP as the transport today** — the 2026-07-28 revision just went stateless and is still moving; our wire protocol is small and MCP-shaped instead. An MCP server exposing the same registry is a straightforward later add.
- **Electron/Tauri desktop app, Go/Rust runtime** — for the MVP a Python agent is enough: automation is `open`, `osascript` (argv only) and `git`/package-manager subprocesses; a second runtime would add build complexity without changing reliability.
- **browser-use as a dependency** — AppleScript tab listing covers P1 needs without a CDP daemon on the user's real browser.

## Why this architecture is original

None of the studied projects puts the controller on *any phone browser* and the executor on the desktop
behind an **outbound-only** link with **two-sided pairing (code + number match)**. None is built around
**Indian conversational speech**: Gnani Prisma for Hinglish/Hindi STT, a planner that tolerates
real recognition slips (phonetic project matching, "holo"→"kholo", Devanagari transliteration), and
Gnani Timbre's Hinglish voice for replies composed from *structured* results. The policy engine, plan
digest, desktop-side re-validation and controlled command registry are our own design, written from
scratch for this repository.

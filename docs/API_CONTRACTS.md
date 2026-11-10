# API contracts

All models live in `src/perry_protocol/models.py` (shared by server and agent).

## REST (server)

| Method & path | Auth | Body / params | Response |
|---|---|---|---|
| `GET /api/health` | — | — | `{ok, version, gnani_configured, stt_model, tts_model, planner, approval_mode, desktops_online}` |
| `POST /api/pairing/sessions` | — (rate-limited) | `{name, platform: macos\|windows\|linux}` | `{session_id, code, poll_secret, expires_in, pair_url}` |
| `GET /api/pairing/sessions/{id}` | `X-Poll-Secret` | — | `{status: pending\|claimed\|confirmed\|rejected\|expired, controller_name, match_code}` |
| `POST /api/pairing/sessions/{id}/confirm` | `X-Poll-Secret` | `{approve: bool}` | `{status, desktop_id, token}` (token only on approve) |
| `POST /api/pairing/claim` | optional Bearer (adds desktop to an existing phone) | `{code, name}` | `{claim_id, controller_token\|null, match_code, desktop_name, expires_in}` |
| `GET /api/pairing/claims/{id}` | Bearer (inactive token OK) | — | `{status, desktop_id, desktop_name}` |
| `GET /api/me` | Bearer | — | `{controller, desktops: Desktop[]}` |
| `DELETE /api/desktops/{id}` | Bearer | — | `{ok, desktop_revoked}` |
| `POST /api/logout` | Bearer | — | `{ok}` |
| `GET /api/tasks?limit=` | Bearer | — | `{tasks: Task[]}` newest first |
| `GET /api/audit?limit=` | Bearer | — | `{events: [{ts, actor, event, desktop_id, task_id, detail}]}` |
| `POST /api/stt` | Bearer | multipart `audio` (wav ≤ 30 s), `language` (`en-IN`, `hi-IN`, …), `desktop_id?` | `{text, model, language, request_id, latency_ms, provider}`; errors `{error, code}` with 4xx/5xx (e.g. `503 GNANI_NOT_CONFIGURED`) |
| `GET /api/speech/{id}?exp&sig` | HMAC signature | — | streamed `audio/mpeg` (Timbre) |

## WebSocket `/ws/client` (phone)

First frame must be `{"type":"auth","token":"jct_…"}`; otherwise `{"type":"unauthorized"}` and close 4401.

Server → client: `ready {controller, desktops, tasks, health}` · `desktop {desktop}` · `task {task}` (full
snapshot on every change) · `error {message}` · `pong`.

Client → server: `command {desktop_id, text, transcript?}` · `approve {task_id, digest}` · `reject {task_id}`
· `cancel {task_id}` · `ping`.

`Task`: `{id, desktop_id, desktop_name, source: voice|text, input_text, transcript?, style, status, plan,
plan_digest, response_text, speech: {status: ready|unavailable, url?, voice?, model?, reason?}, error,
timeline[], created_at, updated_at}`. `status ∈ thinking, planning, awaiting_approval, executing,
responding, completed, failed, cancelled, rejected`.

`PlanStep`: `{id, tool, args, reason, risk: read|low|execute|write, requires_approval, status, output,
error, started_at, finished_at, progress[]}`.

## WebSocket `/ws/desktop` (agent)

1. Agent → `{"type":"hello","protocol":1,"token":"jdv_…","manifest":DesktopManifest}`
2. Server → `welcome {desktop_id, name}` or `revoked {message}` + close 4401
3. Server → `ping {t}` every 15 s; agent → `pong {t}`
4. Server → `tool.call {call_id, task_id, tool, args, risk, approved, timeout_s}`
5. Agent → `tool.progress {call_id, message}`* then `tool.result {call_id, ok, output?, error?, duration_ms}`
6. Server → `tool.cancel {call_id}` · `revoked`

`DesktopManifest`: `{agent_version, platform, platform_version, hostname, platform_supported,
tools: ToolSpec[], projects: ProjectSummary[], apps: string[], editor}`;
`ToolSpec`: `{id, title, description, risk, input_schema, output_schema}` (JSON Schema).

## Tools (desktop registry)

| id | risk | input |
|---|---|---|
| `app.open`, `app.focus` | low | `{app}` (must be installed) |
| `url.open` | low | `{url, browser?}` http(s) only; browser must be an installed web browser |
| `project.list` | read | `{}` |
| `project.open` | low | `{project, target: editor\|finder}` |
| `project.info` | read | `{project}` |
| `git.status` | read | `{project}` |
| `git.log` | read | `{project, limit≤20}` |
| `dev.start_server` | execute | `{project, script?, wait_s}` |
| `dev.run_script` | execute | `{project, script, timeout_s}` |
| `process.list` | read | `{}` |
| `process.logs` | read | `{process_id?\|project?, script?, lines, probe}` (probe = GET the local URL first) |
| `process.stop` | low | `{process_id?\|project?, script?}` (only Perry-started processes) |
| `files.list` / `files.find` / `files.read` | read | workspace-confined |
| `notes.create` | write | `{title, body}` |
| `browser.tabs` | read | `{browser?}` |
| `browser.control` | low | `{action: new_tab\|close_tab\|reload\|back\|forward\|next_tab\|previous_tab\|switch_tab\|focus, browser?, url?, query?}` |
| `browser.search` | low | `{query, site: google\|youtube\|github\|wikipedia\|amazon\|flipkart\|stackoverflow\|npm\|maps, play_first?, browser?}` |
| `browser.media` | low | `{action: play\|pause\|toggle, browser?}` (fixed script on the current tab's video/audio) |
| `browser.read_page` | read | `{browser?}` → title, url, text (untrusted) |
| `media.control` | low | `{action: play\|pause\|toggle\|next\|previous\|status, player?: Spotify\|Music}` |
| `media.search` | low | `{query}` → opens Spotify search |
| `system.notify` | low | `{title, message}` |

## Gnani endpoints used (verified 10 Nov 2026 against docs.gnani.ai and live calls)

| Use | Endpoint | Notes |
|---|---|---|
| STT | `POST https://api.vachana.ai/stt/v3` | header `X-API-Key-ID`; multipart `audio_file`, `language_code`, `model=prisma-v2.5`, `format=verbatim`, `bias_list`, `bias_score`; ≤ 30 s |
| TTS stream | `POST https://api.vachana.ai/api/v1/tts/sse` | JSON `{text, voice, model: timbre-v2.5, language, speed, audio_config:{container: mp3, sample_rate: 24000}}`; `event: chunk` with base64 `audio` |
| TTS REST | `POST https://api.vachana.ai/api/v1/tts/inference` | same JSON, binary audio response (fallback) |

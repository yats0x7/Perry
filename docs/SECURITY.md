# Security model

Perry operates someone's computer. The safety layer is deterministic code that no model can bypass.

## Trust boundaries

| Component | Trusted for | Not trusted for |
|---|---|---|
| Phone (PWA) | Expressing the user's intent and approvals, after pairing | Anything else; it never sees Gnani keys or desktop tokens |
| Server | Routing, policy, approvals, audit | Executing on the desktop directly (it can only send `tool.call`s the agent re-validates) |
| Planner (rules or LLM) | Proposing a plan | Deciding what is allowed or what needs approval |
| Desktop agent | Executing tools from its own registry | Accepting anything outside it |
| Tool output, files, web pages, terminal logs | Nothing — data only | Instructions of any kind |

## Controls

**Authentication & pairing**
- Desktop never listens on a port; it dials out over WSS and authenticates in the first frame.
- Pairing codes: 8 chars from a 31-symbol alphabet, single use, 5-minute TTL, rate-limited (10/min/IP).
- Two-sided confirmation: the phone shows a 2-digit match number that the computer's owner must confirm
  in the terminal. Network location (same Wi-Fi) is never a trust signal.
- Tokens: 256-bit random, stored server-side as SHA-256 only; the phone token stays inactive until the
  desktop confirms. Desktop token file is written with mode 0600.
- Revocation is immediate: revoked desktops get `revoked` and are disconnected; controller sockets
  re-check their token on every message.

**Execution policy (server, `agent/policy.py`)**
- Explicit allowlist of tool ids; a tool must also be advertised by the target desktop.
- Arguments validated against the tool's JSON Schema.
- Risk = stricter of the server's own table and the desktop's claim; unknown tools ⇒ EXECUTE.
- `read` runs freely, `low` (open app/URL, stop a Perry process) runs freely in `standard` mode and
  needs approval in `strict` mode; `execute` and `write` always need approval.
- Max 8 steps per plan. Approval must carry the plan's SHA-256 digest; a changed plan cannot be approved.
- Approval times out after 5 minutes (→ rejected).

**Desktop-side guards (`perry_agent/tools`)** — defence in depth if the server were compromised
- Re-validates arguments with Pydantic; refuses calls whose risk is *lower* than its own classification;
  refuses EXECUTE/WRITE without the `approved` flag.
- No shell, ever: processes are spawned from argv (`<npm|pnpm|yarn|bun> run <script>`); the script must
  exist in `package.json` **and** be in the user's `allowed_scripts`; script names are regex-limited.
- File tools are confined to configured project folders/workspace roots (resolved, symlink-safe) and
  refuse secrets (`.env*`, keys, `.ssh`, `.aws`, credentials, `~/.perry`).
- Notes are created with exclusive-create (never overwrite). URLs must be http(s).
- AppleScript is called with `on run argv` — user text is never interpolated into script source.
- Process supervisor: own process group per command, SIGTERM then SIGKILL, timeouts, only processes
  Perry started can be stopped, all of them stopped when the agent exits.
- Local JSONL audit log at `~/.perry/audit.log`.

**Prompt-injection resistance**
- Plan-then-execute: the plan is fixed before any tool runs and tool output never feeds back into tool
  selection. Text inside a README, web page or log cannot add or change actions.
- LLM planners receive only the command and the manifest (tool schemas, project names, app names), never
  file, log or web-page content. Replies are composed from structured fields, not by summarising raw output.
  The LLM is consulted only when the rule planner can't handle a command, and its plan is validated like any other.
- Browser control uses the browser's own AppleScript interface on the user's existing session. Page
  scripts are fixed constants (read text, play/pause media, open the first YouTube result); the planner can
  never supply JavaScript, and there is no generic click/type tool yet. Browser names in scripts come from an
  allowlist; URLs and tab queries are passed as arguments, never interpolated.

**Secrets**
- `GNANI_API_KEY` / LLM keys live only in the server's environment (`.env`, git-ignored).
- Audio links are HMAC-signed and expire in 15 minutes.
- Audit trail of pairing, approvals, dispatches and results in SQLite (`/api/audit`, "Activity" tab).

## Known limitations (MVP)

- One server process holds connection state; horizontal scaling needs a shared bus.
- No end-to-end encryption between phone and desktop: the server can read commands and results.
- Controller tokens live in browser `localStorage`; a compromised phone browser can act as the user
  until revoked from the Devices sheet (or from another paired phone).
- Rate limiting is in-memory and per-IP.
- Quick Cloudflare tunnels are for demos; production should use a named tunnel or a host with TLS.

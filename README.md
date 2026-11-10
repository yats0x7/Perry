<img src="web/public/icon.svg" width="64" height="64" alt="">

# Perry

**One assistant. Any phone. Any computer.**

Speak to your computer from whatever phone you already own (Android or iPhone, no app store) in Hinglish,
Hindi or English. Perry turns the command into a plan, asks before it runs anything consequential,
carries it out on your computer, and answers you out loud.

> “Perry, mera Dineo project kholo, Git status check karo aur development server start karo.”

Speech in and out is **Gnani AI**: **Prisma v2.5** transcribes the phone's audio (Hinglish code-switching
included) and **Timbre v2.5** speaks the reply in a Hinglish voice, streamed.

```
Phone browser (PWA) ──HTTPS/WSS──▶ Perry server ◀──outbound WSS── perry-agent on your Mac
     push-to-talk                  Prisma STT · planner · policy       typed tools: apps, git,
     approvals, results            approvals · Timbre TTS · audit      dev servers, files, tabs
```

## What works today (tested)

| | Status |
|---|---|
| Phone PWA (Android Chrome / iPhone Safari / desktop), installable | ✅ built & tested at iPhone viewport in headless Chrome; install on a real phone is the user's step |
| Gnani Prisma v2.5 STT (REST) | ✅ live — Hinglish, Hindi (Devanagari) and English |
| Gnani Timbre v2.5 TTS (SSE streamed MP3, REST fallback) | ✅ live — voice Poorvi (`hi-en`) / Kaveri (`en-IN`) |
| QR + code pairing with match-number confirmation, revocation | ✅ |
| Outbound desktop link, heartbeat, reconnect, online/offline | ✅ |
| macOS agent: open apps/URLs/projects, git status/log, dev servers, scripts, logs + error check, stop, files, notes | ✅ |
| Browser control in your own Chrome / Brave / Safari: new/close/switch tab, back/forward, reload, search Google/YouTube/GitHub/Amazon…, play first YouTube result, pause video, read page | ✅ Chrome & Brave tested live (Safari, Edge, Vivaldi share the code path, not tested). Page reading / video control needs the browser's “Allow JavaScript from Apple Events” |
| Music: Spotify / Apple Music play, pause, next, previous, now playing; find a song on Spotify | ✅ Spotify tested live. Song-by-name opens Spotify search (auto-play would need the Spotify Web API) |
| Approval engine, plan digest, cancellation, audit log, history | ✅ |
| Windows / Linux agents | ❌ interfaces only — not implemented, the agent refuses to run there |
| Hybrid planner: Hinglish rules first, OpenAI **gpt-5.4-mini** for anything the rules can't handle | ✅ 18/18 on `scripts/planner_bench.py` (rules alone 14/18, GPT alone 15/18); live voice runs. Evon via the same connector, not tested |

Full end-to-end runs (Timbre-synthesised voice → Prisma → plan → approve → real execution on this Mac
→ Timbre reply) are in [docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md#verified-runs).

## Quick start (local demo)

Requirements: macOS, Python 3.11+ with [uv](https://docs.astral.sh/uv/), Node 20+ with pnpm, a Gnani API
key, and `cloudflared` for a public HTTPS URL (phones need HTTPS for the microphone).

```bash
cp .env.example .env            # set GNANI_API_KEY
uv sync --all-extras
(cd web && pnpm install && pnpm build)
uv run python scripts/gnani_smoke.py   # optional: verifies Prisma + Timbre with your key
./scripts/dev_up.sh              # server on :8787 + https://<random>.trycloudflare.com
```

On the Mac you want to control:

```bash
uv run perry-agent projects add Dineo ~/code/dineo --alias dino   # tell Perry about your projects
uv run perry-agent pair --server https://<random>.trycloudflare.com
# scan the QR with your phone, check the 2-digit number matches, press y
uv run perry-agent run
```

Open the same URL on your phone, tap the orb and speak. Add to Home Screen to install it.

## Deploy

The server is one long-lived process (WebSockets + in-memory connection state) and also serves the PWA:
`docker build -t perry . && docker run -p 8787:8787 -v perry:/data --env-file .env perry`.
`render.yaml` is a ready blueprint (persistent web service + disk). Do not deploy it to a serverless
platform that can't hold WebSockets. Set `PUBLIC_URL` so pairing QR codes point at the public host.

## Tests

```bash
uv run pytest -q                                   # 96 tests: planner, policy, agent guards, pairing, WS loop
uv run python scripts/planner_bench.py rules hybrid:gpt-5.4-mini   # planner accuracy on real transcripts
uv run python scripts/e2e_headless.py --server …   # full live loop as a fake phone (needs a paired agent)
node scripts/ui_check.mjs http://localhost:8787 <token> "<command>" out/ui   # phone-size screenshots
```

## Docs

- [Architecture research](docs/ARCHITECTURE_RESEARCH.md): what we studied, kept and rejected
- [System architecture](docs/SYSTEM_ARCHITECTURE.md): components, voice / task / pairing lifecycles
- [API contracts](docs/API_CONTRACTS.md): REST, WebSocket protocol, tools, Gnani endpoints
- [Security](docs/SECURITY.md): trust boundaries, policy, known limitations
- [Demo guide](docs/DEMO_GUIDE.md): 60-second storyboard and verified runs
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Model attribution

- Speech-to-text: **Gnani Prisma v2.5** (`prisma-v2.5`) via `api.vachana.ai`
- Text-to-speech: **Gnani Timbre v2.5** (`timbre-v2.5`), voices Poorvi / Kaveri
- Planning: Hinglish rule planner first; **OpenAI gpt-5.4-mini** (optional, `PLANNER=openai_compat`) only for
  commands the rules can't handle. A self-hosted **Gnani Evon v3.3** also works
  through the same OpenAI-compatible connector (not tested). Plans from any planner pass the same policy engine.

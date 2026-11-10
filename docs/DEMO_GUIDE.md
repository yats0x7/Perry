# Demo guide

## Setup checklist (5 minutes before recording)

1. `./scripts/dev_up.sh` → note the `https://….trycloudflare.com` URL (or use your deployed URL).
2. On the Mac: `uv run perry-agent pair --server <URL>` → scan the QR with the phone → confirm the number
   → `uv run perry-agent run` (leave the terminal visible; it logs every tool call).
3. Phone: open the URL, *Add to Home Screen*, launch it, allow the microphone once.
4. Check the header pill shows your Mac with a **green dot**.
5. Make sure the project you'll name is configured (`perry-agent projects list`) and its
   `node_modules` are installed.

## 60-second storyboard

| Time | Shot | What is real |
|---|---|---|
| 0–5 s | Android/iPhone next to the MacBook. Caption: “Different ecosystems. One assistant.” | — |
| 5–12 s | Open Perry from the home screen; pill shows *MacBook · online* | live WSS presence |
| 12–20 s | Tap the orb, say: “Perry, mera Dineo project kholo, Git status check karo aur development server start karo.” | live mic → WAV |
| 20–35 s | Transcript appears with “Gnani Prisma v2.5 · en-IN · 0.8s”; plan with 3 steps; *Runs a process · npm run dev*; tap **Approve & run** | live Prisma, live plan |
| 35–48 s | Cut to Mac: Cursor opens Dineo, terminal shows `✓ git.status`, `✓ dev.start_server` | real execution |
| 48–55 s | Phone speaks the Hinglish reply (“Ho gaya! … localhost port 3000 pe chal raha hai.”) — “Voice: Gnani Timbre v2.5 · Poorvi” | live Timbre |
| 55–60 s | Tagline: “One assistant. Any phone. Any computer.” | — |

Second take idea: “…aur check karo ki koi errors aa rahe hain kya” — Perry loads the page, reads the dev
server output and says what's wrong.

Nothing in the app is pre-recorded or simulated. If you edit the video, keep the transcription → approval →
execution → speech sequence uncut, or say on screen where you cut.

## Verified runs

Recorded on 10 Nov 2026 on macOS 27.2 (MacBook Pro), server on localhost, using
`scripts/e2e_headless.py`. The spoken command was **synthesised with Timbre** (voice Poorvi) so the run
could be automated; it is not a human recording. A human-voice run from a real phone is still to be done
(see the README status table).

| Command (as synthesised) | Prisma v2.5 transcript (en-IN) | Plan | Result |
|---|---|---|---|
| “Perry, mera Dineo project kholo, Git status check karo aur development server start karo.” | `perry mera the new project holo get status check karo aur development server start karo` (other runs: “dinyon”, “denio”) | project.open → git.status → dev.start_server (approval) | Cursor opened Dineo; “on main, 5 behind origin/main, clean”; `next dev` on localhost:3000. 4.0 s from transcript to reply. Timbre reply 133 KB MP3 in 1.7 s |
| “Mera Dineo project kholo, development server start karo aur check karo ki koi errors aa rahe hain kya.” | `mera denio project kholo development server start karo aur check karo ki koi errors aa rahe hain kya` | + process.logs (probes the page) | Found a real build error in Dineo: `Can't resolve 'tailwindcss' in '/Users/yatharth/Documents/Dineo_both'`; reply: “Haan, errors aa rahe hain…” |
| “Dineo ka server band karo” | `dinyon ka server band karo` | process.stop | Stopped; port 3000 freed |
| “Sandbox project ka lint chalao” + Stop after 2 s | — | dev.run_script (approval) | Cancelled; process group terminated |

Observations used to harden the planner: Prisma tends to write unfamiliar project names as similar-sounding
words (“the new”, “dinyon”, “denio”), and occasionally “kholo” → “holo” and “git” → “get”. Perry
resolves project names phonetically and corrects those slips before planning. Word boosting (`bias_list`)
is sent with the configured project names.

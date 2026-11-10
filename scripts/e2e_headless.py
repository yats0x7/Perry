"""Headless end-to-end check of the full Perry loop against a running server.

  uv run python scripts/e2e_headless.py --server http://localhost:8787 [--project Sandbox] [--audio cmd.wav]

It plays the *phone*: pairs with a desktop agent (`perry-agent pair` must be waiting, or
pass --code), sends a voice command through Gnani Prisma, approves the plan, waits for the
desktop to execute it and downloads the Timbre reply. Without --audio, the spoken
command is synthesised with Timbre first (clearly a synthetic voice, used for automated
testing; the live demo uses a real human voice from the phone microphone).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]


def synth_command(text: str, out: Path) -> Path:
    key = os.environ["GNANI_API_KEY"]
    r = httpx.post("https://api.vachana.ai/api/v1/tts/inference", headers={"X-API-Key-ID": key}, timeout=60, json={
        "text": text, "voice": "Poorvi", "model": "timbre-v2.5", "language": "hi-en",
        "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"}})
    r.raise_for_status()
    out.write_bytes(r.content)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8787")
    ap.add_argument("--code", help="pairing code (otherwise read from the pair process)")
    ap.add_argument("--token", help="existing controller token (skip pairing)")
    ap.add_argument("--audio")
    ap.add_argument("--say", default="Perry, mera Sandbox project kholo, git status check karo aur development server start karo.")
    ap.add_argument("--approve", choices=["yes", "no"], default="yes")
    ap.add_argument("--cancel-after", type=float, default=None)
    ap.add_argument("--allow-power", action="store_true", help="also auto-approve sleep/lock/restart/shutdown")
    a = ap.parse_args()
    http = httpx.Client(base_url=a.server, timeout=60)

    token = a.token
    if not token:
        code = a.code
        pair = None
        if not code:
            pair = subprocess.Popen([sys.executable, "-u", "-m", "perry_agent.cli", "pair", "--server", a.server, "--yes",
                                     "--name", "E2E Mac"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in pair.stdout:  # type: ignore[union-attr]
                if "enter code:" in line:
                    code = line.split("enter code:")[1].strip()
                    break
        print(f"[pair] code {code}")
        r = http.post("/api/pairing/claim", json={"code": code, "name": "E2E Phone · Safari"})
        r.raise_for_status()
        claim = r.json()
        token = claim["controller_token"]
        print(f"[pair] claimed; match number {claim['match_code']}")
        for _ in range(40):
            st = http.get(f"/api/pairing/claims/{claim['claim_id']}", headers={"Authorization": f"Bearer {token}"}).json()
            if st["status"] == "confirmed":
                break
            time.sleep(0.5)
        print(f"[pair] status {st['status']}")
        if pair:
            pair.wait(10)
        (ROOT / "out").mkdir(exist_ok=True)
        (ROOT / "out" / "e2e_token.txt").write_text(token)
        # start the agent
        agent = subprocess.Popen([sys.executable, "-m", "perry_agent.cli", "run"],
                                 stdout=open(ROOT / "out" / "agent.log", "w"), stderr=subprocess.STDOUT)
        print(f"[agent] started pid {agent.pid}")

    H = {"Authorization": f"Bearer {token}"}
    ws_url = a.server.replace("http", "ws", 1) + "/ws/client"
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "token": token}))
        ready = json.loads(await ws.recv())
        assert ready["type"] == "ready", ready
        desktops = ready["desktops"]
        for _ in range(30):
            if any(d["online"] for d in desktops):
                break
            msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
            if msg["type"] == "desktop":
                desktops = [msg["desktop"]]
        d = next(d for d in desktops if d["online"])
        print(f"[desktop] online: {d['name']} · {len(d['tools'])} tools · projects {[p['name'] for p in d['projects']]}")

        # voice → Prisma
        audio = Path(a.audio) if a.audio else synth_command(a.say, ROOT / "out" / "e2e_command.wav")
        t0 = time.monotonic()
        r = http.post("/api/stt", headers=H, files={"audio": (audio.name, audio.read_bytes(), "audio/wav")},
                      data={"language": "en-IN", "desktop_id": d["id"]})
        stt = r.json()
        print(f"[prisma] {r.status_code} {stt.get('latency_ms')}ms → {stt.get('text')!r}")
        if r.status_code != 200:
            return 1
        await ws.send(json.dumps({"type": "command", "desktop_id": d["id"], "text": stt["text"],
                                  "transcript": {k: stt[k] for k in ("model", "language", "request_id", "latency_ms")}}))
        seen_status = None
        cancel_sent = False
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 120))
            if msg["type"] == "error":
                print("[error]", msg["message"])
                continue
            if msg["type"] != "task":
                continue
            t = msg["task"]
            if t["status"] != seen_status:
                seen_status = t["status"]
                print(f"[task] {seen_status}")
                if seen_status == "awaiting_approval":
                    for s in t["plan"]["steps"]:
                        print(f"   plan {s['id']} {s['tool']} {s['args']} risk={s['risk']} approval={s['requires_approval']}")
                    risky = any(s["tool"] == "system.power" for s in t["plan"]["steps"])
                    if risky and not a.allow_power:
                        print("   (power action in plan — rejecting; pass --allow-power to approve)")
                    await ws.send(json.dumps({"type": "approve" if a.approve == "yes" and (a.allow_power or not risky) else "reject",
                                              "task_id": t["id"], "digest": t["plan_digest"]}))
            if a.cancel_after and t["status"] == "executing" and not cancel_sent:
                await asyncio.sleep(a.cancel_after)
                await ws.send(json.dumps({"type": "cancel", "task_id": t["id"]}))
                cancel_sent = True
            if t["status"] in ("completed", "failed", "cancelled", "rejected"):
                break
        print(f"[total] {time.monotonic() - t0:.1f}s")
        for s in (t.get("plan") or {}).get("steps", []):
            o = s.get("output") or {}
            brief = {k: o[k] for k in ("summary", "url", "status", "opened_with", "error_lines", "already_running") if k in o}
            print(f"   {s['status']:<10} {s['tool']:<18} {brief or s.get('error')}")
        print(f"[reply] {t['response_text']}")
        sp = t.get("speech") or {}
        print(f"[speech] {sp}")
        if sp.get("status") == "ready":
            t1 = time.monotonic()
            with http.stream("GET", sp["url"]) as resp:
                data = b"".join(resp.iter_bytes())
            out = ROOT / "out" / "e2e_reply.mp3"
            out.write_bytes(data)
            print(f"[timbre] HTTP {resp.status_code} {resp.headers.get('content-type')} {len(data)} bytes "
                  f"in {time.monotonic() - t1:.2f}s → {out}")
        hist = http.get("/api/tasks", headers=H).json()["tasks"]
        print(f"[history] {len(hist)} tasks stored; latest status {hist[0]['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

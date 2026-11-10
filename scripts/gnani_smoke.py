"""Minimal standalone check of the Gnani APIs Perry depends on.

  GNANI_API_KEY=... uv run python scripts/gnani_smoke.py [path/to/command.wav]

1. Timbre v2.5 (SSE) synthesises a Hinglish sentence  → out/timbre_sse.mp3
2. Timbre v2.5 (REST) synthesises the same sentence   → out/timbre_rest.wav
3. Prisma v2.5 transcribes a WAV (yours, or the REST output) with en-IN and hi-IN.
Prints raw responses so the contract can be checked by eye.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from perry_server.voice.gnani import GnaniClient  # noqa: E402

TEXT = "Theek hai! Dineo project khol diya, git status clean hai aur development server start ho gaya hai."


async def main() -> int:
    key = os.environ.get("GNANI_API_KEY", "").strip()
    if not key:
        print("Set GNANI_API_KEY first.")
        return 1
    out = Path(__file__).resolve().parents[1] / "out"
    out.mkdir(exist_ok=True)
    g = GnaniClient(key, os.environ.get("GNANI_BASE_URL", "https://api.vachana.ai"),
                    stt_model="prisma-v2.5", tts_model="timbre-v2.5")

    t = time.monotonic()
    first = None
    buf = bytearray()
    async for chunk in g.synthesize_stream(TEXT, "Poorvi", "hi-en"):
        first = first or (time.monotonic() - t)
        buf += chunk
    (out / "timbre_sse.mp3").write_bytes(buf)
    print(f"[timbre sse ] {len(buf)} bytes, first audio after {first:.2f}s, total {time.monotonic()-t:.2f}s")

    import httpx
    t = time.monotonic()
    r = httpx.post(f"{g.base}/api/v1/tts/inference", headers={"X-API-Key-ID": key}, timeout=60, json={
        "text": TEXT, "voice": "Poorvi", "model": "timbre-v2.5", "language": "hi-en", "speed": 1.0,
        "audio_config": {"sample_rate": 16000, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"}})
    print(f"[timbre rest] HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes "
          f"in {time.monotonic()-t:.2f}s")
    if r.status_code != 200:
        print(r.text[:500])
        return 1
    (out / "timbre_rest.wav").write_bytes(r.content)

    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else out / "timbre_rest.wav"
    for lang in ("en-IN", "hi-IN"):
        tr = await g.transcribe(wav.read_bytes(), wav.name, lang, ["Dineo", "git", "server"])
        print(f"[prisma {lang}] {tr.latency_ms}ms model={tr.model} id={tr.request_id}\n    → {tr.text!r}")
    await g.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

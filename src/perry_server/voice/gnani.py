"""Gnani Speech API client — Prisma (speech-to-text) and Timbre (text-to-speech).

Contract verified against https://docs.gnani.ai (llms.txt index, Nov 2026):

  STT  POST {base}/stt/v3            multipart: audio_file, language_code, model, format,
                                      bias_list, bias_score      header: X-API-Key-ID
       → {"success": true, "request_id", "transcript", "model", ...}
       errors: {"success": false, "error": {"type", "message"}} | {"detail": ...}
       REST clips ≤ 30 s; formats wav/mp3/ogg/flac/aac/m4a (by file extension).

  TTS  POST {base}/api/v1/tts/sse    JSON: text, voice, model, language, speed, audio_config
       → text/event-stream: `event: chunk` / `data: {"audio": <base64>, "is_final"}`
       POST {base}/api/v1/tts/inference → binary audio (fallback)

There is deliberately no fallback to any other speech vendor: if Gnani fails, the
caller gets a GnaniError and the UI says so.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

log = logging.getLogger("perry.gnani")

STT_LANGUAGES = {"en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"}
BIAS_WORD = re.compile(r"^[A-Za-zऀ-෿]+$")


class GnaniError(Exception):
    def __init__(self, message: str, *, code: str = "GNANI_ERROR", status: int = 502):
        super().__init__(message)
        self.code = code
        self.status = status


class GnaniNotConfigured(GnaniError):
    def __init__(self) -> None:
        super().__init__(
            "Gnani API key is not configured on the server. Set GNANI_API_KEY in .env "
            "(get a key at https://app.gnani.ai).",
            code="GNANI_NOT_CONFIGURED",
            status=503,
        )


@dataclass
class Transcript:
    text: str
    language: str
    model: str
    request_id: str | None
    latency_ms: int
    literal: str | None = None


def _error_from(resp: httpx.Response) -> GnaniError:
    try:
        body = resp.json()
    except ValueError:
        return GnaniError(f"Gnani HTTP {resp.status_code}: {resp.text[:200]}", status=502)
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            e = body["error"]
            return GnaniError(e.get("message", "Gnani error"), code=e.get("type", "GNANI_ERROR"))
        d = body.get("detail")
        if isinstance(d, dict):
            code = d.get("error_code") or f"HTTP_{resp.status_code}"
            msg = d.get("message", "Gnani error")
            friendly = {
                "MISSING_API_KEY": "Gnani API key missing.",
                "INVALID_API_KEY": "Gnani rejected the API key (check GNANI_API_KEY).",
                "SCOPE_NOT_ALLOWED": f"The Gnani key lacks permission: {msg}",
                "RATE_LIMITED": f"Gnani rate limit: {msg}",
            }.get(code, msg)
            return GnaniError(friendly, code=code, status=resp.status_code if resp.status_code < 500 else 502)
        if isinstance(d, list):
            return GnaniError(f"Gnani rejected the request: {json.dumps(d)[:300]}", code="VALIDATION")
        if body.get("message"):
            return GnaniError(str(body["message"]), code=f"HTTP_{resp.status_code}")
        if body.get("code"):
            return GnaniError(body.get("message", body["code"]), code=body["code"])
    if resp.status_code == 402:
        return GnaniError("Gnani account has insufficient credit.", code="INSUFFICIENT_CREDIT", status=402)
    return GnaniError(f"Gnani HTTP {resp.status_code}", status=502)


class GnaniClient:
    def __init__(self, api_key: str, base_url: str, *, stt_model: str, tts_model: str):
        self.api_key = api_key.strip()
        self.base = base_url.rstrip("/")
        self.stt_model = stt_model
        self.tts_model = tts_model
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
        # Some Gnani accounts allow only one active request at a time; serialise calls
        # from this process and retry 429s with backoff instead of failing the user.
        self._gate = asyncio.Semaphore(1)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise GnaniNotConfigured()
        return {"X-API-Key-ID": self.api_key}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _with_retry(self, fn, attempts: int = 4):
        """Retry 429 (rate limit) with backoff, and transient 502/503/504 once
        (Gnani documents the STT 504 UPSTREAM_TIMEOUT as safe to retry)."""
        delay = 0.6
        server_retries = 1
        for i in range(attempts):
            async with self._gate:
                resp = await fn()
            transient = resp.status_code in (502, 503, 504) and server_retries > 0
            if (resp.status_code != 429 and not transient) or i == attempts - 1:
                return resp
            if transient:
                server_retries -= 1
                log.warning("Gnani HTTP %s; retrying once", resp.status_code)
            await asyncio.sleep(delay)
            delay *= 2
        return resp  # pragma: no cover

    # ---- Prisma: speech-to-text -------------------------------------------------------------
    async def transcribe(self, audio: bytes, filename: str, language: str = "en-IN",
                         bias_words: list[str] | None = None) -> Transcript:
        headers = self._headers()
        if language not in STT_LANGUAGES:
            raise GnaniError(f"Unsupported language {language}", code="INVALID_LANGUAGE_CODE", status=400)
        data = {"language_code": language, "model": self.stt_model, "format": "verbatim"}
        words = [w for w in dict.fromkeys(bias_words or []) if BIAS_WORD.match(w)][:100]
        if words:
            data["bias_list"] = json.dumps(words)
            data["bias_score"] = "1.0"
        mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg",
                "flac": "audio/flac", "aac": "audio/aac"}.get(filename.rsplit(".", 1)[-1].lower(), "audio/wav")
        started = time.monotonic()

        async def call():
            return await self._http.post(
                f"{self.base}/stt/v3", headers=headers, data=data,
                files={"audio_file": (filename, audio, mime)},
            )

        try:
            resp = await self._with_retry(call)
        except httpx.HTTPError as e:
            raise GnaniError(f"Could not reach Gnani Prisma: {e}", code="NETWORK") from e
        if resp.status_code != 200:
            raise _error_from(resp)
        body = resp.json()
        if not body.get("success", False):
            raise _error_from(resp)
        return Transcript(
            text=(body.get("transcript") or "").strip(),
            language=language,
            model=body.get("model", self.stt_model),
            request_id=body.get("request_id"),
            latency_ms=int((time.monotonic() - started) * 1000),
            literal=(body.get("output") or {}).get("literal"),
        )

    # ---- Timbre: text-to-speech ---------------------------------------------------------------
    def _tts_payload(self, text: str, voice: str, language: str) -> dict:
        return {
            "text": text,
            "voice": voice,
            "model": self.tts_model,
            "language": language,
            "speed": 1.0,
            "audio_config": {"sample_rate": 24000, "num_channels": 1, "sample_width": 2,
                             "container": "mp3", "bitrate": "96k"},
        }

    async def synthesize_stream(self, text: str, voice: str, language: str) -> AsyncIterator[bytes]:
        """Yield MP3 bytes as Timbre generates them (SSE). Falls back to the REST
        endpoint (still Timbre) if streaming fails before any audio arrived."""
        headers = {**self._headers(), "Content-Type": "application/json", "Accept": "text/event-stream"}
        payload = self._tts_payload(text, voice, language)
        got_audio = False
        try:
            async with self._gate:
                async with self._http.stream("POST", f"{self.base}/api/v1/tts/sse", headers=headers,
                                             json=payload) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        raise _error_from(resp)
                    event = None
                    async for line in resp.aiter_lines():
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            raw = line[5:].strip()
                            try:
                                data = json.loads(raw)
                            except ValueError:
                                continue
                            if event == "error" or data.get("success") is False:
                                raise GnaniError(data.get("message", "Timbre streaming error"), code="TTS_STREAM")
                            chunk = data.get("audio")
                            if chunk:
                                got_audio = True
                                yield base64.b64decode(chunk)
                            if data.get("is_final") or event == "complete":
                                return
        except (GnaniError, httpx.HTTPError) as e:
            if got_audio or isinstance(e, GnaniNotConfigured):
                raise
            if isinstance(e, GnaniError) and e.code in ("INVALID_API_KEY", "MISSING_API_KEY", "SCOPE_NOT_ALLOWED"):
                raise
            log.warning("Timbre SSE failed (%s); falling back to Timbre REST", e)
            yield await self.synthesize(text, voice, language)

    async def synthesize(self, text: str, voice: str, language: str) -> bytes:
        headers = {**self._headers(), "Content-Type": "application/json"}
        payload = self._tts_payload(text, voice, language)

        async def call():
            return await self._http.post(f"{self.base}/api/v1/tts/inference", headers=headers, json=payload)

        try:
            resp = await self._with_retry(call)
        except httpx.HTTPError as e:
            raise GnaniError(f"Could not reach Gnani Timbre: {e}", code="NETWORK") from e
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("audio"):
            raise _error_from(resp)
        return resp.content

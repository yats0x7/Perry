"""Spoken replies via Gnani Timbre, delivered as short-lived signed audio URLs.

The phone's <audio> element cannot send auth headers, so each reply gets an HMAC-signed
URL valid for 15 minutes. On first request the MP3 is streamed from Timbre's SSE API
straight through to the phone (playback starts on the first chunk) and cached for replay.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from ..config import Settings
from .gnani import GnaniClient

URL_TTL_S = 15 * 60


@dataclass
class SpeechEntry:
    text: str
    voice: str
    language: str
    created: float
    audio: bytes | None = None


class SpeechService:
    def __init__(self, gnani: GnaniClient, settings: Settings):
        self.gnani = gnani
        self.s = settings
        self.secret = settings.resolved_secret()
        self.entries: dict[str, SpeechEntry] = {}

    def voice_for(self, style: str) -> tuple[str, str]:
        if style == "english":
            return self.s.gnani_tts_voice_en, "en-IN"
        return self.s.gnani_tts_voice, self.s.gnani_tts_language  # Hinglish (also used for Hindi input)

    def _sig(self, sid: str, exp: int) -> str:
        return hmac.new(self.secret, f"{sid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def verify(self, sid: str, exp: int, sig: str) -> bool:
        return exp > time.time() and hmac.compare_digest(self._sig(sid, exp), sig) and sid in self.entries

    def prepare(self, text: str, style: str) -> dict:
        if not self.gnani.configured:
            return {"status": "unavailable", "reason": "GNANI_API_KEY is not configured on the server."}
        self._gc()
        voice, lang = self.voice_for(style)
        sid = uuid.uuid4().hex
        self.entries[sid] = SpeechEntry(text=text[:1500], voice=voice, language=lang, created=time.time())
        exp = int(time.time()) + URL_TTL_S
        return {"status": "ready", "url": f"/api/speech/{sid}?exp={exp}&sig={self._sig(sid, exp)}",
                "voice": voice, "language": lang, "model": self.gnani.tts_model}

    async def stream(self, sid: str) -> AsyncIterator[bytes]:
        e = self.entries[sid]
        if e.audio is not None:
            yield e.audio
            return
        buf = bytearray()
        async for chunk in self.gnani.synthesize_stream(e.text, e.voice, e.language):
            buf += chunk
            yield chunk
        e.audio = bytes(buf)

    def _gc(self) -> None:
        cutoff = time.time() - URL_TTL_S
        for k in [k for k, v in self.entries.items() if v.created < cutoff]:
            del self.entries[k]

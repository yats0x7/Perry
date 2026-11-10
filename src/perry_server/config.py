from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Gnani (server-side only; never sent to browsers or desktops) ----
    gnani_api_key: str = ""
    gnani_base_url: str = "https://api.vachana.ai"
    gnani_stt_model: str = "prisma-v2.5"
    gnani_stt_default_language: str = "en-IN"  # en-IN accepts Hindi-English mixed speech, Latin output
    gnani_tts_model: str = "timbre-v2.5"
    gnani_tts_voice: str = "Poorvi"  # Timbre v2.5 Hinglish voice
    gnani_tts_language: str = "hi-en"
    gnani_tts_voice_en: str = "Kaveri"
    gnani_tts_voice_hi: str = "Nalini"

    # ---- reasoning provider ----
    planner: Literal["auto", "rules", "openai_compat"] = "auto"
    # Any OpenAI-compatible endpoint, e.g. a self-hosted Gnani Evon v3.3 behind SGLang.
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gnani/gnani-evon-v3.3-30B-A3B"
    llm_reasoning_effort: str = "low"  # for reasoning models (GPT-5.x / o-series)

    # ---- Spotify catalog search (optional; lets "play <song>" start the exact track) ----
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    # ---- server ----
    public_url: str = ""  # e.g. https://perry.example.com — used in pairing QR codes
    db_path: str = "data/perry.db"
    secret_key: str = ""  # signs short-lived audio URLs; generated & persisted if empty
    approval_mode: Literal["standard", "strict"] = "standard"
    cors_origins: str = ""  # comma separated, only needed when the web app is hosted elsewhere
    web_dist: str = "web/dist"
    pairing_ttl_s: int = 300
    approval_timeout_s: int = 300
    host: str = "127.0.0.1"
    port: int = 8787

    @property
    def gnani_configured(self) -> bool:
        return bool(self.gnani_api_key.strip())

    def resolved_secret(self) -> bytes:
        if self.secret_key:
            return self.secret_key.encode()
        p = Path(self.db_path).with_name("secret.key")
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_text(secrets.token_urlsafe(48))
            p.chmod(0o600)
        return p.read_text().strip().encode()


@lru_cache
def get_settings() -> Settings:
    return Settings()

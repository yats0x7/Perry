"""Local desktop-agent configuration (~/.perry by default, override with PERRY_HOME).

config.json  – user-editable: workspace roots, projects, editor, allowed scripts.
agent.json   – written by `perry-agent pair`: server URL, desktop id, device token (0600).
audit.log    – JSONL record of every tool call this machine executed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field


def perry_home() -> Path:
    home = Path(os.environ.get("PERRY_HOME", Path.home() / ".perry")).expanduser()
    legacy = Path.home() / ".jarvis"  # pre-rename location: carry config + pairing over once
    if "PERRY_HOME" not in os.environ and not home.exists() and legacy.is_dir():
        legacy.rename(home)
    home.mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:
        pass
    return home


class ProjectConfig(BaseModel):
    name: str
    path: str
    aliases: list[str] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return slug(self.name)


class AgentConfig(BaseModel):
    workspace_roots: list[str] = Field(default_factory=list)
    projects: list[ProjectConfig] = Field(default_factory=list)
    editor: str | None = None  # None = auto-detect; "Finder" to just reveal folders
    # Project scripts Perry may run (still each behind user approval).
    allowed_scripts: list[str] = Field(
        default_factory=lambda: ["dev", "start", "serve", "preview", "test", "build", "lint", "typecheck"]
    )
    notes_dir: str = "~/Documents/Perry Notes"
    # Voice-requested shell commands (each one shown verbatim on the phone and approved first).
    terminal_enabled: bool = True
    max_read_bytes: int = 64_000


class Credentials(BaseModel):
    server_url: str
    desktop_id: str
    token: str
    name: str = ""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "project"


def config_path() -> Path:
    return perry_home() / "config.json"


def load_config() -> AgentConfig:
    p = config_path()
    if not p.exists():
        cfg = AgentConfig()
        save_config(cfg)
        return cfg
    return AgentConfig.model_validate_json(p.read_text())


def save_config(cfg: AgentConfig) -> None:
    config_path().write_text(cfg.model_dump_json(indent=2))


def credentials_path() -> Path:
    return perry_home() / "agent.json"


def load_credentials() -> Credentials | None:
    p = credentials_path()
    if not p.exists():
        return None
    return Credentials.model_validate_json(p.read_text())


def save_credentials(c: Credentials) -> None:
    p = credentials_path()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(c.model_dump_json(indent=2))


def clear_credentials() -> None:
    credentials_path().unlink(missing_ok=True)


def audit(event: dict) -> None:
    with (perry_home() / "audit.log").open("a") as f:
        f.write(json.dumps(event, default=str) + "\n")

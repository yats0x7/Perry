"""Outbound, authenticated WebSocket link from the desktop to the Perry server.

The desktop never listens on a port. It dials out, authenticates with its device token
in the first frame (not the URL, so it never lands in proxy logs), advertises its tool
manifest, answers heartbeats and reconnects with jittered exponential backoff.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import websockets
from websockets.asyncio.client import connect

from perry_protocol import PROTOCOL_VERSION, DesktopManifest, ProjectSummary, ToolCall, ToolResult

from . import __version__
from .config import AgentConfig, Credentials, audit, clear_credentials
from .platform import PlatformAdapter, platform_key
from .platform.macos import hostname
from .processes import ProcessManager
from .tools.builtin import _detect_pm, _scripts, build_registry
from .tools.registry import ToolContext, ToolRegistry

log = logging.getLogger("perry.agent")


class Revoked(Exception):
    pass


def build_manifest(cfg: AgentConfig, os_: PlatformAdapter, reg: ToolRegistry) -> DesktopManifest:
    from pathlib import Path

    projects = []
    for p in cfg.projects:
        path = Path(p.path).expanduser()
        scripts = list(_scripts(path))
        projects.append(
            ProjectSummary(
                id=p.id, name=p.name, aliases=p.aliases, path=str(path),
                has_git=(path / ".git").exists(), scripts=scripts,
                package_manager=_detect_pm(path) if scripts else None,
            )
        )
    apps: list[str] = []
    try:
        apps = os_.list_apps() if os_.supported else []
    except Exception:  # noqa: BLE001
        pass
    return DesktopManifest(
        agent_version=__version__,
        platform=platform_key(),  # type: ignore[arg-type]
        platform_version=os_.version() if os_.supported else "",
        hostname=hostname() if os_.supported else "",
        platform_supported=os_.supported,
        tools=reg.specs() if os_.supported else [],
        projects=projects,
        apps=apps,
        editor=cfg.editor or (os_.detect_editor() if os_.supported else None),
    )


class DesktopLink:
    def __init__(self, creds: Credentials, cfg: AgentConfig, os_: PlatformAdapter):
        self.creds = creds
        self.cfg = cfg
        self.os = os_
        self.procs = ProcessManager()
        self.registry = build_registry(cfg, os_, self.procs)
        self.running: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        # Live status for front-ends (the menu-bar app) and a local kill switch.
        self.status: dict = {"state": "connecting", "name": None, "last": None, "error": None}
        self.paused = False

    @property
    def ws_url(self) -> str:
        base = self.creds.server_url.rstrip("/")
        return base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws/desktop"

    async def run_forever(self) -> None:
        backoff = 1.0
        try:
            while True:
                started = time.monotonic()
                try:
                    await self._session()
                except Revoked:
                    log.error("This desktop was revoked from the phone. Credentials removed; pair again.")
                    clear_credentials()
                    self.status.update(state="revoked")
                    return
                except (OSError, websockets.ConnectionClosed, websockets.InvalidStatus, asyncio.TimeoutError) as e:
                    log.warning("connection lost: %s", e)
                    self.status.update(state="offline", error=str(e)[:120])
                if time.monotonic() - started > 30:
                    backoff = 1.0
                delay = backoff * (0.7 + random.random() * 0.6)
                log.info("reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, 30)
        finally:
            self.procs.stop_all()

    async def _session(self) -> None:
        log.info("connecting to %s", self.ws_url)
        async with connect(self.ws_url, ping_interval=20, ping_timeout=20, open_timeout=15, max_size=2**22) as ws:
            manifest = build_manifest(self.cfg, self.os, self.registry)
            await ws.send(json.dumps({
                "type": "hello", "protocol": PROTOCOL_VERSION, "token": self.creds.token,
                "manifest": manifest.model_dump(mode="json"),
            }))
            welcome = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if welcome.get("type") == "revoked":
                raise Revoked()
            if welcome.get("type") != "welcome":
                raise OSError(f"server refused connection: {welcome.get('message', welcome)}")
            self.status.update(state="online", name=welcome.get("name"), error=None)
            log.info("online as '%s' (%s) · %d tools · %d projects",
                     welcome.get("name"), welcome.get("desktop_id"), len(manifest.tools), len(manifest.projects))
            send_lock = asyncio.Lock()

            async def send(obj: dict) -> None:
                async with send_lock:
                    await ws.send(json.dumps(obj))

            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "ping":
                        await send({"type": "pong", "t": msg.get("t")})
                    elif kind == "tool.call":
                        call = ToolCall.model_validate(msg)
                        cancelled = asyncio.Event()
                        task = asyncio.create_task(self._execute(call, cancelled, send))
                        self.running[call.call_id] = (task, cancelled)
                    elif kind == "tool.cancel":
                        entry = self.running.get(msg.get("call_id", ""))
                        if entry:
                            entry[1].set()
                            # give the tool a moment to clean up, then hard-cancel
                            asyncio.get_running_loop().call_later(3, entry[0].cancel)
                    elif kind == "revoked":
                        raise Revoked()
            finally:
                for task, ev in self.running.values():
                    ev.set()
                    task.cancel()
                self.running.clear()

    async def _execute(self, call: ToolCall, cancelled: asyncio.Event, send) -> None:
        async def progress(message: str) -> None:
            await send({"type": "tool.progress", "call_id": call.call_id, "message": message})

        audit({"ts": time.time(), "event": "tool.start", "task_id": call.task_id, "call_id": call.call_id,
               "tool": call.tool, "args": call.args, "approved": call.approved})
        try:
            if self.paused:
                result = ToolResult(call_id=call.call_id, ok=False, error="Perry is paused on this Mac.")
            else:
                result = await self.registry.execute(call, ToolContext(progress=progress, cancelled=cancelled))
        except asyncio.CancelledError:
            result = ToolResult(call_id=call.call_id, ok=False, error="Cancelled.")
        self.status["last"] = (call.tool, result.ok, time.time())
        audit({"ts": time.time(), "event": "tool.end", "call_id": call.call_id, "ok": result.ok,
               "error": result.error, "duration_ms": result.duration_ms})
        log.info("%s %s (%dms)%s", "✓" if result.ok else "✗", call.tool, result.duration_ms,
                 "" if result.ok else f" — {result.error}")
        self.running.pop(call.call_id, None)
        try:
            await send(result.model_dump(mode="json"))
        except websockets.ConnectionClosed:
            log.warning("could not deliver result for %s: connection closed", call.call_id)

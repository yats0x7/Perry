"""Live connection registry: desktop agents and phone/web controllers.

State is in-memory, so run the server as a single process (one uvicorn worker).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import WebSocket

from perry_protocol import DesktopManifest, ToolCall, ToolResult

log = logging.getLogger("perry.hub")

HEARTBEAT_S = 15
STALE_S = 45


@dataclass
class DesktopConn:
    desktop_id: str
    name: str
    ws: WebSocket
    manifest: DesktopManifest
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    pending: dict[str, tuple[asyncio.Future, Callable[[str], Awaitable[None]] | None]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, obj: dict) -> None:
        async with self.lock:
            await self.ws.send_text(json.dumps(obj))


class Hub:
    def __init__(self) -> None:
        self.desktops: dict[str, DesktopConn] = {}
        self.clients: dict[str, set[WebSocket]] = {}
        self._client_locks: dict[int, asyncio.Lock] = {}

    # ---- controllers ---------------------------------------------------------------
    def add_client(self, controller_id: str, ws: WebSocket) -> None:
        self.clients.setdefault(controller_id, set()).add(ws)
        self._client_locks[id(ws)] = asyncio.Lock()

    def remove_client(self, controller_id: str, ws: WebSocket) -> None:
        self.clients.get(controller_id, set()).discard(ws)
        self._client_locks.pop(id(ws), None)

    async def send_client(self, controller_id: str, obj: dict) -> None:
        data = json.dumps(obj, default=str)
        for ws in list(self.clients.get(controller_id, ())):
            lock = self._client_locks.get(id(ws))
            try:
                if lock:
                    async with lock:
                        await ws.send_text(data)
            except Exception:  # noqa: BLE001 — a dead socket is removed by its own handler
                pass

    async def close_clients(self, controller_id: str) -> None:
        for ws in list(self.clients.get(controller_id, ())):
            try:
                await ws.close(code=4401)
            except Exception:  # noqa: BLE001
                pass

    # ---- desktops -------------------------------------------------------------------
    def online(self, desktop_id: str) -> DesktopConn | None:
        return self.desktops.get(desktop_id)

    async def attach_desktop(self, conn: DesktopConn) -> None:
        old = self.desktops.get(conn.desktop_id)
        if old is not None and old.ws is not conn.ws:
            self._fail_pending(old, "Desktop reconnected from another session.")
            try:
                await old.ws.close(code=4000)
            except Exception:  # noqa: BLE001
                pass
        self.desktops[conn.desktop_id] = conn

    def detach_desktop(self, conn: DesktopConn) -> bool:
        if self.desktops.get(conn.desktop_id) is conn:
            del self.desktops[conn.desktop_id]
            self._fail_pending(conn, "Desktop disconnected.")
            return True
        return False

    def _fail_pending(self, conn: DesktopConn, reason: str) -> None:
        for call_id, (fut, _) in list(conn.pending.items()):
            if not fut.done():
                fut.set_result(ToolResult(call_id=call_id, ok=False, error=reason))
        conn.pending.clear()

    async def call_tool(self, desktop_id: str, call: ToolCall,
                        on_progress: Callable[[str], Awaitable[None]] | None = None) -> ToolResult:
        conn = self.desktops.get(desktop_id)
        if conn is None:
            return ToolResult(call_id=call.call_id, ok=False, error="Desktop is offline.")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[call.call_id] = (fut, on_progress)
        try:
            await conn.send(call.model_dump(mode="json"))
            return await asyncio.wait_for(fut, timeout=call.timeout_s + 15)
        except asyncio.TimeoutError:
            await self.cancel_call(desktop_id, call.call_id)
            return ToolResult(call_id=call.call_id, ok=False, error="Desktop did not answer in time.")
        finally:
            conn.pending.pop(call.call_id, None)

    async def cancel_call(self, desktop_id: str, call_id: str) -> None:
        conn = self.desktops.get(desktop_id)
        if conn:
            try:
                await conn.send({"type": "tool.cancel", "call_id": call_id})
            except Exception:  # noqa: BLE001
                pass

    async def on_desktop_message(self, conn: DesktopConn, msg: dict) -> None:
        conn.last_seen = time.time()
        kind = msg.get("type")
        if kind == "tool.result":
            res = ToolResult.model_validate(msg)
            entry = conn.pending.get(res.call_id)
            if entry and not entry[0].done():
                entry[0].set_result(res)
        elif kind == "tool.progress":
            entry = conn.pending.get(msg.get("call_id", ""))
            if entry and entry[1]:
                await entry[1](str(msg.get("message", ""))[:300])

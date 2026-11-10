"""Perry relay server.

Phone (PWA) ──HTTPS/WSS──▶ this server ◀──outbound WSS── desktop agent

Run:  uv run perry-server        (single process: connection state is in-memory)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from perry_protocol import DesktopManifest

from . import __version__
from .agent.catalog import SpotifyCatalog
from .agent.llm_planner import build_planner
from .agent.orchestrator import Orchestrator
from .agent.planner import RulePlanner
from .agent.policy import PolicyEngine
from .auth import AuthService, Controller, PairingError
from .config import Settings, get_settings
from .db import DB
from .hub import HEARTBEAT_S, STALE_S, DesktopConn, Hub
from .voice.gnani import GnaniClient, GnaniError
from .voice.speech import SpeechService

log = logging.getLogger("perry.server")


class SessionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    platform: str = Field(pattern="^(macos|windows|linux)$")
    machine_id: str | None = Field(None, pattern="^[0-9a-f]{16,64}$")

class ConfirmIn(BaseModel):
    approve: bool

class ClaimIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    name: str = Field("Phone", max_length=80)


class State:
    def __init__(self, s: Settings):
        self.settings = s
        self.db = DB(s.db_path)
        self.auth = AuthService(self.db, s.pairing_ttl_s)
        self.hub = Hub()
        self.gnani = GnaniClient(s.gnani_api_key, s.gnani_base_url, stt_model=s.gnani_stt_model,
                                 tts_model=s.gnani_tts_model)
        self.speech = SpeechService(self.gnani, s)
        self.planner = build_planner(s)
        self.spotify = SpotifyCatalog(s.spotify_client_id, s.spotify_client_secret)
        self.orch = Orchestrator(self.db, self.hub, self.speech, PolicyEngine(s.approval_mode),
                                 self.planner, RulePlanner(), s.approval_timeout_s, spotify=self.spotify)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()
    state = State(s)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not s.gnani_configured:
            log.warning("GNANI_API_KEY is not set — voice input/output will report an error until it is.")
        log.info("planner=%s approval_mode=%s db=%s", state.planner.name, s.approval_mode, s.db_path)
        yield
        await state.gnani.aclose()

    app = FastAPI(title="Perry", version=__version__, lifespan=lifespan)
    app.state.perry = state
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",")],
                           allow_methods=["*"], allow_headers=["*"])

    def public_base(request: Request) -> str:
        if s.public_url:
            return s.public_url.rstrip("/")
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc))
        return f"{proto}://{host}"

    def bearer(authorization: str | None) -> str | None:
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return None

    def controller(authorization: str | None = Header(None)) -> Controller:
        c = state.auth.controller_for_token(bearer(authorization))
        if not c:
            raise HTTPException(401, "Not paired or session revoked.")
        return c

    def desktop_view(d: dict) -> dict:
        conn = state.hub.online(d["id"])
        m = conn.manifest if conn else None
        if m is None:
            row = state.db.one("SELECT manifest_json FROM desktops WHERE id=?", (d["id"],))
            if row and row["manifest_json"]:
                m = DesktopManifest.model_validate_json(row["manifest_json"])
        return {
            "id": d["id"], "name": d["name"], "platform": d["platform"], "online": conn is not None,
            "last_seen_at": conn.last_seen if conn else d.get("last_seen_at"),
            "connected_at": conn.connected_at if conn else None,
            "paired_at": d.get("created_at"),
            "platform_supported": m.platform_supported if m else None,
            "projects": [{"id": p.id, "name": p.name, "scripts": p.scripts, "has_git": p.has_git, "package_manager": p.package_manager} for p in m.projects] if m else [],
            "tools": [{"id": t.id, "title": t.title, "risk": t.risk.value} for t in m.tools] if m else [],
            "editor": m.editor if m else None,
            "platform_version": m.platform_version if m else None,
        }

    async def push_desktop_status(desktop_id: str) -> None:
        row = state.db.one("SELECT id, name, platform, last_seen_at FROM desktops WHERE id=?", (desktop_id,))
        if not row:
            return
        view = desktop_view(dict(row))
        for cid in state.auth.controllers_of(desktop_id):
            await state.hub.send_client(cid, {"type": "desktop", "desktop": view})

    # ------------------------------------------------------------------ REST: meta --
    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__, "gnani_configured": s.gnani_configured,
                "stt_model": s.gnani_stt_model, "tts_model": s.gnani_tts_model, "planner": state.planner.name,
                "approval_mode": s.approval_mode, "desktops_online": len(state.hub.desktops),
                "spotify_search": state.spotify.configured}

    # ------------------------------------------------------------------ REST: pairing --
    @app.post("/api/pairing/sessions")
    def pairing_start(body: SessionIn, request: Request):
        ip = request.client.host if request.client else "?"
        if not state.auth.session_limiter.check(ip):
            raise HTTPException(429, "Too many pairing attempts; wait a minute.")
        out = state.auth.create_session(body.name, body.platform, body.machine_id)
        out["pair_url"] = f"{public_base(request)}/pair?code={out['code']}"
        return out

    @app.get("/api/pairing/sessions/{sid}")
    def pairing_poll(sid: str, x_poll_secret: str = Header(...)):
        try:
            return state.auth.session_status(sid, x_poll_secret)
        except PairingError as e:
            raise HTTPException(e.status, str(e))

    @app.post("/api/pairing/sessions/{sid}/confirm")
    async def pairing_confirm(sid: str, body: ConfirmIn, x_poll_secret: str = Header(...)):
        try:
            out = state.auth.confirm(sid, x_poll_secret, body.approve)
        except PairingError as e:
            raise HTTPException(e.status, str(e))
        for old_id in out.pop("replaced", []):
            conn = state.hub.online(old_id)
            if conn:
                try:
                    await conn.send({"type": "revoked", "message": "Replaced by a newer pairing of this computer."})
                    await conn.ws.close(code=4401)
                except Exception:  # noqa: BLE001
                    pass
        return out

    @app.post("/api/pairing/claim")
    def pairing_claim(body: ClaimIn, request: Request, authorization: str | None = Header(None)):
        ip = request.client.host if request.client else "?"
        if not state.auth.claim_limiter.check(ip):
            raise HTTPException(429, "Too many attempts; wait a minute.")
        try:
            return state.auth.claim(body.code, body.name, bearer(authorization))
        except PairingError as e:
            raise HTTPException(e.status, str(e))

    @app.get("/api/pairing/claims/{sid}")
    def pairing_claim_status(sid: str, authorization: str | None = Header(None)):
        tok = bearer(authorization)
        if not tok:
            raise HTTPException(401, "Missing token")
        try:
            return state.auth.claim_status(sid, tok)
        except PairingError as e:
            raise HTTPException(e.status, str(e))

    # ------------------------------------------------------------------ REST: controller --
    @app.get("/api/me")
    def me(c: Controller = Depends(controller)):
        return {"controller": {"id": c.id, "name": c.name},
                "desktops": [desktop_view(d) for d in state.auth.desktops_of(c.id)]}

    @app.delete("/api/desktops/{desktop_id}")
    async def revoke_desktop(desktop_id: str, c: Controller = Depends(controller)):
        if not state.auth.is_paired(c.id, desktop_id):
            raise HTTPException(404, "Unknown desktop")
        revoked = state.auth.revoke(c.id, desktop_id)
        conn = state.hub.online(desktop_id)
        if revoked and conn:
            try:
                await conn.send({"type": "revoked"})
                await conn.ws.close(code=4401)
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "desktop_revoked": revoked}

    @app.post("/api/logout")
    async def logout(c: Controller = Depends(controller)):
        for did in state.auth.sign_out(c.id):
            conn = state.hub.online(did)
            if conn:
                try:
                    await conn.send({"type": "revoked"})
                    await conn.ws.close(code=4401)
                except Exception:  # noqa: BLE001
                    pass
        await state.hub.close_clients(c.id)
        return {"ok": True}

    @app.get("/api/tasks")
    def tasks(limit: int = 30, c: Controller = Depends(controller)):
        return {"tasks": state.orch.history(c.id, min(limit, 100))}

    @app.get("/api/audit")
    def audit(limit: int = 50, c: Controller = Depends(controller)):
        ids = [d["id"] for d in state.auth.desktops_of(c.id)]
        if not ids:
            return {"events": []}
        q = ",".join("?" * len(ids))
        rows = state.db.all(f"SELECT ts, actor, event, desktop_id, task_id, detail_json FROM audit_log "
                            f"WHERE desktop_id IN ({q}) ORDER BY id DESC LIMIT ?", (*ids, min(limit, 200)))
        return {"events": [{**dict(r), "detail": json.loads(r["detail_json"] or "{}")} for r in rows]}

    # ------------------------------------------------------------------ REST: voice --
    @app.post("/api/stt")
    async def stt(audio: UploadFile = File(...), language: str = Form("en-IN"), desktop_id: str | None = Form(None),
                  c: Controller = Depends(controller)):
        data = await audio.read()
        if len(data) < 2000:
            raise HTTPException(400, "Recording is too short.")
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, "Recording is too large (max ~30 s).")
        bias = ["Perry", "git", "status", "server", "development", "project", "start", "kholo", "chalao"]
        conn = state.hub.online(desktop_id) if desktop_id and state.auth.is_paired(c.id, desktop_id) else None
        if conn:
            for p in conn.manifest.projects:
                bias += [p.name, *p.aliases]
        try:
            t = await state.gnani.transcribe(data, audio.filename or "command.wav", language, bias)
        except GnaniError as e:
            return JSONResponse({"error": str(e), "code": e.code}, status_code=e.status)
        state.db.audit(f"controller:{c.id}", "stt", model=t.model, language=t.language, ms=t.latency_ms,
                       request_id=t.request_id, chars=len(t.text))
        return {"text": t.text, "model": t.model, "language": t.language, "request_id": t.request_id,
                "latency_ms": t.latency_ms, "provider": "Gnani Prisma"}

    @app.get("/api/speech/{sid}")
    async def speech(sid: str, exp: int, sig: str):
        if not state.speech.verify(sid, exp, sig):
            raise HTTPException(403, "Audio link expired.")
        gen = state.speech.stream(sid)
        try:
            first = await gen.__anext__()
        except GnaniError as e:
            return JSONResponse({"error": str(e), "code": e.code}, status_code=e.status)
        except StopAsyncIteration:
            raise HTTPException(502, "Timbre returned no audio.")

        async def body():
            yield first
            try:
                async for chunk in gen:
                    yield chunk
            except GnaniError as e:
                log.warning("Timbre stream interrupted: %s", e)

        return StreamingResponse(body(), media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------------ WS: desktop --
    @app.websocket("/ws/desktop")
    async def ws_desktop(ws: WebSocket):
        await ws.accept()
        try:
            hello = json.loads(await asyncio.wait_for(ws.receive_text(), 10))
            d = state.auth.desktop_for_token(hello.get("token"))
            if hello.get("type") != "hello" or d is None:
                await ws.send_text(json.dumps({"type": "revoked", "message": "Unknown or revoked device token."}))
                await ws.close(code=4401)
                return
            manifest = DesktopManifest.model_validate(hello.get("manifest") or {})
        except (asyncio.TimeoutError, ValueError, ValidationError, WebSocketDisconnect):
            await ws.close(code=4400)
            return
        conn = DesktopConn(d.id, d.name, ws, manifest)
        await state.hub.attach_desktop(conn)
        state.db.exec("UPDATE desktops SET last_seen_at=?, manifest_json=? WHERE id=?",
                      (time.time(), manifest.model_dump_json(), d.id))
        state.db.audit("desktop", "desktop.online", desktop_id=d.id, tools=len(manifest.tools))
        await conn.send({"type": "welcome", "desktop_id": d.id, "name": d.name})
        await push_desktop_status(d.id)

        async def heartbeat():
            while True:
                await asyncio.sleep(HEARTBEAT_S)
                if time.time() - conn.last_seen > STALE_S:
                    log.info("desktop %s heartbeat timeout", d.id)
                    await ws.close(code=4408)
                    return
                await conn.send({"type": "ping", "t": time.time()})

        hb = asyncio.create_task(heartbeat())
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                await state.hub.on_desktop_message(conn, msg)
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            hb.cancel()
            if state.hub.detach_desktop(conn):
                state.db.exec("UPDATE desktops SET last_seen_at=? WHERE id=?", (time.time(), d.id))
                state.db.audit("desktop", "desktop.offline", desktop_id=d.id)
                await push_desktop_status(d.id)

    # ------------------------------------------------------------------ WS: controller --
    @app.websocket("/ws/client")
    async def ws_client(ws: WebSocket):
        await ws.accept()
        try:
            first = json.loads(await asyncio.wait_for(ws.receive_text(), 10))
            c = state.auth.controller_for_token(first.get("token")) if first.get("type") == "auth" else None
        except (asyncio.TimeoutError, ValueError, WebSocketDisconnect):
            c = None
        if c is None:
            try:
                await ws.send_text(json.dumps({"type": "unauthorized"}))
                await ws.close(code=4401)
            except Exception:  # noqa: BLE001
                pass
            return
        state.hub.add_client(c.id, ws)

        async def reply(obj: dict) -> None:
            lock = state.hub._client_locks.get(id(ws))
            if lock:
                async with lock:
                    await ws.send_text(json.dumps(obj, default=str))

        await reply({"type": "ready", "controller": {"id": c.id, "name": c.name},
                     "desktops": [desktop_view(d) for d in state.auth.desktops_of(c.id)],
                     "tasks": state.orch.history(c.id, 30), "health": health()})
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                kind = msg.get("type")
                # re-check the token is still valid (revocation takes effect immediately)
                if not state.auth.controller_for_token(first.get("token")):
                    await ws.close(code=4401)
                    return
                if kind == "ping":
                    await reply({"type": "pong"})
                elif kind == "command":
                    did = str(msg.get("desktop_id") or "")
                    text = str(msg.get("text") or "").strip()
                    if not text:
                        continue
                    if not state.auth.is_paired(c.id, did):
                        await reply({"type": "error", "message": "That desktop is not paired with this phone."})
                        continue
                    transcript = msg.get("transcript") if isinstance(msg.get("transcript"), dict) else None
                    await state.orch.submit(c.id, did, text, "voice" if transcript else "text", transcript)
                elif kind in ("approve", "reject"):
                    err = await state.orch.decide(c.id, str(msg.get("task_id")), kind == "approve", msg.get("digest"))
                    if err:
                        await reply({"type": "error", "message": err})
                elif kind == "cancel":
                    err = await state.orch.cancel(c.id, str(msg.get("task_id")))
                    if err:
                        await reply({"type": "error", "message": err})
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            state.hub.remove_client(c.id, ws)

    # ------------------------------------------------------------------ static PWA --
    dist = Path(s.web_dist)
    if dist.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith(("api/", "ws/")):
                raise HTTPException(404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                headers = {"Cache-Control": "no-cache"} if f.name in ("sw.js", "index.html", "manifest.webmanifest") else {}
                return FileResponse(f, headers=headers)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def run() -> None:
    import uvicorn

    s = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    uvicorn.run(create_app(s), host=s.host, port=s.port, proxy_headers=True, forwarded_allow_ips="*",
                ws_ping_interval=20, ws_ping_timeout=20)


app = None  # created lazily by `run()`; tests call create_app()

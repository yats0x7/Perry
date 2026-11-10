"""Pairing, auth, revocation and the WebSocket task loop against the real FastAPI app
(with an in-process fake desktop speaking the real wire protocol)."""

import json

import pytest
from fastapi.testclient import TestClient

from perry_server.config import Settings
from perry_server.main import create_app


@pytest.fixture
def client(tmp_path):
    s = Settings(_env_file=None, db_path=str(tmp_path / "t.db"), gnani_api_key="", web_dist=str(tmp_path / "none"))
    with TestClient(create_app(s)) as c:
        yield c


def pair(client, approve=True):
    s = client.post("/api/pairing/sessions", json={"name": "Test Mac", "platform": "macos"}).json()
    claim = client.post("/api/pairing/claim", json={"code": s["code"].lower().replace("-", ""), "name": "iPhone"}).json()
    hdr = {"X-Poll-Secret": s["poll_secret"]}
    st = client.get(f"/api/pairing/sessions/{s['session_id']}", headers=hdr).json()
    assert st["status"] == "claimed" and st["match_code"] == claim["match_code"]
    conf = client.post(f"/api/pairing/sessions/{s['session_id']}/confirm", headers=hdr, json={"approve": approve}).json()
    return s, claim, conf


def test_pairing_happy_path(client):
    s, claim, conf = pair(client)
    tok = claim["controller_token"]
    assert conf["status"] == "confirmed" and conf["token"].startswith("jdv_")
    me = client.get("/api/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["desktops"][0]["name"] == "Test Mac" and me["desktops"][0]["online"] is False


def test_code_is_single_use(client):
    s, _, _ = pair(client)
    r = client.post("/api/pairing/claim", json={"code": s["code"], "name": "Attacker"})
    assert r.status_code == 404


def test_phone_token_inactive_until_desktop_confirms(client):
    s = client.post("/api/pairing/sessions", json={"name": "Mac", "platform": "macos"}).json()
    claim = client.post("/api/pairing/claim", json={"code": s["code"], "name": "Phone"}).json()
    r = client.get("/api/me", headers={"Authorization": f"Bearer {claim['controller_token']}"})
    assert r.status_code == 401


def test_rejected_pairing_creates_nothing(client):
    _, claim, conf = pair(client, approve=False)
    assert conf["status"] == "rejected"
    assert client.get("/api/me", headers={"Authorization": f"Bearer {claim['controller_token']}"}).status_code == 401


def test_bad_poll_secret(client):
    s = client.post("/api/pairing/sessions", json={"name": "Mac", "platform": "macos"}).json()
    r = client.get(f"/api/pairing/sessions/{s['session_id']}", headers={"X-Poll-Secret": "nope"})
    assert r.status_code == 404


def test_stt_without_key_is_explicit(client):
    _, claim, _ = pair(client)
    r = client.post("/api/stt", headers={"Authorization": f"Bearer {claim['controller_token']}"},
                    files={"audio": ("a.wav", b"RIFF" + b"\0" * 4000, "audio/wav")}, data={"language": "en-IN"})
    assert r.status_code == 503 and r.json()["code"] == "GNANI_NOT_CONFIGURED"


def manifest():
    from perry_agent.config import AgentConfig
    from perry_agent.platform import LinuxAdapter
    from perry_agent.processes import ProcessManager
    from perry_agent.tools.builtin import build_registry

    reg = build_registry(AgentConfig(), LinuxAdapter(), ProcessManager())
    return {"agent_version": "t", "platform": "macos", "tools": [t.model_dump(mode="json") for t in reg.specs()],
            "projects": [{"id": "dineo", "name": "Dineo", "path": "/x", "has_git": True, "scripts": ["dev"]}], "apps": []}


def test_full_task_loop_with_approval_and_revocation(client):
    _, claim, conf = pair(client)
    tok, dtok = claim["controller_token"], conf["token"]
    with client.websocket_connect("/ws/desktop") as desk:
        desk.send_text(json.dumps({"type": "hello", "token": dtok, "manifest": manifest()}))
        assert json.loads(desk.receive_text())["type"] == "welcome"
        with client.websocket_connect("/ws/client") as phone:
            phone.send_text(json.dumps({"type": "auth", "token": tok}))
            ready = json.loads(phone.receive_text())
            assert ready["desktops"][0]["online"]
            did = ready["desktops"][0]["id"]
            phone.send_text(json.dumps({"type": "command", "desktop_id": did,
                                        "text": "Dineo ka git status check karo aur dev server start karo"}))
            task = None
            while not task or task["status"] != "awaiting_approval":
                m = json.loads(phone.receive_text())
                if m["type"] == "task":
                    task = m["task"]
            assert [s["tool"] for s in task["plan"]["steps"]] == ["git.status", "dev.start_server"]
            # a stale digest is refused
            phone.send_text(json.dumps({"type": "approve", "task_id": task["id"], "digest": "bogus"}))
            assert "changed" in json.loads(phone.receive_text())["message"]
            phone.send_text(json.dumps({"type": "approve", "task_id": task["id"], "digest": task["plan_digest"]}))
            def next_call():
                while True:  # the desktop also receives task.state updates for its pet/menu bar
                    m = json.loads(desk.receive_text())
                    if m["type"] != "task.state":
                        return m

            for expected_tool, approved in (("git.status", False), ("dev.start_server", True)):
                call = next_call()
                assert call["type"] == "tool.call" and call["tool"] == expected_tool and call["approved"] is approved
                desk.send_text(json.dumps({"type": "tool.result", "call_id": call["call_id"], "ok": True,
                                           "output": {"branch": "main", "clean": True, "modified": [], "staged": [], "untracked": []}
                                           if expected_tool == "git.status" else
                                           {"status": "running", "url": "http://localhost:3000", "error_lines": []}}))
            while task["status"] not in ("completed", "failed"):
                m = json.loads(phone.receive_text())
                if m["type"] == "task":
                    task = m["task"]
            assert task["status"] == "completed"
            assert "localhost port 3000" in task["response_text"]
            assert task["speech"]["status"] == "unavailable"  # no Gnani key in tests → explicit, no silent fallback
            hist = client.get("/api/tasks", headers={"Authorization": f"Bearer {tok}"}).json()["tasks"]
            assert hist[0]["id"] == task["id"]
            # revoke → desktop is told and its token stops working
            r = client.delete(f"/api/desktops/{did}", headers={"Authorization": f"Bearer {tok}"}).json()
            assert r["desktop_revoked"]
            assert next_call()["type"] in ("revoked", "ping")
    with client.websocket_connect("/ws/desktop") as desk:
        desk.send_text(json.dumps({"type": "hello", "token": dtok, "manifest": manifest()}))
        assert json.loads(desk.receive_text())["type"] == "revoked"


def test_rejecting_runs_nothing(client):
    _, claim, conf = pair(client)
    with client.websocket_connect("/ws/desktop") as desk:
        desk.send_text(json.dumps({"type": "hello", "token": conf["token"], "manifest": manifest()}))
        desk.receive_text()
        with client.websocket_connect("/ws/client") as phone:
            phone.send_text(json.dumps({"type": "auth", "token": claim["controller_token"]}))
            did = json.loads(phone.receive_text())["desktops"][0]["id"]
            phone.send_text(json.dumps({"type": "command", "desktop_id": did, "text": "Dineo ka dev server start karo"}))
            task = None
            while not task or task["status"] != "awaiting_approval":
                m = json.loads(phone.receive_text())
                task = m.get("task", task)
            phone.send_text(json.dumps({"type": "reject", "task_id": task["id"]}))
            while task["status"] != "rejected":
                m = json.loads(phone.receive_text())
                task = m.get("task", task)
            assert all(s["status"] == "rejected" for s in task["plan"]["steps"])
            assert "kuch nahi chalaya" in task["response_text"]


def test_websocket_requires_auth(client):
    with client.websocket_connect("/ws/client") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": "jct_fake"}))
        assert json.loads(ws.receive_text())["type"] == "unauthorized"

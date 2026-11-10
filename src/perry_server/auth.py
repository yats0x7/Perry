"""Device pairing and authentication.

Pairing flow (both sides must agree; same Wi-Fi is never treated as trust):

 1. Desktop: POST /api/pairing/sessions → short-lived one-time code (+ QR) and a
    poll secret only the desktop knows.
 2. Phone:   POST /api/pairing/claim {code} → receives an *inactive* controller token
    and a 2-digit match number. The code is now burned.
 3. Desktop: polls, sees the phone's name and match number, asks its user to confirm.
 4. Desktop: POST …/confirm → server mints the desktop device token (returned only to
    the desktop), activates the phone token and links the two.

All tokens are random 256-bit secrets stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass

from .db import DB

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_code(code: str) -> str:
    c = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{c[:4]}-{c[4:]}" if len(c) == 8 else c


class PairingError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Controller:
    id: str
    name: str
    active: bool


@dataclass
class Desktop:
    id: str
    name: str
    platform: str


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


class AuthService:
    def __init__(self, db: DB, pairing_ttl_s: int = 300):
        self.db = db
        self.ttl = pairing_ttl_s
        self.claim_limiter = RateLimiter(10, 60)
        self.session_limiter = RateLimiter(10, 60)

    # ---- pairing -----------------------------------------------------------------------
    def create_session(self, desktop_name: str, platform: str, machine_id: str | None = None) -> dict:
        sid = uuid.uuid4().hex
        poll_secret = secrets.token_urlsafe(32)
        code = new_code()
        now = time.time()
        self.db.exec(
            "INSERT INTO pairing_sessions(id, code, poll_secret_hash, desktop_name, platform, status, created_at, expires_at,"
            " machine_id) VALUES (?,?,?,?,?,'pending',?,?,?)",
            (sid, code, hash_token(poll_secret), desktop_name[:80], platform, now, now + self.ttl, machine_id),
        )
        self.db.audit("desktop", "pairing.started", session=sid, name=desktop_name)
        return {"session_id": sid, "code": code, "poll_secret": poll_secret, "expires_in": self.ttl}

    def _session(self, sid: str, poll_secret: str):
        row = self.db.one("SELECT * FROM pairing_sessions WHERE id=?", (sid,))
        if not row or not secrets.compare_digest(row["poll_secret_hash"], hash_token(poll_secret)):
            raise PairingError("Unknown pairing session", 404)
        return row

    def _expired(self, row) -> bool:
        return row["status"] in ("pending", "claimed") and time.time() > row["expires_at"]

    def session_status(self, sid: str, poll_secret: str) -> dict:
        row = self._session(sid, poll_secret)
        status = "expired" if self._expired(row) else row["status"]
        return {"status": status, "controller_name": row["controller_name"], "match_code": row["match_code"]}

    def claim(self, code: str, controller_name: str, existing_token: str | None) -> dict:
        row = self.db.one("SELECT * FROM pairing_sessions WHERE code=?", (normalize_code(code),))
        if not row or row["status"] != "pending" or self._expired(row):
            raise PairingError("This pairing code is invalid, expired or already used.", 404)
        controller = self.controller_for_token(existing_token) if existing_token else None
        token = None
        if controller is None:
            cid = uuid.uuid4().hex
            token = new_token("jct")
            self.db.exec(
                "INSERT INTO controllers(id, name, token_hash, active, created_at) VALUES (?,?,?,0,?)",
                (cid, controller_name[:80] or "Phone", hash_token(token), time.time()),
            )
        else:
            cid = controller.id
        match = str(secrets.randbelow(90) + 10)
        cur = self.db.exec(
            "UPDATE pairing_sessions SET status='claimed', controller_id=?, controller_name=?, match_code=?"
            " WHERE id=? AND status='pending'",
            (cid, controller_name[:80] or "Phone", match, row["id"]),
        )
        if cur.rowcount != 1:
            raise PairingError("This pairing code was just used by another device.", 409)
        self.db.audit("controller", "pairing.claimed", session=row["id"], controller=cid)
        return {
            "claim_id": row["id"], "controller_token": token, "match_code": match,
            "desktop_name": row["desktop_name"], "expires_in": max(0, int(row["expires_at"] - time.time())),
        }

    def confirm(self, sid: str, poll_secret: str, approve: bool) -> dict:
        row = self._session(sid, poll_secret)
        if row["status"] != "claimed" or self._expired(row):
            raise PairingError("Nothing to confirm (expired or not claimed yet).", 409)
        if not approve:
            self.db.exec("UPDATE pairing_sessions SET status='rejected' WHERE id=?", (sid,))
            self.db.exec("DELETE FROM controllers WHERE id=? AND active=0", (row["controller_id"],))
            self.db.audit("desktop", "pairing.rejected", session=sid)
            return {"status": "rejected"}
        did = uuid.uuid4().hex
        token = new_token("jdv")
        now = time.time()
        # Same computer paired again by the same phone: retire the old registration (its token is gone
        # from the computer anyway) so the phone never targets a stale agent.
        replaced: list[str] = []
        if row["machine_id"]:
            for old in self.db.all(
                "SELECT d.id FROM desktops d JOIN pairings p ON p.desktop_id=d.id WHERE d.machine_id=? AND p.controller_id=?",
                (row["machine_id"], row["controller_id"]),
            ):
                if self.revoke(row["controller_id"], old["id"]):
                    replaced.append(old["id"])
        self.db.exec(
            "INSERT INTO desktops(id, name, platform, token_hash, created_at, machine_id) VALUES (?,?,?,?,?,?)",
            (did, row["desktop_name"], row["platform"], hash_token(token), now, row["machine_id"]),
        )
        self.db.exec("UPDATE controllers SET active=1 WHERE id=?", (row["controller_id"],))
        self.db.exec(
            "INSERT OR IGNORE INTO pairings(controller_id, desktop_id, created_at) VALUES (?,?,?)",
            (row["controller_id"], did, now),
        )
        self.db.exec("UPDATE pairing_sessions SET status='confirmed', desktop_id=? WHERE id=?", (did, sid))
        self.db.audit("desktop", "pairing.confirmed", desktop_id=did, controller=row["controller_id"])
        return {"status": "confirmed", "desktop_id": did, "token": token, "replaced": replaced}

    def claim_status(self, sid: str, controller_token: str) -> dict:
        row = self.db.one("SELECT * FROM pairing_sessions WHERE id=?", (sid,))
        ctl = self.db.one("SELECT id FROM controllers WHERE token_hash=?", (hash_token(controller_token),))
        if not row or not ctl or row["controller_id"] != ctl["id"]:
            raise PairingError("Unknown claim", 404)
        status = "expired" if self._expired(row) else row["status"]
        return {"status": status, "desktop_id": row["desktop_id"], "desktop_name": row["desktop_name"]}

    # ---- authentication ---------------------------------------------------------------------
    def controller_for_token(self, token: str | None, *, require_active: bool = True) -> Controller | None:
        if not token:
            return None
        row = self.db.one("SELECT * FROM controllers WHERE token_hash=?", (hash_token(token),))
        if not row or (require_active and not row["active"]):
            return None
        self.db.exec("UPDATE controllers SET last_seen_at=? WHERE id=?", (time.time(), row["id"]))
        return Controller(row["id"], row["name"], bool(row["active"]))

    def desktop_for_token(self, token: str | None) -> Desktop | None:
        if not token:
            return None
        row = self.db.one("SELECT * FROM desktops WHERE token_hash=?", (hash_token(token),))
        if not row:
            return None
        return Desktop(row["id"], row["name"], row["platform"])

    def desktops_of(self, controller_id: str) -> list[dict]:
        rows = self.db.all(
            "SELECT d.id, d.name, d.platform, d.last_seen_at, d.created_at FROM desktops d "
            "JOIN pairings p ON p.desktop_id=d.id WHERE p.controller_id=? ORDER BY p.created_at",
            (controller_id,),
        )
        return [dict(r) for r in rows]

    def controllers_of(self, desktop_id: str) -> list[str]:
        return [r["controller_id"] for r in self.db.all("SELECT controller_id FROM pairings WHERE desktop_id=?", (desktop_id,))]

    def is_paired(self, controller_id: str, desktop_id: str) -> bool:
        return self.db.one(
            "SELECT 1 FROM pairings WHERE controller_id=? AND desktop_id=?", (controller_id, desktop_id)
        ) is not None

    def revoke(self, controller_id: str, desktop_id: str) -> bool:
        """Unlink; if no phone is left, delete the desktop (its token stops working).
        Returns True when the desktop itself was revoked."""
        self.db.exec("DELETE FROM pairings WHERE controller_id=? AND desktop_id=?", (controller_id, desktop_id))
        self.db.audit("controller", "desktop.unlinked", desktop_id=desktop_id, controller=controller_id)
        if not self.controllers_of(desktop_id):
            self.db.exec("DELETE FROM desktops WHERE id=?", (desktop_id,))
            self.db.audit("controller", "desktop.revoked", desktop_id=desktop_id)
            return True
        return False

    def sign_out(self, controller_id: str) -> list[str]:
        """Delete a controller. Returns desktops that no longer have any controller."""
        desktops = [d["id"] for d in self.desktops_of(controller_id)]
        orphaned = [d for d in desktops if self.revoke(controller_id, d)]
        self.db.exec("DELETE FROM controllers WHERE id=?", (controller_id,))
        return orphaned

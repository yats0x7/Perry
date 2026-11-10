"""SQLite persistence. One file, one connection guarded by a lock — plenty for a
single-instance relay. Tokens are stored only as SHA-256 hashes."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS controllers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
  active INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, last_seen_at REAL
);
CREATE TABLE IF NOT EXISTS desktops (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
  created_at REAL NOT NULL, last_seen_at REAL, manifest_json TEXT
);
CREATE TABLE IF NOT EXISTS pairings (
  controller_id TEXT NOT NULL REFERENCES controllers(id) ON DELETE CASCADE,
  desktop_id TEXT NOT NULL REFERENCES desktops(id) ON DELETE CASCADE,
  created_at REAL NOT NULL, PRIMARY KEY (controller_id, desktop_id)
);
CREATE TABLE IF NOT EXISTS pairing_sessions (
  id TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, poll_secret_hash TEXT NOT NULL,
  desktop_name TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL,
  controller_id TEXT, controller_name TEXT, match_code TEXT, desktop_id TEXT,
  created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, controller_id TEXT NOT NULL, desktop_id TEXT,
  status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, data_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_by_controller ON tasks(controller_id, created_at DESC);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
  event TEXT NOT NULL, desktop_id TEXT, task_id TEXT, detail_json TEXT
);
"""


class DB:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            legacy = Path(path).with_name("jarvis.db")  # pre-rename database: move it (and WAL files) once
            if not Path(path).exists() and legacy.exists():
                for suffix in ("", "-wal", "-shm"):
                    src = Path(str(legacy) + suffix)
                    if src.exists():
                        src.rename(str(path) + suffix)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        # in-place migrations for databases created by earlier versions
        for table, column in (("desktops", "machine_id TEXT"), ("pairing_sessions", "machine_id TEXT")):
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if column.split()[0] not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        self.lock = threading.Lock()

    def exec(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, params)

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self.lock:
            return self.conn.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def audit(self, actor: str, event: str, *, desktop_id: str | None = None,
              task_id: str | None = None, **detail: Any) -> None:
        self.exec(
            "INSERT INTO audit_log(ts, actor, event, desktop_id, task_id, detail_json) VALUES (?,?,?,?,?,?)",
            (time.time(), actor, event, desktop_id, task_id, json.dumps(detail, default=str)[:20000]),
        )

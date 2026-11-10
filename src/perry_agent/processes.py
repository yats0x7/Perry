"""Supervisor for processes Perry starts (dev servers, test runs).

Processes are spawned from argv lists (no shell), in their own session/process group
so the whole tree can be stopped, with merged output captured into a ring buffer.
Perry can only stop processes it started itself.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|[\w.-]+):\d{2,5}[^\s'\"]*")
ERROR_RE = re.compile(
    r"(\berror\b|\bERR!|\bfailed\b|\bexception\b|traceback|cannot find|module not found|"
    r"unhandled|EADDRINUSE|\bfatal\b|✗|⨯)",
    re.IGNORECASE,
)
READY_RE = re.compile(r"(ready in|ready -|✓ ready|compiled successfully|local:\s|listening on|started server)", re.I)


@dataclass
class ManagedProcess:
    id: str
    project_id: str
    script: str
    argv: list[str]
    cwd: str
    popen: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    lines: deque = field(default_factory=lambda: deque(maxlen=3000))
    url: str | None = None
    ready: bool = False
    exit_code: int | None = None
    _total_lines: int = 0

    @property
    def running(self) -> bool:
        return self.popen.poll() is None

    def snapshot(self, tail: int = 30) -> dict:
        self.exit_code = self.popen.poll()
        lines = list(self.lines)
        return {
            "process_id": self.id,
            "project_id": self.project_id,
            "script": self.script,
            "command": " ".join(self.argv),
            "pid": self.popen.pid,
            "status": "running" if self.exit_code is None else "exited",
            "exit_code": self.exit_code,
            "url": self.url,
            "ready": self.ready,
            "uptime_s": round(time.time() - self.started_at, 1),
            "output_tail": lines[-tail:],
            "error_lines": list(dict.fromkeys(l.strip() for l in lines if ERROR_RE.search(l)))[-15:],
            "total_lines": self._total_lines,
        }


class ProcessManager:
    def __init__(self) -> None:
        self._procs: dict[str, ManagedProcess] = {}
        self._lock = threading.Lock()

    def start(self, project_id: str, script: str, argv: list[str], cwd: str, env: dict | None = None) -> ManagedProcess:
        full_env = {**os.environ, "FORCE_COLOR": "0", "NO_COLOR": "1", "BROWSER": "none", "CI": ""}
        full_env.pop("CI")
        if env:
            full_env.update(env)
        popen = subprocess.Popen(
            argv,
            cwd=cwd,
            env=full_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
            bufsize=1,
            errors="replace",
        )
        mp = ManagedProcess(uuid.uuid4().hex[:10], project_id, script, argv, cwd, popen)
        threading.Thread(target=self._pump, args=(mp,), daemon=True).start()
        with self._lock:
            self._procs[mp.id] = mp
        return mp

    def _pump(self, mp: ManagedProcess) -> None:
        assert mp.popen.stdout is not None
        for raw in mp.popen.stdout:
            line = ANSI.sub("", raw.rstrip("\n"))[:500]
            mp.lines.append(line)
            mp._total_lines += 1
            if mp.url is None:
                m = URL_RE.search(line)
                if m:
                    mp.url = m.group(0).rstrip(".,)")
            if not mp.ready and READY_RE.search(line):
                mp.ready = True
        mp.exit_code = mp.popen.wait()

    def get(self, pid: str) -> ManagedProcess | None:
        return self._procs.get(pid)

    def find(self, project_id: str | None = None, script: str | None = None, running_only=True) -> list[ManagedProcess]:
        out = []
        for p in self._procs.values():
            if running_only and not p.running:
                continue
            if project_id and p.project_id != project_id:
                continue
            if script and p.script != script:
                continue
            out.append(p)
        return sorted(out, key=lambda p: p.started_at, reverse=True)

    def all(self) -> list[ManagedProcess]:
        return sorted(self._procs.values(), key=lambda p: p.started_at, reverse=True)

    def stop(self, mp: ManagedProcess, grace_s: float = 5) -> int | None:
        if not mp.running:
            return mp.popen.poll()
        try:
            os.killpg(mp.popen.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            return mp.popen.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(mp.popen.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return mp.popen.wait(timeout=2)

    def stop_all(self) -> None:
        for p in list(self._procs.values()):
            self.stop(p, grace_s=2)

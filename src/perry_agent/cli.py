"""`perry-agent` command line.

  perry-agent pair --server https://your-perry.example   # show QR, confirm phone, save token
  perry-agent run                                          # connect and execute approved tools
  perry-agent projects add Dineo ~/code/dineo --alias dino
  perry-agent projects scan ~/code                         # auto-add folders with package.json/.git
  perry-agent tools | doctor | unpair
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import platform as _platform
import signal
import sys
import time
from pathlib import Path

import httpx

from .config import (
    Credentials,
    ProjectConfig,
    clear_credentials,
    perry_home,
    load_config,
    load_credentials,
    save_config,
    save_credentials,
)
from .platform import current_adapter, platform_key


def _print_qr(data: str) -> None:
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(data)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:  # noqa: BLE001
        print("(install 'qrcode' to show a QR code)")


def machine_id() -> str:
    """Stable, non-reversible id for this computer (hash of the hardware UUID), so the server
    can replace an older registration of the same machine instead of keeping duplicates."""
    import hashlib
    import subprocess
    import uuid

    raw = ""
    try:
        out = subprocess.run(["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], capture_output=True,
                             text=True, timeout=5).stdout
        raw = next((l.split('"')[-2] for l in out.splitlines() if "IOPlatformUUID" in l), "")
    except Exception:  # noqa: BLE001
        pass
    raw = raw or str(uuid.getnode())
    return hashlib.sha256(("perry:" + raw).encode()).hexdigest()[:32]


class AgentLock:
    """Only one `perry-agent run` per PERRY_HOME (an old agent with stale code/credentials
    would otherwise keep answering for this computer)."""

    def __init__(self) -> None:
        self.path = perry_home() / "agent.lock"
        self.fh = None

    def holder(self) -> int | None:
        import fcntl

        fh = self.path.open("a+")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            txt = fh.read().strip()
            fh.close()
            return int(txt) if txt.isdigit() else -1
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
        return None

    def acquire(self) -> bool:
        import fcntl
        import os

        self.fh = self.path.open("a+")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        self.fh.seek(0)
        self.fh.truncate()
        self.fh.write(str(os.getpid()))
        self.fh.flush()
        return True


def cmd_pair(a: argparse.Namespace) -> int:
    server = a.server.rstrip("/")
    running = AgentLock().holder()
    if running:
        print(f"A Perry agent is already running (pid {running}). Stop it (Ctrl+C in its terminal), pair, "
              "then start `perry-agent run` again so it uses the new pairing.")
        return 1
    os_ = current_adapter()
    from .platform.macos import hostname

    name = a.name or (hostname() if os_.supported else _platform.node())
    with httpx.Client(base_url=server, timeout=15) as c:
        r = c.post("/api/pairing/sessions", json={"name": name, "platform": platform_key(), "machine_id": machine_id()})
        if r.status_code != 200:
            print(f"Server refused pairing: {r.status_code} {r.text}")
            return 1
        s = r.json()
        print("\n  Scan with your phone camera (Android or iPhone) to pair Perry:\n")
        _print_qr(s["pair_url"])
        print(f"\n  Or open {server}/pair and enter code:  {s['code']}")
        print(f"  Code expires in {int(s['expires_in'] // 60)} minutes.\n")
        headers = {"X-Poll-Secret": s["poll_secret"]}
        while True:
            time.sleep(1.5)
            st = c.get(f"/api/pairing/sessions/{s['session_id']}", headers=headers)
            if st.status_code != 200:
                print(f"Pairing failed: {st.text}")
                return 1
            info = st.json()
            if info["status"] == "expired":
                print("Pairing code expired. Run `perry-agent pair` again.")
                return 1
            if info["status"] == "claimed":
                break
        print(f"  Phone \"{info['controller_name']}\" wants to control this computer.")
        print(f"  Its screen should show the number  {info['match_code']}.")
        if a.yes:
            ok = True
        else:
            ok = input("  Does it match, and do you want to allow it? [y/N] ").strip().lower() in ("y", "yes")
        r = c.post(f"/api/pairing/sessions/{s['session_id']}/confirm", headers=headers, json={"approve": ok})
        if not ok:
            print("  Pairing rejected.")
            return 1
        if r.status_code != 200:
            print(f"Confirm failed: {r.text}")
            return 1
        d = r.json()
        save_credentials(Credentials(server_url=server, desktop_id=d["desktop_id"], token=d["token"], name=name))
        print(f"\n  ✓ Paired as '{name}'. Start the agent with:  perry-agent run\n")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    creds = load_credentials()
    if not creds:
        print("Not paired yet. Run: perry-agent pair --server https://<your-perry-server>")
        return 1
    lock = AgentLock()
    if not lock.acquire():
        print(f"Another Perry agent is already running for this computer (pid {lock.holder()}). Stop it first.")
        return 1
    os_ = current_adapter()
    if not os_.supported:
        print(f"Desktop automation is not implemented for {os_.name} yet (macOS only for now).")
        return 1
    cfg = load_config()
    if not cfg.projects:
        print("Tip: no projects configured. Add one: perry-agent projects add <Name> <path>")
    from .connection import DesktopLink

    link = DesktopLink(creds, cfg, os_)
    loop = asyncio.new_event_loop()
    main = loop.create_task(link.run_forever())
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, main.cancel)
    try:
        loop.run_until_complete(main)
    except asyncio.CancelledError:
        print("\nStopping Perry agent; stopping processes it started…")
        link.procs.stop_all()
    return 0


def cmd_projects(a: argparse.Namespace) -> int:
    cfg = load_config()
    if a.action == "list":
        for p in cfg.projects:
            print(f"  {p.name:<24} {p.path}  aliases={p.aliases}")
        if not cfg.projects:
            print("  (none)")
    elif a.action == "add":
        path = Path(a.path).expanduser().resolve()
        if not path.is_dir():
            print(f"Not a folder: {path}")
            return 1
        cfg.projects = [p for p in cfg.projects if p.name.lower() != a.name.lower()]
        cfg.projects.append(ProjectConfig(name=a.name, path=str(path), aliases=a.alias or []))
        if not any(path == Path(r).expanduser().resolve() or Path(r).expanduser().resolve() in path.parents
                   for r in cfg.workspace_roots):
            cfg.workspace_roots.append(str(path))
        save_config(cfg)
        print(f"Added {a.name} → {path}")
    elif a.action == "remove":
        cfg.projects = [p for p in cfg.projects if p.name.lower() != a.name.lower()]
        save_config(cfg)
        print(f"Removed {a.name}")
    elif a.action == "scan":
        root = Path(a.path).expanduser().resolve()
        names = {p.name.lower() for p in cfg.projects}
        added = 0
        for d in sorted(root.iterdir()):
            if d.is_dir() and not d.name.startswith(".") and ((d / "package.json").exists() or (d / ".git").exists()):
                if d.name.lower() not in names:
                    cfg.projects.append(ProjectConfig(name=d.name, path=str(d)))
                    added += 1
        if str(root) not in cfg.workspace_roots:
            cfg.workspace_roots.append(str(root))
        save_config(cfg)
        print(f"Added {added} projects from {root}")
    return 0


def cmd_tools(a: argparse.Namespace) -> int:
    from .processes import ProcessManager
    from .tools.builtin import build_registry

    reg = build_registry(load_config(), current_adapter(), ProcessManager())
    for s in reg.specs():
        print(f"  {s.id:<18} [{s.risk.value:<7}] {s.description}")
    return 0


def cmd_doctor(a: argparse.Namespace) -> int:
    os_ = current_adapter()
    creds = load_credentials()
    cfg = load_config()
    print(f"  platform      {os_.name} {'(supported)' if os_.supported else '(NOT implemented yet)'}")
    print(f"  home          {perry_home()}")
    print(f"  paired        {'yes → ' + creds.server_url if creds else 'no'}")
    print(f"  editor        {cfg.editor or (os_.detect_editor() if os_.supported else None) or 'Finder'}")
    print(f"  workspace     {cfg.workspace_roots}")
    for p in cfg.projects:
        ok = Path(p.path).expanduser().is_dir()
        print(f"  project       {p.name} {'✓' if ok else '✗ missing'} {p.path}")
    return 0


def cmd_unpair(a: argparse.Namespace) -> int:
    clear_credentials()
    print("Local credentials removed. Revoke the desktop on your phone too, if it is still listed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="perry-agent", description="Perry desktop agent")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair", help="pair this computer with your phone")
    p.add_argument("--server", required=True)
    p.add_argument("--name")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt (testing only)")
    p.set_defaults(fn=cmd_pair)
    sub.add_parser("run", help="connect and execute approved tools").set_defaults(fn=cmd_run)
    pr = sub.add_parser("projects", help="manage projects Perry knows about")
    pr.add_argument("action", choices=["list", "add", "remove", "scan"])
    pr.add_argument("name", nargs="?")
    pr.add_argument("path", nargs="?")
    pr.add_argument("--alias", action="append")
    pr.set_defaults(fn=cmd_projects)
    sub.add_parser("tools", help="list available tools").set_defaults(fn=cmd_tools)
    sub.add_parser("doctor", help="show configuration").set_defaults(fn=cmd_doctor)
    sub.add_parser("unpair", help="forget this desktop's credentials").set_defaults(fn=cmd_unpair)
    a = ap.parse_args(argv)
    if a.cmd == "projects":
        if a.action in ("add",) and not (a.name and a.path):
            ap.error("projects add NAME PATH")
        if a.action == "scan":
            a.path = a.path or a.name
            if not a.path:
                ap.error("projects scan PATH")
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

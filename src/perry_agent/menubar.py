"""Perry for the Mac menu bar.

  uv run perry-menubar

Runs the same desktop agent as `perry-agent run`, plus a native menu: connection status, the last
action, a Pause switch that refuses phone commands, the terminal-commands switch, projects, pairing
with the 2-digit confirmation as a native dialog, the activity log, and open-at-login.
"""

from __future__ import annotations

import asyncio
import os
import plistlib
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import rumps

from .config import (
    Credentials,
    ProjectConfig,
    load_config,
    load_credentials,
    perry_home,
    save_config,
    save_credentials,
)
from .platform import current_adapter, platform_key

LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "app.perry.menubar.plist"


def _template_icon() -> str:
    """A small black 'P' on transparent: macOS tints template images for light and dark menu bars."""
    path = perry_home() / "menubar-icon.png"
    if path.exists():
        return str(path)
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (44, 44), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((9, 6, 17, 38), fill=(0, 0, 0, 255))          # stem
    d.pieslice((5, 6, 37, 28), -90, 90, fill=(0, 0, 0, 255))   # bowl
    d.rectangle((9, 6, 21, 28), fill=(0, 0, 0, 255))
    d.pieslice((13, 12, 29, 22), -90, 90, fill=(0, 0, 0, 0))   # counter
    d.rectangle((17, 12, 21, 22), fill=(0, 0, 0, 0))
    d.rectangle((30, 31, 37, 38), fill=(0, 0, 0, 255))         # tally square
    img.save(path)
    return str(path)


class PerryBar(rumps.App):
    def __init__(self) -> None:
        super().__init__("Perry", icon=_template_icon(), template=True, quit_button=None)
        self.cfg = load_config()
        self.link = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.pairing: dict | None = None

        self.status_item = rumps.MenuItem("Starting…")
        self.last_item = rumps.MenuItem("No actions yet")
        self.pause_item = rumps.MenuItem("Pause Perry", callback=self.toggle_pause)
        self.terminal_item = rumps.MenuItem("Allow terminal commands", callback=self.toggle_terminal)
        self.terminal_item.state = int(self.cfg.terminal_enabled)
        self.projects_menu = rumps.MenuItem("Projects")
        self.pet_item = rumps.MenuItem("Show pet", callback=self.toggle_pet)
        self.login_item = rumps.MenuItem("Open at login", callback=self.toggle_login)
        self.login_item.state = int(LAUNCH_AGENT.exists())
        self.menu = [
            self.status_item, self.last_item, None,
            self.pause_item, self.terminal_item, self.pet_item, None,
            self.projects_menu,
            rumps.MenuItem("Pair a phone…", callback=self.pair),
            rumps.MenuItem("Activity log", callback=self.open_log), None,
            self.login_item,
            rumps.MenuItem("Quit Perry", callback=self.quit),
        ]
        self._fill_projects()
        self._start_agent()
        self.pet = None
        self._pet_pref = perry_home() / "pet-visible"
        if not self._pet_pref.exists() or self._pet_pref.read_text().strip() != "0":
            self._show_pet()
        rumps.Timer(self._tick, 0.5).start()

    # ---- pet ------------------------------------------------------------------------------
    def _show_pet(self) -> None:
        if self.pet is None:
            from .pet import PetWindow

            self.pet = PetWindow(on_toggle_pause=lambda: self.toggle_pause(self.pause_item))
        self.pet.show()
        self.pet_item.state = 1
        self._pet_pref.write_text("1")

    def toggle_pet(self, item) -> None:
        if self.pet is not None and self.pet.visible:
            self.pet.hide()
            item.state = 0
            self._pet_pref.write_text("0")
        else:
            self._show_pet()

    # ---- agent ----------------------------------------------------------------------------
    def _start_agent(self) -> None:
        creds = load_credentials()
        if not creds:
            return
        from .connection import DesktopLink

        self.link = DesktopLink(creds, self.cfg, current_adapter())
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=lambda: self.loop.run_until_complete(self.link.run_forever()), daemon=True).start()

    def _restart(self) -> None:
        if self.link:
            self.link.procs.stop_all()
        os.execv(sys.executable, [sys.executable, "-m", "perry_agent.menubar"])

    def _tick(self, _=None) -> None:
        if self.pairing is not None:
            self._pair_tick()
        if self.pet is not None and self.pet.visible:
            from .pet import derive_state

            self.pet.update(derive_state(self.link))
        if self.link is None:
            self.status_item.title = "Not paired · choose “Pair a phone…”"
            self.title = None
            return
        st = self.link.status
        if self.link.paused:
            self.status_item.title = "Paused · phone commands are refused"
        elif st["state"] == "online":
            self.status_item.title = f"On air as {st['name']}"
        elif st["state"] == "revoked":
            self.status_item.title = "This Mac was revoked · pair again"
        elif st["state"] == "offline":
            self.status_item.title = "Offline · reconnecting…"
        else:
            self.status_item.title = "Connecting…"
        if st.get("last"):
            tool, ok, ts = st["last"]
            self.last_item.title = f"Last: {tool} · {'done' if ok else 'failed'} · {time.strftime('%H:%M', time.localtime(ts))}"

    # ---- switches --------------------------------------------------------------------------
    def toggle_pause(self, item) -> None:
        if not self.link:
            return
        self.link.paused = not self.link.paused
        item.state = int(self.link.paused)

    def toggle_terminal(self, item) -> None:
        self.cfg.terminal_enabled = not self.cfg.terminal_enabled
        save_config(self.cfg)
        item.state = int(self.cfg.terminal_enabled)

    def toggle_login(self, item) -> None:
        if LAUNCH_AGENT.exists():
            subprocess.run(["/bin/launchctl", "unload", str(LAUNCH_AGENT)], capture_output=True)
            LAUNCH_AGENT.unlink()
            item.state = 0
            return
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        with LAUNCH_AGENT.open("wb") as f:
            plistlib.dump({
                "Label": "app.perry.menubar",
                "ProgramArguments": [sys.executable, "-m", "perry_agent.menubar"],
                "RunAtLoad": True,
                "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/opt/homebrew/bin")},
                "StandardOutPath": str(perry_home() / "menubar.log"),
                "StandardErrorPath": str(perry_home() / "menubar.log"),
            }, f)
        item.state = 1

    # ---- projects ---------------------------------------------------------------------------
    def _fill_projects(self) -> None:
        if self.projects_menu._menu is not None:  # rumps keeps the NSMenu here once populated
            self.projects_menu.clear()
        for p in self.cfg.projects:
            self.projects_menu.add(rumps.MenuItem(p.name, callback=lambda _, path=p.path: subprocess.run(["/usr/bin/open", path])))
        if self.cfg.projects:
            self.projects_menu.add(None)
        self.projects_menu.add(rumps.MenuItem("Add project folder…", callback=self.add_project))

    def add_project(self, _) -> None:
        r = subprocess.run(["/usr/bin/osascript", "-e", 'POSIX path of (choose folder with prompt "Choose a project folder for Perry")'],
                           capture_output=True, text=True)
        path = r.stdout.strip().rstrip("/")
        if r.returncode != 0 or not path:
            return
        name = Path(path).name
        self.cfg.projects = [p for p in self.cfg.projects if p.name.lower() != name.lower()]
        self.cfg.projects.append(ProjectConfig(name=name, path=path))
        if path not in self.cfg.workspace_roots:
            self.cfg.workspace_roots.append(path)
        save_config(self.cfg)
        rumps.notification("Perry", f"Added {name}", "Your phone sees it after Perry reconnects.")
        self._restart()

    # ---- pairing -------------------------------------------------------------------------------
    def pair(self, _) -> None:
        creds = load_credentials()
        w = rumps.Window("Address of your Perry server (the https://… link your phone opens):", "Pair a phone",
                         default_text=creds.server_url if creds else "https://", ok="Next", cancel="Cancel", dimensions=(340, 24))
        res = w.run()
        server = res.text.strip().rstrip("/")
        if not res.clicked or not server.startswith("http"):
            return
        from .cli import machine_id
        from .platform.macos import hostname

        try:
            r = httpx.post(f"{server}/api/pairing/sessions", timeout=15,
                           json={"name": hostname(), "platform": platform_key(), "machine_id": machine_id()})
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            rumps.alert("Perry", f"Couldn’t reach the server: {e}")
            return
        s = r.json()
        import qrcode

        qr_path = perry_home() / "pair-qr.png"
        qrcode.make(s["pair_url"]).save(qr_path)
        subprocess.run(["/usr/bin/open", str(qr_path)])
        rumps.notification("Perry", f"Pairing code {s['code']}", "Scan the QR with your phone, or type the code.")
        self.pairing = {"server": server, "session": s, "name": hostname(), "asked": False}

    def _pair_tick(self) -> None:
        p = self.pairing
        if not p or p["asked"]:
            return
        s = p["session"]
        try:
            st = httpx.get(f"{p['server']}/api/pairing/sessions/{s['session_id']}",
                           headers={"X-Poll-Secret": s["poll_secret"]}, timeout=5).json()
        except Exception:  # noqa: BLE001
            return
        if st.get("status") == "expired":
            self.pairing = None
            rumps.alert("Perry", "The pairing code expired. Choose “Pair a phone…” again.")
            return
        if st.get("status") != "claimed":
            return
        p["asked"] = True
        ok = rumps.alert(
            "Allow this phone?",
            f"“{st['controller_name']}” wants to control this Mac.\nIts screen should show {st['match_code']}.",
            ok="Allow", cancel="Deny",
        ) == 1
        r = httpx.post(f"{p['server']}/api/pairing/sessions/{s['session_id']}/confirm",
                       headers={"X-Poll-Secret": s["poll_secret"]}, json={"approve": ok}, timeout=15)
        self.pairing = None
        if ok and r.status_code == 200:
            d = r.json()
            save_credentials(Credentials(server_url=p["server"], desktop_id=d["desktop_id"], token=d["token"], name=p["name"]))
            rumps.notification("Perry", "Phone paired", "Perry is restarting with the new pairing.")
            self._restart()

    # ---- misc -----------------------------------------------------------------------------------
    def open_log(self, _) -> None:
        log = perry_home() / "audit.log"
        log.touch(exist_ok=True)
        subprocess.run(["/usr/bin/open", "-a", "Console", str(log)])

    def quit(self, _) -> None:
        if self.link:
            self.link.procs.stop_all()
        rumps.quit_application()


def main() -> int:
    if not current_adapter().supported:
        print("The Perry menu bar app runs on macOS only.")
        return 1
    from .cli import AgentLock

    lock = AgentLock()
    if not lock.acquire():
        rumps.alert("Perry is already running", f"Another Perry agent is running for this Mac (pid {lock.holder()}). "
                                                 "Stop it first (Ctrl+C in its terminal).")
        return 1
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    PerryBar().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""macOS adapter: uses LaunchServices (`open`), AppleScript via `osascript` with argv
(never string-interpolated), and the filesystem. No shell is ever invoked."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

from .base import BrowserTab, PlatformAdapter

APP_DIRS = [
    Path("/Applications"),
    Path("/Applications/Utilities"),
    Path("/System/Applications"),
    Path("/System/Applications/Utilities"),
    Path.home() / "Applications",
]

# Editors in preference order: (display name used by `open -a`, bundle folder)
EDITORS = [
    ("Cursor", "Cursor.app"),
    ("Visual Studio Code", "Visual Studio Code.app"),
    ("Zed", "Zed.app"),
    ("Windsurf", "Windsurf.app"),
    ("PyCharm", "PyCharm.app"),
    ("WebStorm", "WebStorm.app"),
]




def _media_script(app: str) -> str:
    return f'''
on run argv
  set act to item 1 of argv
  tell application "{app}"
    if act is "play" then play
    if act is "pause" then pause
    if act is "toggle" then playpause
    if act is "next" then next track
    if act is "previous" then previous track
    if act is not "status" then delay 0.8
    set t to ""
    set a to ""
    set al to ""
    try
      set t to name of current track
      set a to artist of current track
      set al to album of current track
    end try
    return (player state as string) & tab & t & tab & a & tab & al
  end tell
end run
'''


_MEDIA_SCRIPTS = {"Spotify": _media_script("Spotify"), "Music": _media_script("Music")}

_SPOTIFY_PLAY_URI = '''
on run argv
  set sep to character id 9
  tell application "Spotify"
    play track (item 1 of argv)
    delay 1.2
    set t to ""
    set a to ""
    set al to ""
    try
      set t to name of current track
      set a to artist of current track
      set al to album of current track
    end try
    return (player state as string) & sep & t & sep & a & sep & al
  end tell
end run
'''

# Browsers sharing Chrome's AppleScript dictionary. Tested: Google Chrome, Brave Browser.
CHROMIUM_BROWSERS = ("Google Chrome", "Brave Browser", "Microsoft Edge", "Vivaldi", "Chromium")
SCRIPTABLE_BROWSERS = (*CHROMIUM_BROWSERS, "Safari")


def _chromium_script(app: str) -> str:
    # `app` comes only from CHROMIUM_BROWSERS; user data arrives via argv.
    return f'''
on run argv
  set act to item 1 of argv
  set arg to item 2 of argv
  set extra to ""
  set sep to character id 9
  tell application "{app}"
    if act is "list" then
      set out to ""
      set wi to 0
      repeat with w2 in windows
        set wi to wi + 1
        set ai to active tab index of w2
        set ti to 0
        repeat with t in tabs of w2
          set ti to ti + 1
          set out to out & wi & sep & ti & sep & (ti = ai) & sep & (URL of t) & sep & (title of t) & linefeed
        end repeat
      end repeat
      return out
    end if
    if (count of windows) = 0 then
      if act is "new_tab" or act is "focus" then
        make new window
      else
        error "PERRY_NO_WINDOW"
      end if
    end if
    set w to front window
    if act is "new_tab" then
      if arg is "" then
        make new tab at end of tabs of w
      else
        make new tab at end of tabs of w with properties {{URL:arg}}
      end if
      activate
    else if act is "navigate" then
      set URL of active tab of w to arg
      activate
    else if act is "close_tab" then
      set extra to title of active tab of w
      close active tab of w
    else if act is "reload" then
      reload active tab of w
    else if act is "back" then
      go back active tab of w
    else if act is "forward" then
      go forward active tab of w
    else if act is "next_tab" or act is "previous_tab" then
      set n to count of tabs of w
      set i to active tab index of w
      if act is "next_tab" then
        set i to i + 1
        if i > n then set i to 1
      else
        set i to i - 1
        if i < 1 then set i to n
      end if
      set active tab index of w to i
      activate
    else if act is "switch_tab" then
      set found to false
      repeat with wi in windows
        set k to 0
        repeat with t in tabs of wi
          set k to k + 1
          if ((title of t) contains arg) or ((URL of t) contains arg) then
            set active tab index of wi to k
            set index of wi to 1
            set found to true
            exit repeat
          end if
        end repeat
        if found then exit repeat
      end repeat
      if not found then error "PERRY_NO_MATCH"
      activate
    else if act is "focus" then
      activate
    else if act is "read" or act starts with "media_" then
      set r to execute active tab of w javascript arg
      try
        set extra to r as text
      end try
    end if
    delay 0.5
    try
      set atb to active tab of front window
      return (title of atb) & sep & (URL of atb) & sep & extra
    on error
      return tab & sep & extra
    end try
  end tell
end run
'''


_SAFARI_SCRIPT = '''
on run argv
  set act to item 1 of argv
  set arg to item 2 of argv
  set extra to ""
  set sep to character id 9
  tell application "Safari"
    if act is "list" then
      set out to ""
      set wi to 0
      repeat with w2 in windows
        set wi to wi + 1
        set ai to 0
        try
          set ai to index of current tab of w2
        end try
        set ti to 0
        repeat with t in tabs of w2
          set ti to ti + 1
          set tn to ""
          set tu to ""
          try
            set tn to name of t
            set tu to URL of t
          end try
          set out to out & wi & sep & ti & sep & (ti = ai) & sep & tu & sep & tn & linefeed
        end repeat
      end repeat
      return out
    end if
    if (count of windows) = 0 then
      if act is "new_tab" or act is "focus" then
        make new document
      else
        error "PERRY_NO_WINDOW"
      end if
    end if
    set w to front window
    if act is "new_tab" then
      if arg is "" then
        set nt to make new tab at end of tabs of w
      else
        set nt to make new tab at end of tabs of w with properties {URL:arg}
      end if
      set current tab of w to nt
      activate
    else if act is "navigate" then
      set URL of current tab of w to arg
      activate
    else if act is "close_tab" then
      try
        set extra to name of current tab of w
      end try
      close current tab of w
    else if act is "reload" then
      set URL of current tab of w to (URL of current tab of w)
    else if act is "back" then
      do JavaScript "history.back()" in current tab of w
    else if act is "forward" then
      do JavaScript "history.forward()" in current tab of w
    else if act is "next_tab" or act is "previous_tab" then
      set n to count of tabs of w
      set i to index of current tab of w
      if act is "next_tab" then
        set i to i + 1
        if i > n then set i to 1
      else
        set i to i - 1
        if i < 1 then set i to n
      end if
      set current tab of w to tab i of w
      activate
    else if act is "switch_tab" then
      set found to false
      repeat with wi in windows
        repeat with t in tabs of wi
          set tn to ""
          set tu to ""
          try
            set tn to name of t
            set tu to URL of t
          end try
          if (tn contains arg) or (tu contains arg) then
            set current tab of wi to t
            set index of wi to 1
            set found to true
            exit repeat
          end if
        end repeat
        if found then exit repeat
      end repeat
      if not found then error "PERRY_NO_MATCH"
      activate
    else if act is "focus" then
      activate
    else if act is "read" or act starts with "media_" then
      set r to do JavaScript arg in current tab of w
      try
        set extra to r as text
      end try
    end if
    delay 0.5
    try
      set ct to current tab of front window
      set tn to ""
      set tu to ""
      try
        set tn to name of ct
        set tu to URL of ct
      end try
      return tn & sep & tu & sep & extra
    on error
      return tab & sep & extra
    end try
  end tell
end run
'''

_BROWSER_SCRIPTS = {b: _chromium_script(b) for b in CHROMIUM_BROWSERS} | {"Safari": _SAFARI_SCRIPT}


def _run(argv: list[str], timeout: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


class MacOSAdapter(PlatformAdapter):
    name = "macos"
    supported = True

    def version(self) -> str:
        return platform.mac_ver()[0]

    def list_apps(self) -> list[str]:
        names: set[str] = set()
        for d in APP_DIRS:
            if d.is_dir():
                for p in d.iterdir():
                    if p.suffix == ".app":
                        names.add(p.stem)
        return sorted(names, key=str.lower)

    def open_app(self, app_name: str) -> None:
        r = _run(["/usr/bin/open", "-a", app_name])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"Could not open {app_name}")

    def focus_app(self, app_name: str) -> None:
        r = _run(
            [
                "/usr/bin/osascript",
                "-e",
                "on run argv",
                "-e",
                "tell application (item 1 of argv) to activate",
                "-e",
                "end run",
                app_name,
            ]
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"Could not focus {app_name}")

    def open_url(self, url: str, browser: str | None = None) -> None:
        argv = ["/usr/bin/open", "-a", browser, url] if browser else ["/usr/bin/open", url]
        r = _run(argv)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "Could not open URL")

    def running(self, app: str) -> bool:
        return self._running(app)

    def frontmost_app(self) -> str | None:
        asn = _run(["/usr/bin/lsappinfo", "front"]).stdout.strip()
        if not asn:
            return None
        out = _run(["/usr/bin/lsappinfo", "info", "-only", "name", asn]).stdout
        # formats seen: `"LSDisplayName"="Brave Browser"` or `"Brave Browser" ASN:0x…: (in front)`
        m = re.search(r'"(?:LSDisplayName|name)"\s*=\s*"([^"]+)"', out) or re.match(r'\s*"([^"]+)"\s+ASN:', out)
        return m.group(1) if m else None

    def browser(self, browser: str, action: str, arg: str = "") -> dict:
        script = _BROWSER_SCRIPTS.get(browser)
        if script is None:
            raise RuntimeError(f"{browser} can't be scripted for tab actions (supported: {', '.join(SCRIPTABLE_BROWSERS)}).")
        r = _run(["/usr/bin/osascript", "-e", script, action, arg], timeout=20)
        if r.returncode != 0:
            err = r.stderr.strip()
            if "PERRY_NO_WINDOW" in err:
                raise RuntimeError(f"No {browser} window is open.")
            if "PERRY_NO_MATCH" in err:
                raise RuntimeError(f"No open {browser} tab matches “{arg}”.")
            if "JavaScript" in err and ("turned off" in err or "Allow JavaScript" in err or "enable" in err.lower()):
                where = ("Safari › Settings › Advanced › “Show features for web developers”, then "
                         "Develop › Allow JavaScript from Apple Events" if browser == "Safari"
                         else f"{browser} › View › Developer › Allow JavaScript from Apple Events")
                raise RuntimeError(f"Reading or controlling the page needs JavaScript from Apple Events. Turn it on in {where}.")
            if "-1743" in err or "Not authorized" in err:
                raise RuntimeError(f"macOS blocked control of {browser}. Allow it under System Settings › "
                                   "Privacy & Security › Automation.")
            raise RuntimeError(f"{browser}: {err[:200]}")
        title, url, extra = (r.stdout.rstrip("\n").split("\t", 2) + ["", "", ""])[:3]
        return {"title": title or None, "url": url or None, "extra": extra}

    def play_spotify_uri(self, uri: str) -> dict:
        r = _run(["/usr/bin/osascript", "-e", _SPOTIFY_PLAY_URI, uri], timeout=20)
        if r.returncode != 0:
            raise RuntimeError(f"Spotify: {r.stderr.strip()[:200]}")
        state, track, artist, album = (r.stdout.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
        return {"player": "Spotify", "state": state, "track": track or None, "artist": artist or None, "album": album or None}

    # ---- system controls ----------------------------------------------------------------------
    def volume(self) -> dict:
        out = _run(["/usr/bin/osascript", "-e", "get volume settings"]).stdout
        lvl = re.search(r"output volume:(\d+|missing value)", out)
        muted = re.search(r"output muted:(true|false)", out)
        level = int(lvl.group(1)) if lvl and lvl.group(1).isdigit() else None
        return {"level": level, "muted": bool(muted and muted.group(1) == "true")}

    def set_volume(self, level: int | None = None, muted: bool | None = None) -> dict:
        if level is not None:
            level = max(0, min(100, int(level)))
            _run(["/usr/bin/osascript", "-e", "on run argv", "-e", "set volume output volume ((item 1 of argv) as integer)",
                  "-e", "end run", str(level)])
            if muted is None and level > 0:
                muted = False
        if muted is not None:
            _run(["/usr/bin/osascript", "-e", f"set volume output muted {'true' if muted else 'false'}"])
        return self.volume()

    @staticmethod
    def _display_services():
        import ctypes
        import ctypes.util

        cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))
        ds = ctypes.cdll.LoadLibrary("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices")
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        ds.DisplayServicesGetBrightness.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_float)]
        ds.DisplayServicesSetBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        return ctypes, ds, cg.CGMainDisplayID()

    def brightness(self) -> float | None:
        try:
            ctypes, ds, did = self._display_services()
            v = ctypes.c_float()
            return round(v.value, 3) if ds.DisplayServicesGetBrightness(did, ctypes.byref(v)) == 0 else None
        except OSError:
            return None

    def set_brightness(self, value: float) -> float:
        ctypes, ds, did = self._display_services()
        if ds.DisplayServicesSetBrightness(did, ctypes.c_float(max(0.0, min(1.0, value)))) != 0:
            raise RuntimeError("This display's brightness can't be controlled (external monitors usually can't).")
        import time as _t

        _t.sleep(0.3)
        return self.brightness() or value

    def battery(self) -> dict:
        out = _run(["/usr/bin/pmset", "-g", "batt"]).stdout
        m = re.search(r"(\d+)%;\s*([^;]+);\s*([^\n]*?)\s+present", out)
        source = "AC Power" if "AC Power" in out else "Battery Power" if "Battery Power" in out else None
        if not m:
            return {"present": False, "source": source}
        remaining = m.group(3).strip()
        return {"present": True, "percent": int(m.group(1)), "state": m.group(2).strip(), "source": source,
                "remaining": None if "no estimate" in remaining or not remaining else remaining.split()[0]}

    def dark_mode(self, value: bool | None = None) -> bool:
        script = ("tell application \"System Events\" to tell appearance preferences to "
                  + ("get dark mode" if value is None else f"set dark mode to {'true' if value else 'false'}"))
        r = _run(["/usr/bin/osascript", "-e", script])
        if r.returncode != 0:
            raise RuntimeError(f"{r.stderr.strip()[:160]} — allow control of System Events under Privacy & Security › Automation.")
        if value is not None:
            return value
        return r.stdout.strip() == "true"

    def power(self, action: str) -> None:
        if action == "sleep":
            _run(["/usr/bin/pmset", "sleepnow"])
        elif action == "display_sleep":
            _run(["/usr/bin/pmset", "displaysleepnow"])
        elif action == "lock":
            import ctypes

            try:
                login = ctypes.cdll.LoadLibrary("/System/Library/PrivateFrameworks/login.framework/Versions/Current/login")
                login.SACLockScreenImmediate()
            except (OSError, AttributeError):
                _run(["/usr/bin/pmset", "displaysleepnow"])  # locks when "require password immediately" is set
        elif action in ("restart", "shutdown"):
            verb = "restart" if action == "restart" else "shut down"
            r = _run(["/usr/bin/osascript", "-e", f"tell application \"System Events\" to {verb}"])
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip()[:200])
        else:
            raise RuntimeError(f"Unknown power action {action}")

    def screenshot(self, path: str) -> None:
        r = _run(["/usr/sbin/screencapture", "-x", path], timeout=15)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:200] or "screencapture failed — allow Screen Recording for your terminal.")

    def open_uri(self, uri: str) -> None:
        r = _run(["/usr/bin/open", uri])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or "Could not open link")

    def media(self, player: str, action: str) -> dict:
        script = _MEDIA_SCRIPTS[player]  # fixed per-player script; action is a validated enum
        if action == "status" and not self._running(player):
            return {"player": player, "state": "not running", "track": None, "artist": None, "album": None}
        r = _run(["/usr/bin/osascript", "-e", script, action], timeout=15)
        if r.returncode != 0:
            raise RuntimeError(
                f"{player}: {r.stderr.strip()[:200]} — allow your terminal under System Settings › "
                "Privacy & Security › Automation if macOS asked."
            )
        state, track, artist, album = (r.stdout.rstrip("\n").split("\t") + ["", "", "", ""])[:4]
        return {"player": player, "state": state, "track": track or None, "artist": artist or None, "album": album or None}

    def detect_editor(self) -> str | None:
        for name, bundle in EDITORS:
            for d in (Path("/Applications"), Path.home() / "Applications"):
                if (d / bundle).exists():
                    return name
        return None

    def open_in_editor(self, path: str, editor: str | None) -> str:
        chosen = editor or self.detect_editor()
        if chosen and chosen.lower() != "finder":
            r = _run(["/usr/bin/open", "-a", chosen, path])
            if r.returncode == 0:
                return chosen
        self.reveal_in_file_manager(path)
        return "Finder"

    def reveal_in_file_manager(self, path: str) -> None:
        _run(["/usr/bin/open", path])

    def notify(self, title: str, message: str) -> None:
        _run(
            [
                "/usr/bin/osascript",
                "-e",
                "on run argv",
                "-e",
                "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e",
                "end run",
                title,
                message,
            ]
        )

    def _running(self, app: str) -> bool:
        r = _run(["/usr/bin/pgrep", "-x", app if app != "Google Chrome" else "Google Chrome"])
        return r.returncode == 0

    def browser_tabs(self, browser: str | None = None) -> list[BrowserTab]:
        tabs: list[BrowserTab] = []
        for b in ([browser] if browser else SCRIPTABLE_BROWSERS):
            if not self._running(b):
                continue
            r = _run(["/usr/bin/osascript", "-e", _BROWSER_SCRIPTS[b], "list", ""], timeout=10)
            if r.returncode != 0:
                raise RuntimeError(f"{b}: {r.stderr.strip()[:200]} — allow control under System Settings › "
                                   "Privacy & Security › Automation.")
            for line in r.stdout.splitlines():
                parts = line.split("\t", 4)
                if len(parts) == 5:
                    w, i, active, url, title = parts
                    tabs.append(BrowserTab(b, int(w), int(i), title, url, active == "true"))
        return tabs

def hostname() -> str:
    r = _run(["/usr/sbin/scutil", "--get", "ComputerName"])
    return r.stdout.strip() or os.uname().nodename

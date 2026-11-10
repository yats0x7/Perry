"""Mac system controls and the approval-gated terminal tool."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from perry_protocol import Risk
from perry_protocol.command_guard import check_command

from ..config import AgentConfig
from ..platform import PlatformAdapter
from ..processes import ProcessManager
from .registry import ToolContext, ToolError, ToolRegistry

KEEP_AWAKE = ("system", "keep-awake")


class StatusIn(BaseModel):
    pass


class StatusOut(BaseModel):
    volume: int | None
    muted: bool
    brightness: int | None = Field(None, description="percent")
    battery: dict
    dark_mode: bool | None
    keep_awake: bool
    keep_awake_until: str | None = None


class ControlIn(BaseModel):
    action: Literal["volume_set", "volume_up", "volume_down", "mute", "unmute",
                    "brightness_set", "brightness_up", "brightness_down",
                    "keep_awake", "allow_sleep", "dark_mode_on", "dark_mode_off", "dark_mode_toggle",
                    "display_sleep", "screenshot"]
    value: int | None = Field(None, ge=0, le=100, description="Percent for *_set, step for *_up/_down")
    minutes: int | None = Field(None, ge=1, le=24 * 60, description="keep_awake duration; omit = until told otherwise")


class ControlOut(BaseModel):
    action: str
    volume: int | None = None
    muted: bool | None = None
    brightness: int | None = None
    dark_mode: bool | None = None
    keep_awake: bool | None = None
    keep_awake_until: str | None = None
    path: str | None = None


class PowerIn(BaseModel):
    action: Literal["sleep", "lock", "restart", "shutdown"]


class PowerOut(BaseModel):
    action: str
    done: bool = True


class TerminalIn(BaseModel):
    command: str = Field(min_length=1, max_length=600)
    cwd: str | None = Field(None, max_length=300, description="Project id/name or folder; default: home folder")
    background: bool = Field(False, description="Start as a long-running managed process instead of waiting")
    timeout_s: int = Field(60, ge=1, le=300)


class TerminalOut(BaseModel):
    command: str
    cwd: str
    exit_code: int | None
    output: str = Field("", description="Untrusted command output (last part)")
    truncated: bool = False
    duration_ms: int = 0
    background: bool = False
    process_id: str | None = None


def register_system_tools(reg: ToolRegistry, cfg: AgentConfig, os_: PlatformAdapter, procs: ProcessManager, ws) -> None:
    def keep_awake_state() -> tuple[bool, str | None]:
        running = procs.find(*KEEP_AWAKE)
        if not running:
            return False, None
        mp = running[0]
        until = getattr(mp, "until", None)
        return True, until

    @reg.tool("system.status", title="Mac status", risk=Risk.READ, input_model=StatusIn, output_model=StatusOut,
              description="Read volume, brightness, battery, dark mode and whether the Mac is being kept awake.")
    async def system_status(a: StatusIn, ctx: ToolContext):
        vol = await asyncio.to_thread(os_.volume)
        br = await asyncio.to_thread(os_.brightness)
        batt = await asyncio.to_thread(os_.battery)
        try:
            dark = await asyncio.to_thread(os_.dark_mode)
        except RuntimeError:
            dark = None
        awake, until = keep_awake_state()
        return StatusOut(volume=vol["level"], muted=vol["muted"], brightness=None if br is None else round(br * 100),
                         battery=batt, dark_mode=dark, keep_awake=awake, keep_awake_until=until)

    @reg.tool("system.control", title="Mac control", risk=Risk.LOW, input_model=ControlIn, output_model=ControlOut,
              description="Change volume/mute, screen brightness, dark mode; keep the Mac awake (caffeinate) or let it "
                          "sleep again; put the display to sleep; take a screenshot to the Desktop.")
    async def system_control(a: ControlIn, ctx: ToolContext):
        act = a.action
        if act.startswith("volume") or act in ("mute", "unmute"):
            cur = await asyncio.to_thread(os_.volume)
            level = cur["level"] or 0
            if act == "volume_set":
                if a.value is None:
                    raise ToolError("Say which volume level (0–100).")
                v = await asyncio.to_thread(os_.set_volume, a.value)
            elif act == "volume_up":
                v = await asyncio.to_thread(os_.set_volume, level + (a.value or 15))
            elif act == "volume_down":
                v = await asyncio.to_thread(os_.set_volume, level - (a.value or 15))
            else:
                v = await asyncio.to_thread(os_.set_volume, None, act == "mute")
            return ControlOut(action=act, volume=v["level"], muted=v["muted"])
        if act.startswith("brightness"):
            cur = await asyncio.to_thread(os_.brightness)
            if cur is None:
                raise ToolError("This Mac's display brightness can't be read (external monitors usually can't).")
            if act == "brightness_set":
                if a.value is None:
                    raise ToolError("Say which brightness level (0–100).")
                target = a.value / 100
            else:
                step = (a.value or 15) / 100
                target = cur + step if act == "brightness_up" else cur - step
            try:
                now = await asyncio.to_thread(os_.set_brightness, max(0.02, min(1.0, target)))
            except RuntimeError as e:
                raise ToolError(str(e)) from e
            return ControlOut(action=act, brightness=round(now * 100))
        if act == "keep_awake":
            for mp in procs.find(*KEEP_AWAKE):
                procs.stop(mp)
            argv = ["/usr/bin/caffeinate", "-d", "-i", "-m"] + (["-t", str(a.minutes * 60)] if a.minutes else [])
            mp = procs.start(*KEEP_AWAKE, argv, str(Path.home()))
            until = datetime.fromtimestamp(time.time() + a.minutes * 60).strftime("%H:%M") if a.minutes else None
            mp.until = until  # type: ignore[attr-defined]
            return ControlOut(action=act, keep_awake=True, keep_awake_until=until)
        if act == "allow_sleep":
            for mp in procs.find(*KEEP_AWAKE):
                await asyncio.to_thread(procs.stop, mp)
            return ControlOut(action=act, keep_awake=False)
        if act.startswith("dark_mode"):
            try:
                if act == "dark_mode_toggle":
                    cur = await asyncio.to_thread(os_.dark_mode)
                    val = await asyncio.to_thread(os_.dark_mode, not cur)
                else:
                    val = await asyncio.to_thread(os_.dark_mode, act == "dark_mode_on")
            except RuntimeError as e:
                raise ToolError(str(e)) from e
            return ControlOut(action=act, dark_mode=val)
        if act == "display_sleep":
            await asyncio.to_thread(os_.power, "display_sleep")
            return ControlOut(action=act)
        if act == "screenshot":
            path = Path.home() / "Desktop" / f"Perry screenshot {datetime.now().strftime('%Y-%m-%d at %H.%M.%S')}.png"
            try:
                await asyncio.to_thread(os_.screenshot, str(path))
            except RuntimeError as e:
                raise ToolError(str(e)) from e
            return ControlOut(action=act, path=str(path))
        raise ToolError(f"Unknown action {act}")

    @reg.tool("system.power", title="Sleep / lock / restart", risk=Risk.EXECUTE, input_model=PowerIn, output_model=PowerOut,
              description="Put the Mac to sleep, lock the screen, restart or shut down (always asks for approval). "
                          "Perry goes offline until the Mac is awake again.")
    async def system_power(a: PowerIn, ctx: ToolContext):
        # Reply first, act a moment later, so the result reaches the phone before the network drops.
        async def later():
            await asyncio.sleep(1.5)
            try:
                await asyncio.to_thread(os_.power, a.action)
            except RuntimeError:
                pass

        asyncio.get_running_loop().create_task(later())
        return PowerOut(action=a.action)

    @reg.tool("terminal.run", title="Run terminal command", risk=Risk.EXECUTE, input_model=TerminalIn,
              output_model=TerminalOut,
              description="Run ONE shell command in the user's login shell (zsh) after explicit approval and return its "
                          "output. No sudo, no destructive commands. Use a dedicated tool instead whenever one exists.")
    async def terminal_run(a: TerminalIn, ctx: ToolContext):
        if not cfg.terminal_enabled:
            raise ToolError("Terminal commands are turned off on this Mac (terminal_enabled=false).")
        why = check_command(a.command)
        if why:
            raise ToolError(f"Not running this: {why}.")
        cwd = Path.home()
        if a.cwd:
            try:
                cwd = ws.project_path(a.cwd)
            except ToolError:
                cand = Path(a.cwd).expanduser()
                if not cand.is_dir():
                    raise ToolError(f"Folder not found: {a.cwd}") from None
                cwd = cand.resolve()
        argv = ["/bin/zsh", "-lc", a.command]
        if a.background:
            mp = procs.start("terminal", a.command[:40], argv, str(cwd))
            await asyncio.sleep(2.0)
            snap = mp.snapshot(tail=30)
            return TerminalOut(command=a.command, cwd=str(cwd), exit_code=snap["exit_code"], background=True,
                               process_id=mp.id, output="\n".join(snap["output_tail"]))
        await ctx.progress(f"$ {a.command}")
        started = time.monotonic()

        def run() -> subprocess.CompletedProcess:
            return subprocess.run(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=a.timeout_s, text=True, errors="replace",
                                  env={**os.environ, "NO_COLOR": "1", "TERM": "dumb", "PAGER": "cat", "GIT_PAGER": "cat"})

        try:
            r = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired as e:
            out = (e.output or "") if isinstance(e.output, str) else (e.output or b"").decode(errors="replace")
            return TerminalOut(command=a.command, cwd=str(cwd), exit_code=None, output=(out[-6000:] + "\n…timed out").strip(),
                               truncated=len(out) > 6000, duration_ms=int((time.monotonic() - started) * 1000))
        out = r.stdout or ""
        return TerminalOut(command=a.command, cwd=str(cwd), exit_code=r.returncode, output=out[-6000:],
                           truncated=len(out) > 6000, duration_ms=int((time.monotonic() - started) * 1000))

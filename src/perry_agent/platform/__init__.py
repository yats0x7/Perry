from __future__ import annotations

import sys

from .base import BrowserTab, PlatformAdapter, UnsupportedAdapter


class WindowsAdapter(UnsupportedAdapter):
    """Planned: ShellExecuteW / `start` for apps & URLs, UI Automation for focus,
    toast notifications, Chrome tabs via CDP. Not implemented or tested yet."""

    name = "windows"


class LinuxAdapter(UnsupportedAdapter):
    """Planned: `gtk-launch`/`xdg-open`, D-Bus notifications, wmctrl/X11 focus
    (Wayland focus is compositor-specific). Not implemented or tested yet."""

    name = "linux"


def current_adapter() -> PlatformAdapter:
    if sys.platform == "darwin":
        from .macos import MacOSAdapter

        return MacOSAdapter()
    if sys.platform.startswith("win"):
        return WindowsAdapter()
    return LinuxAdapter()


def platform_key() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


__all__ = [
    "BrowserTab",
    "PlatformAdapter",
    "WindowsAdapter",
    "LinuxAdapter",
    "current_adapter",
    "platform_key",
]

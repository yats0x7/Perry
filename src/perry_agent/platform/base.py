"""Platform adapter interface.

Tools never call OS-specific APIs directly; they go through a `PlatformAdapter`.
Only `MacOSAdapter` is implemented and tested. Windows and Linux adapters exist so the
interface is designed against three OSes, but they report `supported = False` and
raise `NotImplementedError` rather than pretending to work.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class BrowserTab:
    browser: str
    window: int
    index: int
    title: str
    url: str
    active: bool


class PlatformAdapter(abc.ABC):
    name: str = "unknown"
    supported: bool = False

    @abc.abstractmethod
    def version(self) -> str: ...

    @abc.abstractmethod
    def list_apps(self) -> list[str]:
        """Display names of installed GUI applications."""

    @abc.abstractmethod
    def open_app(self, app_name: str) -> None: ...

    @abc.abstractmethod
    def focus_app(self, app_name: str) -> None: ...

    @abc.abstractmethod
    def open_url(self, url: str, browser: str | None = None) -> None:
        """Open a URL in the default browser, or in a specific installed browser."""

    @abc.abstractmethod
    def media(self, player: str, action: str) -> dict:
        """Control a music player (play/pause/toggle/next/previous/status); returns now-playing info."""

    @abc.abstractmethod
    def browser(self, browser: str, action: str, arg: str = "") -> dict:
        """Run a fixed browser action (new_tab, close_tab, reload, back, forward, next_tab,
        previous_tab, switch_tab, focus, read, media_play, media_pause, media_toggle).
        Returns {"title", "url", "extra"} for the active tab afterwards."""

    @abc.abstractmethod
    def frontmost_app(self) -> str | None: ...

    @abc.abstractmethod
    def running(self, app: str) -> bool: ...

    @abc.abstractmethod
    def play_spotify_uri(self, uri: str) -> dict:
        """Start a spotify:track/album/playlist/artist URI in the Spotify app; returns now-playing info."""

    # ---- system controls -------------------------------------------------------------------
    @abc.abstractmethod
    def volume(self) -> dict:
        """{"level": 0-100, "muted": bool}"""

    @abc.abstractmethod
    def set_volume(self, level: int | None = None, muted: bool | None = None) -> dict: ...

    @abc.abstractmethod
    def brightness(self) -> float | None:
        """0.0-1.0 for the main display, None if unavailable (e.g. external monitor only)."""

    @abc.abstractmethod
    def set_brightness(self, value: float) -> float: ...

    @abc.abstractmethod
    def battery(self) -> dict: ...

    @abc.abstractmethod
    def dark_mode(self, value: bool | None = None) -> bool:
        """Get (value=None) or set dark mode; returns the resulting state."""

    @abc.abstractmethod
    def power(self, action: str) -> None:
        """sleep | display_sleep | lock | restart | shutdown"""

    @abc.abstractmethod
    def screenshot(self, path: str) -> None: ...

    @abc.abstractmethod
    def open_uri(self, uri: str) -> None:
        """Hand an app URI (e.g. spotify:search:…) to the OS."""

    @abc.abstractmethod
    def open_in_editor(self, path: str, editor: str | None) -> str:
        """Open a folder in the code editor; returns the editor actually used."""

    @abc.abstractmethod
    def reveal_in_file_manager(self, path: str) -> None: ...

    @abc.abstractmethod
    def notify(self, title: str, message: str) -> None: ...

    @abc.abstractmethod
    def browser_tabs(self, browser: str | None = None) -> list[BrowserTab]: ...

    @abc.abstractmethod
    def detect_editor(self) -> str | None: ...


class UnsupportedAdapter(PlatformAdapter):
    """Shared base for adapters that are designed but not yet implemented."""

    supported = False

    def _no(self, *_a, **_k):
        raise NotImplementedError(
            f"Perry desktop automation is not implemented for {self.name} yet."
        )

    version = list_apps = open_app = focus_app = open_url = _no  # type: ignore[assignment]
    open_in_editor = reveal_in_file_manager = notify = browser_tabs = _no  # type: ignore[assignment]
    media = open_uri = browser = frontmost_app = running = play_spotify_uri = _no  # type: ignore[assignment]
    volume = set_volume = brightness = set_brightness = battery = dark_mode = power = screenshot = _no  # type: ignore[assignment]

    def detect_editor(self) -> str | None:
        return None

"""Talking to the running Steam client through steam:// URIs."""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable, Sequence

Launcher = Callable[..., object]


def detect_command(which: Callable[[str], str | None] = shutil.which) -> list[str]:
    if which("steam"):
        return ["steam"]
    if which("flatpak"):
        try:
            out = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                                 capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if "com.valvesoftware.Steam" in out:
            return ["flatpak", "run", "com.valvesoftware.Steam"]
    return ["xdg-open"]


class SteamClient:
    def __init__(self, command: Sequence[str] | str | None = None, launcher: Launcher = subprocess.Popen):
        if isinstance(command, str):
            command = command.split() if command else None
        self.command = list(command) if command else detect_command()
        self.launcher = launcher
        # Called after opening a Steam *window* (store, install/uninstall dialog), so the
        # fullscreen launcher can get out of the way instead of hiding it.
        self.on_ui: Callable[[], None] | None = None
        # Called after a game was launched (the launcher should step aside).
        self.on_play: Callable[[int], None] | None = None

    def _ui(self, ok: bool) -> bool:
        if ok and self.on_ui is not None:
            self.on_ui()
        return ok

    def open_uri(self, uri: str) -> bool:
        try:
            self.launcher(
                [*self.command, uri],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return False
        return True

    def play(self, appid: int) -> bool:
        ok = self.open_uri(f"steam://rungameid/{int(appid)}")
        if ok and self.on_play is not None:
            self.on_play(int(appid))
        return ok

    def install(self, appid: int) -> bool:
        return self._ui(self.open_uri(f"steam://install/{int(appid)}"))

    def uninstall(self, appid: int) -> bool:
        return self._ui(self.open_uri(f"steam://uninstall/{int(appid)}"))

    def shutdown(self) -> bool:
        """Ask a running Steam client to exit."""
        if self.command == ["xdg-open"]:
            return False  # no Steam command to talk to
        try:
            self.launcher([*self.command, "-shutdown"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return False
        return True

    def start_silent(self) -> bool:
        """Start Steam minimised to the tray (no window)."""
        if self.command == ["xdg-open"]:
            return False
        try:
            self.launcher([*self.command, "-silent"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return False
        return True

    def open_store(self, appid: int) -> bool:
        return self._ui(self.open_uri(f"steam://store/{int(appid)}"))

"""The Upscaling choice in a game's Options (Windows and Linux games): Off, or how much
smaller the game renders - gamescope scales it up with FSR (system/upscaling)."""

from __future__ import annotations

import shutil
from typing import Callable

from PySide6.QtWidgets import QComboBox, QLabel

from gamingcrypt.system import upscaling

NOTE = ("The game renders smaller and is scaled up to the screen (AMD FSR): more FPS, or less power with an "
        "FPS limit - the picture gets a little softer. From the next start.")
MISSING = "Upscaling needs gamescope (the gaming session's compositor) - it isn't installed."


class UpscaleOption:
    def __init__(self, profiles, appid: int, screen_size: Callable[[], tuple[int, int]],
                 changed: Callable[[], None] | None = None, note: str = NOTE):
        self.profiles, self.appid, self.screen_size, self.changed = profiles, appid, screen_size, changed
        self.text_note = note
        self.combo = QComboBox()
        self.note = QLabel("")
        self.note.setObjectName("cardMeta")
        self.note.setWordWrap(True)
        self.fill()
        self.combo.currentIndexChanged.connect(self._chosen)

    def fill(self) -> None:
        chosen = self.profiles.get(self.appid).get("upscale")
        screen = self.screen_size()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(upscaling.describe(None, screen), None)
        for percent in upscaling.LEVELS:
            self.combo.addItem(upscaling.describe(percent, screen), percent)
        self.combo.setCurrentIndex(max(0, self.combo.findData(chosen)))
        self.combo.blockSignals(False)
        there = shutil.which("gamescope") is not None
        self.combo.setEnabled(there)
        self.note.setText(self.text_note if there else MISSING)

    def _chosen(self, _index: int) -> None:
        self.profiles.set(self.appid, "upscale", self.combo.currentData())
        if self.changed is not None:
            self.changed()

    def facts(self) -> str:
        """For the game's facts: "Renders at 960×600, upscaled with FSR" ("" when off)."""
        percent = self.profiles.get(self.appid).get("upscale")
        if percent not in upscaling.LEVELS:
            return ""
        w, h = upscaling.render_size(self.screen_size(), percent)
        return f"Renders at {w}×{h}, upscaled with FSR"


def screen_size_of(widget) -> tuple[int, int]:
    """The screen the widget is on (the handheld: 1280×800)."""
    window = widget.window() if widget is not None else None
    screen = window.screen() if window is not None else None
    size = screen.size() if screen is not None else None
    return (size.width(), size.height()) if size is not None and size.width() > 0 else (1280, 800)

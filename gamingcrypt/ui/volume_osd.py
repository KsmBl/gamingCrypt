"""Small volume indicator at the top while GamingCrypt is on screen."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui.tasks import run_async

STEP = 5
MAX_STEP = 10


def clamp_step(value) -> int:
    """Volume step from the config: -10..10 (negative = buttons swapped, 0 = off)."""
    try:
        return max(-MAX_STEP, min(MAX_STEP, int(value)))
    except (TypeError, ValueError):
        return STEP
SHOW_MS = 1500


class VolumeOsd(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedSize(360, 72)
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 18, 10)
        self.icon = QLabel("🔊")
        row.addWidget(self.icon)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        row.addWidget(self.bar, 1)
        self.value = QLabel("")
        self.value.setFixedWidth(64)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.value)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_level(self, percent: int | None, muted: bool = False) -> None:
        if percent is not None:
            self.bar.setValue(percent)
            self.value.setText(f"{percent}%")
        self.icon.setText("🔇" if muted or percent == 0 else "🔉" if (percent or 0) < 50 else "🔊")
        if muted:
            self.value.setText("Muted")
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, 24)
        self.raise_()
        self.show()
        self.timer.start(SHOW_MS)


class GameOverlay(QWidget):
    """The volume indicator over a game (no Steam there to show one, e.g. emulators): a
    transparent window that gamescope draws on top as an "external overlay"."""

    def __init__(self, mark_overlay: Callable[[int], bool] | None = None):
        super().__init__(None)
        from gamingcrypt.system import gamescope_ctl

        self.mark_overlay = mark_overlay or gamescope_ctl.set_external_overlay
        self.marked = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.osd = VolumeOsd(self)
        self.osd.timer.timeout.connect(self.hide)

    def show_level(self, percent: int | None, muted: bool = False) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())  # gamescope stretches overlays to the screen anyway
        self.show()
        if not self.marked:
            self.marked = self.mark_overlay(int(self.winId()))
        self.osd.show_level(percent, muted)


class _Bridge(QObject):
    key = Signal(int)


class VolumeController(QObject):
    """Volume buttons -> default output volume (+ the indicator when GamingCrypt is visible)."""

    def __init__(self, audio, osd: VolumeOsd | None = None, parent: QObject | None = None,
                 step: Callable[[], int] = lambda: STEP, game_osd=None,
                 use_game_osd: Callable[[], bool] = lambda: False):
        super().__init__(parent)
        self.audio = audio
        self.game_osd = game_osd  # over a game without Steam's own indicator (see GameOverlay)
        self.use_game_osd = use_game_osd
        self.step = step  # read on every press: the settings slider applies at once
        self.osd = osd
        self.bridge = _Bridge(self)
        self.bridge.key.connect(self.handle)  # key presses arrive from the reader thread

    def handle(self, code: int) -> None:
        audio = self.audio
        if code == e.KEY_MUTE:
            run_async(lambda: (audio.default_volume(), audio.toggle_mute()), self._show_mute, owner=self)
        else:
            step = clamp_step(self.step())
            if step == 0:
                return  # buttons turned off in the settings
            delta = step if code == e.KEY_VOLUMEUP else -step
            run_async(lambda: audio.step_volume(delta), self._show, owner=self)

    def _target(self):
        if self.osd is not None and self.osd.parentWidget().isVisible():
            return self.osd
        if self.game_osd is not None and self.use_game_osd():
            return self.game_osd
        return None

    def _show(self, percent) -> None:
        target = self._target()
        if target is not None and percent is not None:
            target.show_level(percent)

    def _show_mute(self, result) -> None:
        percent, muted = result
        target = self._target()
        if target is not None and muted is not None:
            target.show_level(percent, muted=muted)

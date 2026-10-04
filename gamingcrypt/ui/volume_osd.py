"""Small volume indicator at the top while GamingCrypt is on screen."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui.tasks import run_async

STEP = 5
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


class _Bridge(QObject):
    key = Signal(int)


class VolumeController(QObject):
    """Volume buttons -> default output volume (+ the indicator when GamingCrypt is visible)."""

    def __init__(self, audio, osd: VolumeOsd | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.audio = audio
        self.osd = osd
        self.bridge = _Bridge(self)
        self.bridge.key.connect(self.handle)  # key presses arrive from the reader thread

    def handle(self, code: int) -> None:
        audio = self.audio
        if code == e.KEY_MUTE:
            run_async(lambda: (audio.default_volume(), audio.toggle_mute()), self._show_mute, owner=self)
        else:
            delta = STEP if code == e.KEY_VOLUMEUP else -STEP
            run_async(lambda: audio.step_volume(delta), self._show, owner=self)

    def _show(self, percent) -> None:
        if self.osd is not None and percent is not None and self.osd.parentWidget().isVisible():
            self.osd.show_level(percent)

    def _show_mute(self, result) -> None:
        percent, muted = result
        if self.osd is not None and muted is not None and self.osd.parentWidget().isVisible():
            self.osd.show_level(percent, muted=muted)

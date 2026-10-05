"""Small notifications at the top right: "Download finished: Hades", "Battery 15%" …

They queue up while GamingCrypt is hidden (a game is in front - gamescope shows one
app at a time) and appear one after the other once it's back.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

SHOW_MS = 4000
MAX_QUEUED = 5


class Toasts(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # never in the way
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 20, 12)
        self.icon = QLabel("")
        row.addWidget(self.icon)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        row.addWidget(self.text, 1)
        self.setFixedWidth(440)
        self.queue: deque[tuple[str, str]] = deque(maxlen=MAX_QUEUED)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._next)
        self.shown: list[str] = []  # history (tests, logs)
        self.hide()

    def notify(self, text: str, icon: str = "ℹ") -> None:
        self.queue.append((icon, text))
        if not self.isVisible():
            self._next()

    def flush(self) -> None:
        """The window is visible again: show what came in meanwhile."""
        if not self.isVisible():
            self._next()

    def _next(self) -> None:
        window = self.parentWidget()
        if not self.queue or window is None or not window.isVisible():
            self.hide()
            return
        icon, text = self.queue.popleft()
        self.icon.setText(icon)
        self.text.setText(text)
        self.shown.append(text)
        self.adjustSize()
        self.move(window.width() - self.width() - 24, 96)
        self.raise_()
        self.show()
        self.timer.start(SHOW_MS)

"""After a display change in gaming mode: "Keep this display mode?" - reverts by itself."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button

SECONDS = 15


class DisplayConfirm(QWidget):
    kept = Signal()
    reverted = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("DisplayConfirm { background: rgba(0, 0, 0, 190); }")
        outer = QVBoxLayout(self)
        outer.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(560)
        box = QVBoxLayout(card)
        box.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Keep this display mode?")
        title.setObjectName("section")
        box.addWidget(title)
        self.mode = QLabel("")
        self.mode.setObjectName("detailMeta")
        self.mode.setWordWrap(True)
        box.addWidget(self.mode)
        self.countdown = QLabel("")
        self.countdown.setObjectName("cardTitle")
        box.addWidget(self.countdown)
        row = QHBoxLayout()
        self.keep_button = big_button("Keep", "primary")
        self.keep_button.clicked.connect(self.keep)
        self.revert_button = big_button("Revert")
        self.revert_button.clicked.connect(self.revert)
        row.addWidget(self.keep_button)
        row.addWidget(self.revert_button)
        box.addLayout(row)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()
        self.remaining = SECONDS
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.hide()

    def ask(self, description: str) -> None:
        self.mode.setText(description)
        self.remaining = SECONDS
        self._update()
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.revert_button.setFocus()  # a stray controller press never confirms a broken mode
        self.timer.start(1000)

    def _update(self) -> None:
        self.countdown.setText(f"Reverting in {self.remaining} s")

    def tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self.revert()  # e.g. black screen: nobody could press anything
        else:
            self._update()

    def keep(self) -> None:
        self.timer.stop()
        self.hide()
        self.kept.emit()

    def revert(self) -> None:
        self.timer.stop()
        self.hide()
        self.reverted.emit()

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self.revert()
            return True
        return False

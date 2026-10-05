"""Low battery: warn once per discharge, then put the device to sleep unless told not to.

At 15 % a small notification; at 10 % a full warning in front of everything (also
in front of a game): "Save your game - going to sleep in 2:00", with "Sleep now"
and "Keep playing". Plugging in resets it.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button

NOTICE_PERCENT = 15
WARN_PERCENT = 10
COUNTDOWN_S = 120


class BatteryWarning(QWidget):
    sleep_now = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("BatteryWarning { background: rgba(0, 0, 0, 200); }")
        outer = QVBoxLayout(self)
        outer.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(560)
        box = QVBoxLayout(card)
        box.setContentsMargins(28, 24, 28, 24)
        box.setSpacing(14)
        self.title = QLabel("")
        self.title.setObjectName("section")
        box.addWidget(self.title)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        box.addWidget(self.text)
        row = QHBoxLayout()
        self.sleep_button = big_button("☾  Sleep now", "primary")
        self.keep_button = big_button("Keep playing")
        self.sleep_button.clicked.connect(self._sleep)
        self.keep_button.clicked.connect(self._keep)
        row.addWidget(self.sleep_button)
        row.addWidget(self.keep_button)
        box.addLayout(row)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()
        self.remaining = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.hide()

    def open(self, percent: int) -> None:
        self.title.setText(f"Battery low: {percent} %")
        self.remaining = COUNTDOWN_S
        self._update_text()
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.keep_button.setFocus()  # a stray A press never puts it to sleep
        self.timer.start(1000)

    def _update_text(self) -> None:
        minutes, seconds = divmod(self.remaining, 60)
        self.text.setText(f"Save your game and plug in the charger. Going to sleep in {minutes}:{seconds:02d}.")

    def _tick(self) -> None:
        self.remaining -= 1
        if self.remaining <= 0:
            self._sleep()
            return
        self._update_text()

    def _sleep(self) -> None:
        self.close_warning()
        self.sleep_now.emit()

    def _keep(self) -> None:
        self.close_warning()
        self.dismissed.emit()

    def close_warning(self) -> None:
        self.timer.stop()
        self.hide()

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self._keep()
            return True
        return False


class BatteryMonitor(QObject):
    """Watches the battery for the whole app (lock screen, menus, in-game)."""

    notice = Signal(int)  # 15 %
    warning = Signal(int)  # 10 %

    def __init__(self, reader: Callable, parent: QObject | None = None, interval_ms: int = 5000):
        super().__init__(parent)
        self.reader = reader
        self.noticed = self.warned = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(interval_ms)

    def check(self) -> None:
        try:
            state = self.reader()
        except Exception:  # noqa: BLE001 - never break the app over the battery
            return
        if state is None:
            return
        if state.plugged:
            self.noticed = self.warned = False  # next time it runs low: warn again
            return
        if state.percent <= WARN_PERCENT and not self.warned:
            self.warned = self.noticed = True
            self.warning.emit(state.percent)
        elif state.percent <= NOTICE_PERCENT and not self.noticed:
            self.noticed = True
            self.notice.emit(state.percent)

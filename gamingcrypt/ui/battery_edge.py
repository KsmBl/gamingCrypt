"""Low battery at a glance: a red border around the whole screen and a message at the top right
for a few seconds - at 15 % and again at 5 %, also over a game (gamescope's external overlay,
as for the volume over a game - see volume_osd.GameOverlay)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

SHOW_MS = 10_000
BORDER = 12  # px
RED = "#e5484d"
UNMAP_DELAY_MS = 300  # gamescope keeps an overlay's last picture: drawn empty first


def message(percent: int) -> str:
    return f"Battery at {percent} % - plug in the charger"


class BatteryEdge(QWidget):
    """The border and the message, over whatever is under it (never in the way of a tap)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.card = QFrame(self)
        self.card.setObjectName("batteryAlert")
        self.card.setStyleSheet(f"QFrame#batteryAlert {{ background: {RED}; border-radius: 14px; }}"
                                "QLabel { color: white; font-size: 22px; font-weight: 700; }")
        row = QHBoxLayout(self.card)
        row.setContentsMargins(20, 12, 22, 12)
        self.icon = QLabel("🪫")
        row.addWidget(self.icon)
        self.text = QLabel("")
        row.addWidget(self.text)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dismiss)
        self.on_dismiss: Callable[[], None] | None = None
        self.hide()

    def alert(self, percent: int) -> None:
        self.text.setText(message(percent))
        self.card.adjustSize()
        self.setGeometry(self.parentWidget().rect())
        self.card.move(self.width() - self.card.width() - BORDER - 18, BORDER + 18)
        self.raise_()
        self.show()
        self.timer.start(SHOW_MS)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.card.move(self.width() - self.card.width() - BORDER - 18, BORDER + 18)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        pen = QPen(QColor(RED), BORDER)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        half = BORDER / 2
        painter.drawRect(QRectF(half, half, self.width() - BORDER, self.height() - BORDER))

    def dismiss(self) -> None:
        self.timer.stop()
        self.hide()
        if self.on_dismiss is not None:
            self.on_dismiss()


class GameBatteryEdge(QWidget):
    """The same over a game: a transparent window gamescope draws on top of everything."""

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
        self.edge = BatteryEdge(self)
        self.edge.on_dismiss = self._dismissed

    def alert(self, percent: int) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.show()
        if not self.marked:
            self.marked = self.mark_overlay(int(self.winId()))
        self.edge.alert(percent)

    def _dismissed(self) -> None:
        if self.isVisible():
            self.repaint()  # empty: gamescope would keep drawing the border
            QTimer.singleShot(UNMAP_DELAY_MS, self._unmap)

    def _unmap(self) -> None:
        if not self.edge.isVisible():
            self.hide()

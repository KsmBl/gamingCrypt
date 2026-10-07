"""Full-window loading screen ("Starting <game>…") shown until the game's window is up."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import Cover, load_cover, placeholder_cover
from gamingcrypt.ui.widgets import big_button

COVER_W, COVER_H = 240, 360


class Spinner(QWidget):
    """A rotating arc with a fading tail - runs only while visible."""

    def __init__(self, size: int = 72, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.step)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.timer.start(16)

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self.timer.stop()

    def step(self) -> None:
        self.angle = (self.angle + 6) % 360
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width() * 0.1
        rect = QRectF(width, width, self.width() - 2 * width, self.height() - 2 * width)
        p.setPen(QPen(QColor(theme.SURFACE_HI), width))
        p.drawEllipse(rect)
        gradient = QConicalGradient(rect.center(), -self.angle)
        accent = QColor(theme.ACCENT)
        gradient.setColorAt(0.0, accent)
        faded = QColor(accent)
        faded.setAlpha(0)
        gradient.setColorAt(0.75, faded)
        pen = QPen(gradient, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-self.angle * 16), int(270 * 16))


class LaunchOverlay(QWidget):
    cancelled = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        layout.addStretch()
        self.cover = Cover()
        self.cover.setFixedSize(COVER_W, COVER_H)
        layout.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignCenter)
        self.label = QLabel()
        self.label.setObjectName("title")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.spinner = Spinner()
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        self.phase = QLabel()
        self.phase.setObjectName("cardTitle")
        self.phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.phase)
        hint = QLabel("GamingCrypt steps aside as soon as the game is on screen\nand comes back when you quit it.")
        hint.setObjectName("subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.back_button = big_button("Back to GamingCrypt")
        self.back_button.clicked.connect(self.cancelled.emit)
        layout.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.hide()

    def show_for(self, name: str, appid: int | None = None, service=None, cover=None) -> None:
        """cover: draws the game's picture into a label - cover(label, w, h) - for games that
        aren't Steam's (emulated, Windows, Linux, movies); Steam's come from ``service``."""
        self.label.setText(f"Starting {name}…")
        self.phase.setText("Asking Steam to start the game…")
        self.cover.setPixmap(placeholder_cover(name, COVER_W, COVER_H))
        if cover is not None:
            cover(self.cover, COVER_W, COVER_H)
        elif service is not None and appid is not None:
            load_cover(service, appid, self.cover, COVER_W, COVER_H)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def set_phase(self, text: str) -> None:
        self.phase.setText(text)

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self.cancelled.emit()
            return True
        return False

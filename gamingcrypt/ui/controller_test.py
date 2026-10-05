"""Settings -> Controller -> Controller test: an Xbox-style controller where every button
lights up when pressed, with the value the game receives next to it.

The events are the ones GamingCrypt's virtual controller sends (or the physical one
translated with your mapping) - exactly what a game sees.
"""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import navigator, theme
from gamingcrypt.ui.widgets import big_button

EXIT_HOLD_S = 1.5
# Xbox layout: (id, label, evdev code, position in a 1000 x 620 drawing, radius)
BUTTONS = [
    ("a", "A", e.BTN_SOUTH, (740, 300), 30), ("b", "B", e.BTN_EAST, (805, 235), 30),
    ("x", "X", e.BTN_NORTH, (675, 235), 30), ("y", "Y", e.BTN_WEST, (740, 170), 30),
    ("back", "View", e.BTN_SELECT, (420, 220), 20), ("start", "Menu", e.BTN_START, (580, 220), 20),
    ("guide", "Guide", e.BTN_MODE, (500, 150), 32),
    ("l3", "L3", e.BTN_THUMBL, (260, 235), 0), ("r3", "R3", e.BTN_THUMBR, (620, 360), 0),
    ("lb", "LB", e.BTN_TL, (250, 70), 0), ("rb", "RB", e.BTN_TR, (750, 70), 0),
]
CODE_NAMES = {e.BTN_SOUTH: "BTN_SOUTH", e.BTN_EAST: "BTN_EAST", e.BTN_NORTH: "BTN_NORTH",
              e.BTN_WEST: "BTN_WEST", e.BTN_SELECT: "BTN_SELECT", e.BTN_START: "BTN_START",
              e.BTN_MODE: "BTN_MODE", e.BTN_THUMBL: "BTN_THUMBL", e.BTN_THUMBR: "BTN_THUMBR",
              e.BTN_TL: "BTN_TL", e.BTN_TR: "BTN_TR"}
# value columns next to the drawing: left-hand controls left, right-hand ones right
LEFT_ROWS = ["lt", "lb", "lstick", "l3", "dpad", "back"]
RIGHT_ROWS = ["rt", "rb", "y", "x", "b", "a", "rstick", "r3", "start", "guide"]
WIDTH, HEIGHT, OFFSET = 1500, 620, 250  # drawing size; the controller sits at OFFSET
STICK_MAX = 32767
TRIGGER_MAX = 255


class ControllerState:
    """What's pressed / where the sticks are, from standard (Xbox) events."""

    def __init__(self):
        self.pressed: set[int] = set()
        self.axes: dict[int, int] = {}
        self.hat = [0, 0]

    def feed(self, ev_type: int, code: int, value: int) -> None:
        if ev_type == e.EV_KEY:
            (self.pressed.add if value else self.pressed.discard)(code)
        elif ev_type == e.EV_ABS and code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.hat[code - e.ABS_HAT0X] = value
        elif ev_type == e.EV_ABS:
            self.axes[code] = value

    def stick(self, x_code: int, y_code: int) -> tuple[float, float]:
        return (round(self.axes.get(x_code, 0) / STICK_MAX, 2), round(self.axes.get(y_code, 0) / STICK_MAX, 2))

    def trigger(self, code: int) -> float:
        return round(min(1.0, max(0.0, self.axes.get(code, 0) / TRIGGER_MAX)), 2)

    def dpad(self) -> str:
        names = {(0, -1): "Up", (0, 1): "Down", (-1, 0): "Left", (1, 0): "Right"}
        x, y = self.hat
        parts = [names[(0, y)]] if y else []
        if x:
            parts.append(names[(x, 0)])
        return " + ".join(parts) or "-"


class ControllerSchematic(QWidget):
    def __init__(self, state: ControllerState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.labels: dict[str, str] = {}  # button id -> what it means in the chosen system
        self.setMinimumSize(640, 400)

    def value_text(self, row: str) -> str:
        """Shown next to each control: what the game receives (and what it means in the system)."""
        meaning = self.labels.get(row)
        prefix = f"{meaning}  ·  " if meaning else ""
        s = self.state
        if row == "lstick":
            x, y = s.stick(e.ABS_X, e.ABS_Y)
            return f"{prefix}Left stick  {x:+.2f} {y:+.2f}"
        if row == "rstick":
            x, y = s.stick(e.ABS_RX, e.ABS_RY)
            return f"{prefix}Right stick  {x:+.2f} {y:+.2f}"
        if row in ("lt", "rt"):
            return f"{prefix}{row.upper()}  ABS_{'Z' if row == 'lt' else 'RZ'} {s.trigger(e.ABS_Z if row == 'lt' else e.ABS_RZ):.2f}"
        if row == "dpad":
            return f"{prefix}D-pad  {s.dpad()}"
        button = next(b for b in BUTTONS if b[0] == row)
        return f"{prefix}{button[1]}  {CODE_NAMES[button[2]]}{'  ●' if button[2] in s.pressed else ''}"

    def active(self, row: str) -> bool:
        s = self.state
        if row in ("lstick", "rstick"):
            x, y = s.stick(*((e.ABS_X, e.ABS_Y) if row == "lstick" else (e.ABS_RX, e.ABS_RY)))
            return max(abs(x), abs(y)) > 0.15
        if row in ("lt", "rt"):
            return s.trigger(e.ABS_Z if row == "lt" else e.ABS_RZ) > 0.1
        if row == "dpad":
            return s.hat != [0, 0]
        return next(b for b in BUTTONS if b[0] == row)[2] in s.pressed

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / WIDTH, self.height() / HEIGHT)
        p.translate((self.width() - WIDTH * scale) / 2, (self.height() - HEIGHT * scale) / 2)
        p.scale(scale, scale)
        dim, hi, accent = QColor(theme.SURFACE_HI), QColor(theme.TEXT), QColor(theme.ACCENT)
        font = QFont(self.font())
        font.setPixelSize(24)
        p.setFont(font)
        for rows, x, align in ((LEFT_ROWS, 0, Qt.AlignmentFlag.AlignRight), (RIGHT_ROWS, WIDTH - 330,
                                                                             Qt.AlignmentFlag.AlignLeft)):
            for i, row in enumerate(rows):
                p.setPen(accent if self.active(row) else QColor(theme.TEXT_DIM))
                p.drawText(QRectF(x, 30 + i * 56, 330, 50), align | Qt.AlignmentFlag.AlignVCenter,
                           self.value_text(row))
        p.translate(OFFSET, 0)
        # body
        body = QPainterPath()
        body.addRoundedRect(QRectF(130, 90, 740, 330), 150, 150)
        for grip in (QRectF(150, 260, 230, 300), QRectF(620, 260, 230, 300)):
            ellipse = QPainterPath()
            ellipse.addEllipse(grip)
            body = body.united(ellipse)  # one outline, no seams
        p.setPen(QPen(dim, 4))
        p.setBrush(QColor(theme.SURFACE))
        p.drawPath(body)
        # bumpers + triggers
        for label, rect, code in (("LB", QRectF(170, 50, 170, 34), e.BTN_TL), ("RB", QRectF(660, 50, 170, 34), e.BTN_TR)):
            p.setBrush(accent if code in self.state.pressed else dim)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, 12, 12)
            p.setPen(hi)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        for label, x, code in (("LT", 190, e.ABS_Z), ("RT", 680, e.ABS_RZ)):
            value = self.state.trigger(code)
            rect = QRectF(x, 6, 130, 36)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dim)
            p.drawRoundedRect(rect, 10, 10)
            p.setBrush(accent)
            p.drawRoundedRect(QRectF(x, 6, 130 * value, 36), 10, 10)
            p.setPen(hi)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{label} {value:.2f}")
        # sticks
        for (cx, cy), (xc, yc), click in (((260, 235), (e.ABS_X, e.ABS_Y), e.BTN_THUMBL),
                                          ((620, 360), (e.ABS_RX, e.ABS_RY), e.BTN_THUMBR)):
            x, y = self.state.stick(xc, yc)
            p.setPen(QPen(dim, 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 60, 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent if click in self.state.pressed else hi)
            p.drawEllipse(QPointF(cx + x * 40, cy + y * 40), 24, 24)
            p.setPen(hi)
            p.drawText(QRectF(cx - 90, cy + 66, 180, 30), Qt.AlignmentFlag.AlignCenter, f"{x:+.2f}  {y:+.2f}")
        # d-pad
        cx, cy = 380, 360
        for (dx, dy) in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            active = self.state.hat[0] == dx and dx or self.state.hat[1] == dy and dy
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent if active else dim)
            p.drawRoundedRect(QRectF(cx + dx * 38 - 19, cy + dy * 38 - 19, 38, 38), 6, 6)
        # face, centre and guide buttons
        for button_id, label, code, (x, y), r in BUTTONS:
            if not r:
                continue
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent if code in self.state.pressed else dim)
            p.drawEllipse(QPointF(x, y), r, r)
            p.setPen(hi)
            p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter,
                       label if r >= 30 else label[0])
        p.end()


class ControllerTestPage(QWidget):
    closed = Signal()

    def __init__(self, labels_for: Callable[[str], dict[str, str]] | None = None,
                 systems: list[tuple[str, str]] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = ControllerState()
        self.labels_for = labels_for
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 16)
        top = QHBoxLayout()
        title = QLabel("Controller test")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        self.system_combo = QComboBox()
        self.system_combo.addItem("Plain controller", "")
        for system_id, name in systems or []:
            self.system_combo.addItem(name, system_id)
        self.system_combo.currentIndexChanged.connect(self._system_chosen)
        self.system_combo.setVisible(bool(systems))
        top.addWidget(self.system_combo)
        self.done_button = big_button("Done", "primary")
        self.done_button.clicked.connect(self.finish)
        top.addWidget(self.done_button)
        layout.addLayout(top)
        self.schematic = ControllerSchematic(self.state)
        layout.addWidget(self.schematic, 1)
        hint = QLabel("Press any button. Hold B for 1.5 seconds or tap Done to leave.")
        hint.setObjectName("cardMeta")
        layout.addWidget(hint)
        self._b_down_at: float | None = None
        self.exit_timer = QTimer(self)
        self.exit_timer.setSingleShot(True)
        self.exit_timer.timeout.connect(self.finish)
        self.update_values()

    def _system_chosen(self, _index: int) -> None:
        system = self.system_combo.currentData()
        self.schematic.labels = self.labels_for(system) if system and self.labels_for else {}
        self.update_values()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.on_event not in navigator.LISTENERS:
            navigator.LISTENERS.append(self.on_event)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.on_event in navigator.LISTENERS:
            navigator.LISTENERS.remove(self.on_event)
        self.exit_timer.stop()
        super().hideEvent(event)

    def on_event(self, ev_type: int, code: int, value: int) -> bool:
        self.state.feed(ev_type, code, value)
        if ev_type == e.EV_KEY and code == e.BTN_EAST:
            if value:
                self._b_down_at = time.monotonic()
                self.exit_timer.start(int(EXIT_HOLD_S * 1000))
            else:
                self._b_down_at = None
                self.exit_timer.stop()
        self.update_values()
        self.schematic.update()
        return True  # nothing navigates while testing

    def update_values(self) -> None:
        self.schematic.update()

    def finish(self) -> None:
        self.exit_timer.stop()
        if self.on_event in navigator.LISTENERS:
            navigator.LISTENERS.remove(self.on_event)
        self.closed.emit()

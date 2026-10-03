"""Touch inputs for the unlock secret: PIN pad, password + keyboard, swipe pattern."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from gamingcrypt.ui import theme
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button
from gamingcrypt.unlock import secrets

METHOD_LABELS = {"pin": "PIN", "password": "Password", "pattern": "Swipe pattern", "grid5": "5×5 Pattern"}


class PinPad(QWidget):
    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display = QLineEdit()
        self.display.setReadOnly(True)
        self.display.setEchoMode(QLineEdit.EchoMode.Password)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setFixedWidth(340)
        layout.addWidget(self.display, alignment=Qt.AlignmentFlag.AlignCenter)
        grid = QGridLayout()
        grid.setSpacing(14)
        keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"]
        self.buttons: dict[str, object] = {}
        for i, key in enumerate(keys):
            button = big_button(key, "pinKey")
            if key == "✓":
                button.setObjectName("primary")
                button.setStyleSheet("min-height: 72px; min-width: 96px; font-size: 32px; border-radius: 40px;")
            button.clicked.connect(lambda _=False, k=key: self.press(k))
            self.buttons[key] = button
            grid.addWidget(button, i // 3, i % 3)
        layout.addLayout(grid)

    def press(self, key: str) -> None:
        if key == "⌫":
            self.display.backspace()
        elif key == "✓":
            self.submitted.emit(self.display.text())
        elif len(self.display.text()) < 32:
            self.display.setText(self.display.text() + key)

    def clear(self) -> None:
        self.display.clear()


def between_node(a: int, b: int, size: int = 3) -> int | None:
    """Node lying exactly between ``a`` and ``b`` on the grid (e.g. 0 -> 2 skips 1)."""
    ar, ac = divmod(a, size)
    br, bc = divmod(b, size)
    if (ar + br) % 2 or (ac + bc) % 2:
        return None
    mid = ((ar + br) // 2) * size + (ac + bc) // 2
    return mid if mid not in (a, b) else None


class PatternWidget(QWidget):
    """3x3 swipe pattern. Emits the touched node indices when the finger lifts."""

    pattern_entered = Signal(list)

    SIZE = 3

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.nodes: list[int] = []
        self._cursor: QPointF | None = None
        self._error = False
        # Controller: a cursor over the dots; A adds a dot, Start confirms, B clears.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.pad_cursor = 4

    def gamepad_direction(self, dx: int, dy: int) -> bool:
        row, col = divmod(self.pad_cursor, self.SIZE)
        row, col = row + dy, col + dx
        if not (0 <= row < self.SIZE and 0 <= col < self.SIZE):
            return False  # leave the pattern
        self.pad_cursor = row * self.SIZE + col
        self.update()
        return True

    def gamepad_activate(self) -> bool:
        self._error = False
        self.add_node(self.pad_cursor)
        self.update()
        return True

    def gamepad_start(self) -> bool:
        if self.nodes:
            self.pattern_entered.emit(list(self.nodes))
        return True

    def gamepad_back(self) -> bool:
        if self.nodes:
            self.reset()
            return True
        return False

    # geometry ---------------------------------------------------------------
    def _cell(self) -> float:
        return min(self.width(), self.height()) / self.SIZE

    def node_center(self, index: int) -> QPointF:
        cell = self._cell()
        side = cell * self.SIZE
        ox = (self.width() - side) / 2
        oy = (self.height() - side) / 2
        row, col = divmod(index, self.SIZE)
        return QPointF(ox + (col + 0.5) * cell, oy + (row + 0.5) * cell)

    def node_at(self, pos: QPointF) -> int | None:
        radius = self._cell() * 0.35
        for i in range(self.SIZE * self.SIZE):
            c = self.node_center(i)
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= radius:
                return i
        return None

    # input ------------------------------------------------------------------
    def add_node(self, index: int) -> None:
        if index in self.nodes:
            return
        if self.nodes:
            mid = between_node(self.nodes[-1], index, self.SIZE)
            if mid is not None and mid not in self.nodes:
                self.nodes.append(mid)
        self.nodes.append(index)

    def reset(self, error: bool = False) -> None:
        self.nodes = []
        self._cursor = None
        self._error = error
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        self.reset()
        self._track(event.position())

    def mouseMoveEvent(self, event):  # noqa: N802
        self._track(event.position())

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._cursor = None
        self.update()
        if self.nodes:
            self.pattern_entered.emit(list(self.nodes))

    def _track(self, pos: QPointF) -> None:
        node = self.node_at(pos)
        if node is not None:
            self.add_node(node)
        self._cursor = pos
        self.update()

    # painting -------------------------------------------------------------
    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.DANGER if self._error else theme.ACCENT)
        cell = self._cell()
        if self.nodes:
            painter.setPen(QPen(color, cell * 0.06, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            points = [self.node_center(n) for n in self.nodes]
            if self._cursor is not None:
                points.append(self._cursor)
            for a, b in zip(points, points[1:]):
                painter.drawLine(a, b)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(self.SIZE * self.SIZE):
            active = i in self.nodes
            painter.setBrush(color if active else QColor(theme.SURFACE_HI))
            r = cell * (0.16 if active else 0.11)
            painter.drawEllipse(self.node_center(i), r, r)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.ACCENT_HI), cell * 0.03))
            painter.drawEllipse(self.node_center(self.pad_cursor), cell * 0.24, cell * 0.24)


class DotCanvas(QWidget):
    """Square grid of dots; a tap emits the dot index. Doesn't reveal the tap order."""

    dot_tapped = Signal(int)

    def __init__(self, size: int = 5, parent: QWidget | None = None):
        super().__init__(parent)
        self.size = size
        self.setMinimumSize(400, 400)
        self.flash: int | None = None
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.pad_cursor = (size * size) // 2
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(self._end_flash)

    def _cell(self) -> float:
        return min(self.width(), self.height()) / self.size

    def node_center(self, index: int) -> QPointF:
        cell = self._cell()
        side = cell * self.size
        row, col = divmod(index, self.size)
        return QPointF((self.width() - side) / 2 + (col + 0.5) * cell,
                       (self.height() - side) / 2 + (row + 0.5) * cell)

    def node_at(self, pos: QPointF) -> int | None:
        radius = self._cell() * 0.45
        for i in range(self.size * self.size):
            c = self.node_center(i)
            if math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= radius:
                return i
        return None

    def mousePressEvent(self, event):  # noqa: N802
        node = self.node_at(event.position())
        if node is not None:
            self.flash = node
            self._flash_timer.start(150)
            self.update()
            self.dot_tapped.emit(node)

    def gamepad_direction(self, dx: int, dy: int) -> bool:
        row, col = divmod(self.pad_cursor, self.size)
        row, col = row + dy, col + dx
        if not (0 <= row < self.size and 0 <= col < self.size):
            return False  # e.g. down from the last row -> to the ⌫ / ✓ buttons
        self.pad_cursor = row * self.size + col
        self.update()
        return True

    def gamepad_activate(self) -> bool:
        self.flash = self.pad_cursor
        self._flash_timer.start(150)
        self.update()
        self.dot_tapped.emit(self.pad_cursor)
        return True

    def _end_flash(self) -> None:
        self.flash = None
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        cell = self._cell()
        for i in range(self.size * self.size):
            active = i == self.flash
            painter.setBrush(QColor(theme.ACCENT if active else theme.SURFACE_HI))
            r = cell * (0.3 if active else 0.22)
            painter.drawEllipse(self.node_center(i), r, r)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(theme.ACCENT_HI), cell * 0.04))
            painter.drawEllipse(self.node_center(self.pad_cursor), cell * 0.38, cell * 0.38)


class DotGridPad(QWidget):
    """5x5 dots: tap them in your secret order, then confirm."""

    submitted = Signal(list)

    def __init__(self, size: int = secrets.DOT_GRID_SIZE, parent: QWidget | None = None):
        super().__init__(parent)
        self.nodes: list[int] = []
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display = QLineEdit()
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setFixedWidth(340)
        layout.addWidget(self.display, alignment=Qt.AlignmentFlag.AlignCenter)
        self.canvas = DotCanvas(size)
        self.canvas.dot_tapped.connect(self.press)
        layout.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.back_button = big_button("⌫")
        self.back_button.clicked.connect(self.backspace)
        row.addWidget(self.back_button)
        self.ok_button = big_button("✓", "primary")
        self.ok_button.clicked.connect(lambda: self.submitted.emit(list(self.nodes)))
        row.addWidget(self.ok_button)
        row.addStretch()
        layout.addLayout(row)

    def press(self, index: int) -> None:
        if len(self.nodes) < 64:
            self.nodes.append(index)
        self._update_display()

    def backspace(self) -> None:
        if self.nodes:
            self.nodes.pop()
        self._update_display()

    def clear(self) -> None:
        self.nodes = []
        self._update_display()

    def _update_display(self) -> None:
        self.display.setText("●" * len(self.nodes))


class PasswordEntry(QWidget):
    submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Password")
        self.edit.returnPressed.connect(self._submit)
        row.addWidget(self.edit, 1)
        self.reveal = big_button("👁", checkable=True)
        self.reveal.toggled.connect(
            lambda on: self.edit.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
        )
        row.addWidget(self.reveal)
        layout.addLayout(row)
        self.keyboard = OnScreenKeyboard(self.edit)
        self.keyboard.submitted.connect(self._submit)
        layout.addWidget(self.keyboard)

    def _submit(self) -> None:
        self.submitted.emit(self.edit.text())

    def clear(self) -> None:
        self.edit.clear()


class SecretInput(QWidget):
    """Wraps the input widget for one unlock method and converts it into a secret."""

    secret_entered = Signal(str)
    invalid = Signal(str)

    CONVERTERS = {
        "pin": secrets.pin_to_secret,
        "password": secrets.password_to_secret,
        "pattern": secrets.pattern_to_secret,
        "grid5": secrets.dot_grid_to_secret,
    }

    def __init__(self, method: str, parent: QWidget | None = None):
        super().__init__(parent)
        if method not in self.CONVERTERS:
            method = "password"
        self.method = method
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if method == "pin":
            self.widget = PinPad()
            self.widget.submitted.connect(self.submit)
        elif method == "pattern":
            self.widget = PatternWidget()
            self.widget.pattern_entered.connect(self.submit)
        elif method == "grid5":
            self.widget = DotGridPad()
            self.widget.submitted.connect(self.submit)
        else:
            self.widget = PasswordEntry()
            self.widget.submitted.connect(self.submit)
        layout.addWidget(self.widget)

    def submit(self, raw) -> None:
        try:
            secret = self.CONVERTERS[self.method](raw)
        except secrets.InvalidSecret as exc:
            self.clear(error=True)
            self.invalid.emit(str(exc))
            return
        self.secret_entered.emit(secret)

    def clear(self, error: bool = False) -> None:
        if isinstance(self.widget, PatternWidget):
            self.widget.reset(error=error)
        else:
            self.widget.clear()

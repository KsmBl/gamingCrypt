"""Start screen: unlock the VeraCrypt volume with PIN, password or pattern."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gamingcrypt.ui import theme
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button
from gamingcrypt.unlock import secrets
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker

METHOD_LABELS = {"pin": "PIN", "password": "Password", "pattern": "Pattern"}


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


class LockScreen(QWidget):
    """Emits ``unlocked`` once the volume was mounted successfully."""

    unlocked = Signal()

    def __init__(self, unlocker: VeraCryptUnlocker, methods: list[str] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.unlocker = unlocker
        self.methods = [m for m in (methods or list(METHOD_LABELS)) if m in METHOD_LABELS] or ["pin"]
        self.busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        title = QLabel("🔒 GamingCrypt")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        selector = QHBoxLayout()
        selector.addStretch()
        self.method_buttons = {}
        for method in self.methods:
            button = big_button(METHOD_LABELS[method], checkable=True)
            button.clicked.connect(lambda _=False, m=method: self.select_method(m))
            self.method_buttons[method] = button
            selector.addWidget(button)
        selector.addStretch()
        if len(self.methods) > 1:
            layout.addLayout(selector)

        self.stack = QStackedWidget()
        self.pin_pad = PinPad()
        self.pin_pad.submitted.connect(lambda pin: self._attempt(secrets.pin_to_secret, pin))
        self.password = PasswordEntry()
        self.password.submitted.connect(lambda pw: self._attempt(secrets.password_to_secret, pw))
        self.pattern = PatternWidget()
        self.pattern.pattern_entered.connect(lambda nodes: self._attempt(secrets.pattern_to_secret, nodes))
        self.pages = {"pin": self.pin_pad, "password": self.password, "pattern": self.pattern}
        for method in self.methods:
            self.stack.addWidget(self.pages[method])
        layout.addWidget(self.stack, 1)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.skip_button = big_button("Continue without unlocking")
        self.skip_button.clicked.connect(self.unlocked.emit)
        layout.addWidget(self.skip_button, alignment=Qt.AlignmentFlag.AlignCenter)
        if unlocker.configured:
            self.skip_button.hide()
        else:
            self.set_status("No VeraCrypt volume configured (see config.json)", error=True)

        self.select_method(self.methods[0])

    def select_method(self, method: str) -> None:
        self.current_method = method
        self.stack.setCurrentWidget(self.pages[method])
        for name, button in self.method_buttons.items():
            button.setChecked(name == method)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _attempt(self, convert, raw) -> None:
        if self.busy:
            return
        try:
            secret = convert(raw)
        except secrets.InvalidSecret as exc:
            self._fail(str(exc))
            return
        self.busy = True
        self.set_status("Unlocking…")
        run_async(lambda: self.unlocker.unlock(secret), self._finished, lambda exc: self._finished(UnlockResult(False, str(exc))))

    def _finished(self, result: UnlockResult) -> None:
        self.busy = False
        if result.success:
            self.set_status(result.message)
            self._clear_inputs()
            self.unlocked.emit()
        else:
            self._fail(result.message)

    def _fail(self, message: str) -> None:
        self.set_status(message, error=True)
        self._clear_inputs(error=True)

    def _clear_inputs(self, error: bool = False) -> None:
        self.pin_pad.clear()
        self.password.clear()
        self.pattern.reset(error=error)

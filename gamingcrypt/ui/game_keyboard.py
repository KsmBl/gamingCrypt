"""The on-screen keyboard over a game: typed keys reach the game through a virtual keyboard
(input/virtual_keyboard), the game keeps the focus.

gamescope draws the window as a notification (see gamescope_ctl.set_notification_overlay) -
those take no input, so it's steered with the controller: while it's open the controller goes
to the keyboard, not to the game (Remapper.divert).

Ⓐ types the highlighted key, Ⓑ deletes, Ⓨ is a space, Ⓧ Shift, Menu Enter, View closes it.
Besides letters it has Esc, Tab, Ctrl, Alt, the arrows and (Fn) F1 - F12 for PC games.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.input.virtual_keyboard import VirtualKeyboard
from gamingcrypt.ui.navigator import REPEAT_DELAY_MS, REPEAT_RATE_MS, STICK_PRESS, STICK_RELEASE
from gamingcrypt.ui.widgets import big_button

UNMAP_DELAY_MS = 120  # as the volume indicator's: gamescope keeps an overlay's last picture
PANEL_WIDTH = 1100
STICK_MAX = 32767

TOP = [("Esc", "Esc"), ("Tab", "Tab"), ("Ctrl", "Ctrl"), ("Alt", "Alt"), ("◀", "Left"), ("▲", "Up"),
       ("▼", "Down"), ("▶", "Right"), ("Fn", "Fn")]
LETTERS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
SYMBOLS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|"]
FN = [["F1", "F2", "F3", "F4", "F5", "F6"], ["F7", "F8", "F9", "F10", "F11", "F12"],
      ["Home", "End", "PgUp", "PgDn", "Ins", "Del"]]
HINT = "Ⓐ Type     Ⓑ Delete     Ⓨ Space     Ⓧ Shift     Menu  Enter     View  Close"


def _forget(listener) -> None:
    from gamingcrypt.ui import navigator

    if listener in navigator.LISTENERS:
        navigator.LISTENERS.remove(listener)


class _Bridge(QObject):
    event = Signal(int, int, int)


class GameKeyboard(QWidget):
    closed = Signal()

    def __init__(self, sink: VirtualKeyboard | None = None,
                 hotkeys: Callable[[int, int, int], bool] | None = None,
                 divert: Callable[[Callable | None], None] | None = None,
                 mark_overlay: Callable[[int], bool] | None = None):
        """hotkeys: the device buttons first (the combination closes it again); divert: hands the
        controller to the keyboard (a callback) and back (None) - see Remapper.divert."""
        super().__init__(None)
        from gamingcrypt.system import gamescope_ctl

        self.sink = sink or VirtualKeyboard()
        self.hotkeys = hotkeys
        self.divert = divert
        self.mark_overlay = mark_overlay or gamescope_ctl.set_notification_overlay
        self.marked = False
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.bridge = _Bridge(self)
        self.bridge.event.connect(self.pad_event)
        self.panel = QFrame(self)
        self.panel.setObjectName("card")
        self.body = QVBoxLayout(self.panel)
        self.body.setContentsMargins(20, 14, 20, 12)
        self.keys_box: QWidget | None = None
        hint = QLabel(HINT)
        hint.setObjectName("cardMeta")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(hint)
        self.opened = False
        self.mode = "letters"  # / "symbols" / "fn"
        self.shift = False
        self.rows: list[list[QPushButton]] = []
        self.current = (1, 0)
        self.direction = (0, 0)
        self.stick = [0.0, 0.0]
        self.hat = [0, 0]
        self.repeat = QTimer(self)
        self.repeat.timeout.connect(self._repeat)
        self._build()
        listen = self.pad_event
        self.destroyed.connect(lambda _o=None: _forget(listen))

    # the keys ---------------------------------------------------------------------------
    def _rows(self) -> list[list[tuple[str, str]]]:
        rows = [TOP]
        if self.mode == "fn":
            rows += [[(k, k) for k in row] for row in FN]
        else:
            chars = SYMBOLS if self.mode == "symbols" else LETTERS
            for index, row in enumerate(chars):
                keys = [(c.upper() if self.shift and self.mode == "letters" else c, "char") for c in row]
                if index == 3:
                    keys = [("⇧", "Shift")] + keys + [("⌫", "Backspace")]
                rows.append(keys)
        rows.append([("abc" if self.mode != "letters" else "#+=", "Symbols"), ("space", "Space"), ("⏎", "Enter")])
        return rows

    def _build(self) -> None:
        if self.keys_box is not None:
            self.keys_box.hide()  # (gone at once - deleted later)
            self.keys_box.deleteLater()
        self.keys_box = QWidget()
        grid = QVBoxLayout(self.keys_box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.body.insertWidget(0, self.keys_box)
        self.rows = []
        for row in self._rows():
            line = QHBoxLayout()
            line.setSpacing(6)
            buttons = []
            for label, action in row:
                button = big_button(label, "key", checkable=action in ("Ctrl", "Alt", "Fn", "Shift"))
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # (the window never takes the focus)
                button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                button.setProperty("action", action)
                button.clicked.connect(lambda _c=False, b=button: self.press(b))
                line.addWidget(button, 4 if action == "Space" else 1)
                buttons.append(button)
            grid.addLayout(line)
            self.rows.append(buttons)
        if self.opened:
            self.keys_box.show()  # (now - else only once the event loop gets to it: placed too small)
        self._sync_toggles()
        row, column = self.current
        row = min(row, len(self.rows) - 1)
        self.select(row, min(column, len(self.rows[row]) - 1))
        if self.opened:
            self._place()

    def _sync_toggles(self) -> None:
        on = {"Ctrl": "Ctrl" in self.sink.held, "Alt": "Alt" in self.sink.held, "Fn": self.mode == "fn",
              "Shift": self.shift}
        for row in self.rows:
            for button in row:
                action = button.property("action")
                if action in on:
                    button.setChecked(on[action])

    def select(self, row: int, column: int) -> None:
        old = self.key()
        self.current = (row, column)
        new = self.key()
        for button, current in ((old, False), (new, True)):
            if button is not None:
                button.setProperty("current", current)
                button.style().unpolish(button)
                button.style().polish(button)

    def key(self) -> QPushButton | None:
        row, column = self.current
        if 0 <= row < len(self.rows) and 0 <= column < len(self.rows[row]):
            return self.rows[row][column]
        return None

    def step(self, dx: int, dy: int) -> None:
        row, column = self.current
        if dx:
            self.select(row, (column + dx) % len(self.rows[row]))
            return
        target = (row + dy) % len(self.rows)
        x = self._center_x(self.key())
        best = min(range(len(self.rows[target])), key=lambda c: abs(self._center_x(self.rows[target][c]) - x))
        self.select(target, best)

    def _center_x(self, button: QPushButton) -> int:
        return button.mapTo(self.panel, button.rect().center()).x()

    # typing -----------------------------------------------------------------------------
    def press(self, button: QPushButton | None = None) -> None:
        button = button or self.key()
        if button is None:
            return
        action = button.property("action")
        if action == "char":
            self.sink.insert(button.text())
            if self.shift:
                self.shift = False
                self._build()
                return
        elif action == "Backspace":
            self.sink.backspace()
        elif action in ("Ctrl", "Alt"):
            self.sink.held ^= {action}
        elif action == "Shift":
            self.shift = not self.shift
            self._build()
            return
        elif action == "Fn":
            self.mode = "letters" if self.mode == "fn" else "fn"
            self._build()
            return
        elif action == "Symbols":
            self.mode = "letters" if self.mode != "letters" else "symbols"
            self._build()
            return
        else:
            self.sink.key(action)
        self._sync_toggles()  # (Ctrl / Alt count for one key)

    # the controller ---------------------------------------------------------------------
    def pad_event(self, ev_type: int, code: int, value: int) -> bool:
        if not self.opened:
            return False
        if self.hotkeys is not None and self.hotkeys(ev_type, code, value):
            return True
        if not self.opened:
            return True  # (the combination just closed it)
        if ev_type == e.EV_KEY and value == 1:
            action = {e.BTN_SOUTH: self.press, e.BTN_EAST: self.sink.backspace,
                      e.BTN_WEST: lambda: self.sink.key("Space"),  # Y (xpad layout, see navigator)
                      e.BTN_NORTH: self._toggle_shift,  # X
                      e.BTN_START: lambda: self.sink.key("Enter"), e.BTN_SELECT: self.close_keyboard}.get(code)
            if action is not None:
                action()
        elif ev_type == e.EV_ABS and code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.hat[code - e.ABS_HAT0X] = value
            self._direction_changed()
        elif ev_type == e.EV_ABS and code in (e.ABS_X, e.ABS_Y):
            axis = code - e.ABS_X
            self.stick[axis] = value / STICK_MAX
            self._direction_changed()
        return True  # nothing else gets it meanwhile

    def _toggle_shift(self) -> None:
        if self.mode == "letters":
            self.shift = not self.shift
            self._build()

    def _stick_direction(self) -> tuple[int, int]:
        x, y = self.stick
        held = self.direction != (0, 0) and self.hat == [0, 0]
        limit = STICK_RELEASE if held else STICK_PRESS
        if max(abs(x), abs(y)) < limit:
            return 0, 0
        return (1 if x > 0 else -1, 0) if abs(x) >= abs(y) else (0, 1 if y > 0 else -1)

    def _direction_changed(self) -> None:
        direction = (self.hat[0], 0) if self.hat[0] else (0, self.hat[1]) if self.hat[1] else self._stick_direction()
        if direction == self.direction:
            return
        self.direction = direction
        if direction == (0, 0):
            self.repeat.stop()
            return
        self.step(*direction)
        self.repeat.start(REPEAT_DELAY_MS)

    def _repeat(self) -> None:
        if self.direction != (0, 0):
            self.step(*self.direction)
            self.repeat.start(REPEAT_RATE_MS)

    # shown over the game ----------------------------------------------------------------
    def open_over_game(self) -> None:
        from PySide6.QtGui import QGuiApplication

        from gamingcrypt.system import gamescope_ctl
        from gamingcrypt.ui import navigator

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(*gamescope_ctl.notification_geometry(screen.geometry()))
        self.opened = True
        self._place()
        self.panel.show()
        self.show()
        if not self.marked:
            self.marked = self.mark_overlay(int(self.winId()))
        if self.pad_event not in navigator.LISTENERS:
            navigator.LISTENERS.append(self.pad_event)  # (a controller the remapper doesn't read)
        if self.divert is not None:
            self.divert(lambda events: [self.bridge.event.emit(*event) for event in events])

    def _place(self) -> None:
        """At the bottom, in the middle (as tall as its keys: Fn has a row less)."""
        width = min(PANEL_WIDTH, self.width() - 32)
        self.panel.layout().activate()
        height = self.panel.sizeHint().height()
        self.panel.setGeometry((self.width() - width) // 2, self.height() - height - 16, width, height)

    def close_keyboard(self) -> None:
        from gamingcrypt.ui import navigator

        if not self.opened:
            return
        self.opened = False
        if self.divert is not None:
            self.divert(None)  # the controller is the game's again
        if self.pad_event in navigator.LISTENERS:
            navigator.LISTENERS.remove(self.pad_event)
        self.repeat.stop()
        self.direction, self.stick, self.hat = (0, 0), [0.0, 0.0], [0, 0]
        self.sink.held.clear()
        self.shift = False
        self.panel.hide()
        if self.isVisible():
            self.repaint()  # drawn empty first: gamescope keeps an overlay's last picture
            QTimer.singleShot(UNMAP_DELAY_MS, self._unmap)
        self.closed.emit()

    def _unmap(self) -> None:
        if not self.opened:
            self.hide()

    def is_open(self) -> bool:
        return self.opened

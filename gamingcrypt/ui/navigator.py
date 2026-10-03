"""Browse the UI with a controller: spatial focus movement, A = select, B = back.

Widgets can take over input with optional hooks:
``gamepad_direction(dx, dy) -> bool``, ``gamepad_activate() -> bool``,
``gamepad_back() -> bool`` (also on ancestors), ``gamepad_start() -> bool``.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QLineEdit,
    QScrollArea,
    QSlider,
    QWidget,
)

from gamingcrypt.input import evdev as e

STICK_PRESS, STICK_RELEASE = 0.6, 0.35
REPEAT_DELAY_MS, REPEAT_RATE_MS = 380, 110
SCROLL_MS = 140  # shorter than the repeat rate: holding the D-pad glides continuously

_paused = False


def set_paused(paused: bool) -> None:
    """E.g. while remapping buttons: A/B must not also click / go back."""
    global _paused
    _paused = paused


class _Bridge(QObject):
    event = Signal(int, int, int)


class GamepadNavigator(QObject):
    def __init__(self, window: QWidget, tab_switch: Callable[[int], None] | None = None,
                 parent: QObject | None = None):
        super().__init__(parent or window)
        self.window = window
        self.tab_switch = tab_switch
        self.bridge = _Bridge(self)
        self.bridge.event.connect(self.on_event)
        self.hat = [0, 0]
        self.stick = [0.0, 0.0]
        self.held: tuple[int, int] | None = None
        self.repeat = QTimer(self)
        self.repeat.timeout.connect(self._repeat)
        self._scroll_anims: dict[int, QPropertyAnimation] = {}
        self._scroll_targets: dict[int, int] = {}

    # input -------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return not _paused and self.window.isVisible() and not self.window.isMinimized()

    def on_event(self, ev_type: int, code: int, value: int) -> None:
        if not self.active:
            self._release()
            return
        if not self.window.isActiveWindow() and (ev_type == e.EV_KEY and value == 1):
            self.window.activateWindow()
        if ev_type == e.EV_KEY and value == 1:
            action = {e.BTN_SOUTH: self.activate, e.BTN_EAST: self.back, e.BTN_START: self.start,
                      e.BTN_TL: lambda: self.switch_tab(-1), e.BTN_TR: lambda: self.switch_tab(1)}.get(code)
            if action is not None:
                action()
        elif ev_type == e.EV_ABS and code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.hat[code - e.ABS_HAT0X] = value
            self._direction_changed()
        elif ev_type == e.EV_ABS and code in (e.ABS_X, e.ABS_Y):
            self.stick[code - e.ABS_X] = value / 32767
            self._direction_changed()

    def _current_direction(self) -> tuple[int, int] | None:
        if self.hat != [0, 0]:
            return (self.hat[0], 0) if self.hat[0] else (0, self.hat[1])
        x, y = self.stick
        limit = STICK_RELEASE if self.held else STICK_PRESS
        if max(abs(x), abs(y)) < limit:
            return None
        return ((1 if x > 0 else -1), 0) if abs(x) >= abs(y) else (0, (1 if y > 0 else -1))

    def _direction_changed(self) -> None:
        direction = self._current_direction()
        if direction == self.held:
            return
        self.held = direction
        if direction is None:
            self.repeat.stop()
            return
        self.move(*direction)
        self.repeat.start(REPEAT_DELAY_MS)

    def _repeat(self) -> None:
        if self.held is None or not self.active:
            self._release()
            return
        self.repeat.setInterval(REPEAT_RATE_MS)
        self.move(*self.held)

    def _release(self) -> None:
        self.held = None
        self.repeat.stop()

    # helpers -----------------------------------------------------------------
    def root(self) -> QWidget:
        root = getattr(self.window, "nav_root", None)
        return root() if callable(root) else self.window

    def focused(self) -> QWidget | None:
        # The window's own focus child: still known when the window isn't active
        # (e.g. right after coming back from a game).
        w = self.window.focusWidget() or QApplication.focusWidget()
        root = self.root()
        if w is None or not w.isVisible() or not (w is root or root.isAncestorOf(w)):
            return None
        return w

    def candidates(self) -> list[QWidget]:
        root = self.root()
        return [w for w in root.findChildren(QWidget)
                if w.isVisible() and w.isEnabled() and w.focusPolicy() & Qt.FocusPolicy.TabFocus
                and w.width() > 0 and w.height() > 0]

    @staticmethod
    def _center(w: QWidget) -> QPointF:
        return QPointF(w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2)))

    def focus(self, w: QWidget) -> None:
        from gamingcrypt.ui.widgets import OnScreenKeyboard

        for keyboard in self.root().findChildren(OnScreenKeyboard):
            if keyboard.dismissable and keyboard.isVisible() and not keyboard.owns(w):
                keyboard.hide()  # highlight went somewhere else
        w.setFocus(Qt.FocusReason.TabFocusReason)
        parent = w.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                self.scroll_to(parent, w)
            parent = parent.parentWidget()

    def scroll_to(self, area: QScrollArea, w: QWidget, margin: int = 40) -> None:
        """Glide (instead of jumping) so ``w`` is fully visible."""
        from gamingcrypt.ui.widgets import FoldingHeader

        content = area.widget()
        if content is None:
            return
        bar = area.verticalScrollBar()
        top = w.mapTo(content, QPoint(0, 0)).y()
        bottom = top + w.height()
        view = area.viewport().height()
        start = self._scroll_targets.get(id(bar), bar.value())
        target = start
        if top - margin < start:
            target = top - margin
        elif bottom + margin > start + view:
            target = bottom + margin - view
        target = max(bar.minimum(), min(bar.maximum(), target))
        if target == start:
            return
        self._scroll_targets[id(bar)] = target
        anim = self._scroll_anims.get(id(bar))
        if anim is None:
            anim = QPropertyAnimation(bar, b"value", self)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda b=id(bar): self._scroll_targets.pop(b, None))
            anim.finished.connect(self._scroll_done)
            self._scroll_anims[id(bar)] = anim
        anim.stop()
        anim.setDuration(SCROLL_MS)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        FoldingHeader.programmatic = True
        anim.start()

    def _scroll_done(self) -> None:
        from gamingcrypt.ui.widgets import FoldingHeader

        if not any(a.state() == QPropertyAnimation.State.Running for a in self._scroll_anims.values()):
            FoldingHeader.programmatic = False

    @staticmethod
    def _send_key(target: QWidget, key: Qt.Key) -> None:
        target = target.focusWidget() or target  # e.g. the list inside a dropdown popup
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))

    # actions -------------------------------------------------------------------
    def move(self, dx: int, dy: int) -> None:
        popup = QApplication.activePopupWidget()
        if popup is not None:
            if dy:
                self._send_key(popup, Qt.Key.Key_Down if dy > 0 else Qt.Key.Key_Up)
            return
        current = self.focused()
        if current is not None:
            hook = getattr(current, "gamepad_direction", None)
            if callable(hook) and hook(dx, dy):
                return
            if isinstance(current, QSlider) and dx:
                step = max(1, (current.maximum() - current.minimum()) // 20)
                current.setValue(current.value() + dx * step)
                return
        target = self.nearest(current, dx, dy)
        if target is not None:
            self.focus(target)

    @staticmethod
    def _scroll_area(w: QWidget | None) -> QScrollArea | None:
        while w is not None:
            w = w.parentWidget()
            if isinstance(w, QScrollArea):
                return w
        return None

    def nearest(self, current: QWidget | None, dx: int, dy: int) -> QWidget | None:
        options = [w for w in self.candidates() if w is not current]
        if not options:
            return None
        if current is None:
            return min(options, key=lambda w: (round(self._center(w).y() / 20), self._center(w).x()))
        # Inside a scrolling list (e.g. the game grid) stay in the list - also on items
        # scrolled out of view - and only leave it at its edge. Otherwise the tab bar,
        # which is closer *on screen*, would win over the game right above.
        area = self._scroll_area(current)
        if area is not None and area.widget() is not None:
            content = area.widget()
            inside = [w for w in options if content.isAncestorOf(w)]
            best = self._best(current, inside, dx, dy)
            if best is not None:
                return best
            options = [w for w in options if not content.isAncestorOf(w)]
        return self._best(current, options, dx, dy)

    def _best(self, current: QWidget, options: list[QWidget], dx: int, dy: int) -> QWidget | None:
        here = self._center(current)
        best, best_score = None, None
        for w in options:
            there = self._center(w)
            vx, vy = there.x() - here.x(), there.y() - here.y()
            primary = vx * dx + vy * dy
            if primary <= 4:
                continue
            secondary = abs(vx * dy) + abs(vy * dx)
            score = primary + 2.5 * secondary
            if best_score is None or score < best_score:
                best, best_score = w, score
        return best

    def activate(self) -> None:
        popup = QApplication.activePopupWidget()
        if popup is not None:
            self._send_key(popup, Qt.Key.Key_Return)
            return
        w = self.focused()
        if w is None:
            target = self.nearest(None, 0, 1)
            if target is not None:
                self.focus(target)
            return
        hook = getattr(w, "gamepad_activate", None)
        if callable(hook) and hook():
            return
        if isinstance(w, QAbstractButton):
            w.click()
        elif hasattr(w, "tapped"):
            w.tapped.emit()
        elif isinstance(w, QComboBox):
            w.showPopup()
        elif isinstance(w, QLineEdit):
            self._open_keyboard(w)

    def _open_keyboard(self, edit: QLineEdit) -> None:
        # The touch keyboard opens on a tap - simulate one, then jump onto its keys.
        pos = QPointF(edit.width() / 2, edit.height() / 2)
        for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            QApplication.sendEvent(edit, QMouseEvent(kind, pos, edit.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                                                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        keyboard = self._keyboard_for(edit)
        if keyboard is not None:
            keys = [k for k in keyboard.findChildren(QAbstractButton) if k.isVisible()]
            if keys:
                self.focus(keys[0])

    def _keyboard_for(self, edit: QLineEdit):
        from gamingcrypt.ui.widgets import OnScreenKeyboard

        for kb in self.root().findChildren(OnScreenKeyboard):
            if kb.isVisible() and kb.target() is edit:
                return kb
        return None

    def back(self) -> None:
        popup = QApplication.activePopupWidget()
        if popup is not None:
            self._send_key(popup, Qt.Key.Key_Escape)
            return
        from gamingcrypt.ui.widgets import OnScreenKeyboard

        for keyboard in self.root().findChildren(OnScreenKeyboard):
            if keyboard.dismissable and keyboard.isVisible():
                keyboard.hide()  # B closes a pop-up keyboard, wherever the highlight is
                target = keyboard.target()
                if target is not None and target.isVisible():
                    self.focus(target)
                return

        w = self.focused()
        node = w
        while node is not None:
            if isinstance(node, OnScreenKeyboard) and node.target() is not None and node.target().isVisible():
                # leave the keyboard: back to the text field it types into
                if node.dismissable:
                    node.hide()
                self.focus(node.target())
                return
            hook = getattr(node, "gamepad_back", None)
            if callable(hook) and hook():
                return
            node = node.parentWidget()
        root_hook = getattr(self.window, "gamepad_back", None)
        if callable(root_hook):
            root_hook()

    def start(self) -> None:
        w = self.focused()
        while w is not None:
            hook = getattr(w, "gamepad_start", None)
            if callable(hook) and hook():
                return
            w = w.parentWidget()

    def switch_tab(self, delta: int) -> None:
        if self.tab_switch is not None:
            self.tab_switch(delta)

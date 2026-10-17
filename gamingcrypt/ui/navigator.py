"""Browse the UI with a controller: spatial focus movement, A = select, B = back.

Widgets can take over input with optional hooks:
``gamepad_direction(dx, dy) -> bool``, ``gamepad_activate() -> bool``,
``gamepad_navigate(current, dx, dy) -> QWidget | None`` (on an ancestor: its own layout's order),
``gamepad_back() -> bool`` (also on ancestors), ``gamepad_start() -> bool``, ``gamepad_north() -> bool``
(Y, the top button) and ``gamepad_west() -> bool`` (X, the left one), also on ancestors.
The pad comes in Xbox 360 (xpad) layout: X is BTN_NORTH (0x133), Y is BTN_WEST (0x134) - see input/profile.
"""

from __future__ import annotations

from typing import Callable

import shiboken6
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
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
from gamingcrypt.ui.combo import open_list

STICK_PRESS, STICK_RELEASE = 0.6, 0.35
REPEAT_DELAY_MS, REPEAT_RATE_MS = 380, 110
SCROLL_MS = 140  # shorter than the repeat rate: holding the D-pad glides continuously

_paused = False
_TO_TOP = object()  # nearest(): scroll the list to its top first
TRIGGER_PRESS, TRIGGER_RELEASE = 128, 64  # analog triggers (0-255)


def set_paused(paused: bool) -> None:
    """E.g. while remapping buttons: A/B must not also click / go back."""
    global _paused
    _paused = paused


# Pages that want raw controller input (button recording, controller test) register
# here: called first with every event, returning True keeps it from navigating.
LISTENERS: list[Callable[[int, int, int], bool]] = []


def _disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


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
        self.triggers: dict[int, bool] = {}  # analog trigger pulled (LT / RT page)
        self._scroll_anims: dict[int, QPropertyAnimation] = {}
        self._scroll_targets: dict[int, int] = {}
        self.hotkey_filter: Callable[[int, int, int], bool] | None = None
        self.anchor_x: float | None = None  # the column up / down keeps (global x)
        # A highlighted button greyed out while it works ("Checking…") keeps the highlight instead
        # of Qt passing it on to the next widget (and scrolling the page there).
        self.parked: QWidget | None = None
        self._pressing: tuple[QWidget, list] | None = None
        app = QApplication.instance()
        app.focusChanged.connect(self._focus_changed)
        window.destroyed.connect(lambda _o=None: _disconnect(app.focusChanged, self._focus_changed))

    # input -------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return not _paused and self.window.isVisible() and not self.window.isMinimized()

    def on_event(self, ev_type: int, code: int, value: int) -> None:
        for listener in list(LISTENERS):
            if listener(ev_type, code, value):
                return
        if self.hotkey_filter is not None and self.hotkey_filter(ev_type, code, value):
            return
        if not self.active:
            self._release()
            return
        if not self.window.isActiveWindow() and (ev_type == e.EV_KEY and value == 1):
            self.window.activateWindow()
        if ev_type == e.EV_KEY and value == 1:
            action = {e.BTN_SOUTH: self.activate, e.BTN_EAST: self.back, e.BTN_START: self.start,
                      # xpad layout: BTN_NORTH is X (the left button), BTN_WEST is Y (the top one)
                      e.BTN_NORTH: lambda: self.hook("gamepad_west"), e.BTN_WEST: lambda: self.hook("gamepad_north"),
                      e.BTN_TL: lambda: self.switch_tab(-1), e.BTN_TR: lambda: self.switch_tab(1),
                      e.BTN_TL2: lambda: self.page(-1), e.BTN_TR2: lambda: self.page(1)}.get(code)
            if action is not None:
                action()
        elif ev_type == e.EV_ABS and code in (e.ABS_HAT0X, e.ABS_HAT0Y):
            self.hat[code - e.ABS_HAT0X] = value
            self._direction_changed()
        elif ev_type == e.EV_ABS and code in (e.ABS_Z, e.ABS_RZ):
            # analog triggers: a press when pulled more than halfway (0-255), let go below a quarter
            pulled = self.triggers.get(code, False)
            if not pulled and value > TRIGGER_PRESS:
                self.triggers[code] = True
                self.page(-1 if code == e.ABS_Z else 1)
            elif pulled and value < TRIGGER_RELEASE:
                self.triggers[code] = False
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

    # a greyed out highlight ------------------------------------------------------
    def _focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        if new is None or not shiboken6.isValid(self) or not shiboken6.isValid(self.window):
            return
        if self.parked is not None and new is not self.parked and not isinstance(new, QScrollArea):
            self._unpark()  # (a list itself takes the focus when the window becomes active - not a choice)
        if old is None or not shiboken6.isValid(old) or old.isEnabled() or old.window() is not self.window.window():
            return
        if not old.isVisible():
            return
        # Qt hands the highlight on because ``old`` was disabled: keep it there (nothing has
        # the focus meanwhile - a list mustn't scroll to where it went) and give it back once
        # it works again.
        self.parked = old
        old.installEventFilter(self)
        new.clearFocus()

    def _unpark(self) -> None:
        parked, self.parked = self.parked, None
        if parked is not None and shiboken6.isValid(parked):
            parked.removeEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        pressing = self._pressing
        if pressing is not None and watched is pressing[0] and (
                (event.type() == QEvent.Type.EnabledChange and not pressing[0].isEnabled())
                or (event.type() == QEvent.Type.Hide and pressing[0].isHidden())):
            pressing[1].append(self.window.focusWidget())  # (Qt has just passed the focus on)
        if watched is self.parked and event.type() == QEvent.Type.EnabledChange and self.parked.isEnabled():
            parked = self.parked
            self._unpark()
            if self._nothing_chosen() and parked.isVisible():
                parked.setFocus(Qt.FocusReason.OtherFocusReason)
        return False

    def _keep_if_greyed(self, w: QWidget, press: Callable[[], None]) -> None:
        """Press ``w``; when it greys itself out meanwhile (busy), it keeps the highlight and
        the lists stay where they were. (Also when the window isn't active - Qt then doesn't
        say where the focus went.)"""
        bars = []
        area = self._scroll_area(w)
        while area is not None:
            bars.append((area.verticalScrollBar(), area.verticalScrollBar().value()))
            area = self._scroll_area(area)
        self._pressing = (w, [])  # eventFilter notes where Qt put the focus when w was disabled
        w.installEventFilter(self)
        try:
            press()
        finally:
            pressing, self._pressing = self._pressing, None
            if shiboken6.isValid(w) and w is not self.parked:
                w.removeEventFilter(self)
        if not shiboken6.isValid(w) or not pressing[1]:
            return
        focus = self.window.focusWidget()
        if w.isHidden():  # it went away ("Update now" once updated): the nearest one, not where Qt went
            if focus is pressing[1][-1]:
                for bar, value in bars:
                    if shiboken6.isValid(bar):
                        bar.setValue(value)
                target = self._closest(w)
                if target is not None:
                    self.focus(target)
            return
        if w.isEnabled() or not w.isVisible():
            return
        if focus is not pressing[1][-1]:
            return  # the page chose where to go on itself
        if focus is not None:
            focus.clearFocus()
        for bar, value in bars:
            if shiboken6.isValid(bar):
                bar.setValue(value)
        if self.parked is not w:
            self._unpark()
            self.parked = w
            w.installEventFilter(self)

    def _closest(self, w: QWidget) -> QWidget | None:
        """What's nearest to where ``w`` is (or was)."""
        here = self._center(w)
        options = [o for o in self.candidates() if o is not w]
        if not options:
            return None
        return min(options, key=lambda o: (self._center(o) - here).manhattanLength())

    def _parked(self) -> QWidget | None:
        parked = self.parked
        if parked is None or not shiboken6.isValid(parked) or not parked.isVisible() or not self._nothing_chosen():
            return None
        return parked

    def _nothing_chosen(self) -> bool:
        focus = self.window.focusWidget()
        return focus is None or isinstance(focus, QScrollArea)

    # helpers -----------------------------------------------------------------
    def root(self) -> QWidget:
        root = getattr(self.window, "nav_root", None)
        return root() if callable(root) else self.window

    def focused(self) -> QWidget | None:
        if self.parked is not None and self._parked() is not None:
            return None  # a list holding the focus meanwhile isn't the highlight
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
                if not isinstance(w, QScrollArea)  # a container, not something to select
                and w.isVisible() and w.isEnabled() and w.focusPolicy() & Qt.FocusPolicy.TabFocus
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
        self.anchor_x = self._anchor(w)
        parent = w.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                self.scroll_to(parent, w)
            parent = parent.parentWidget()

    def scroll_to(self, area: QScrollArea, w: QWidget, margin: int = 40) -> None:
        """Glide (instead of jumping) so ``w`` is fully visible."""
        content = area.widget()
        if content is None:
            return
        bar = area.verticalScrollBar()
        top = w.mapTo(content, QPoint(0, 0)).y()
        bottom = top + w.height()
        view = area.viewport().height()
        self._live_anim(bar)  # drops what's left of a deleted page
        start = self._scroll_targets.get(id(bar), bar.value())
        target = start
        if top - margin < start:
            target = top - margin
        elif bottom + margin > start + view:
            target = bottom + margin - view
        if self._topmost_in(content, w):
            # the first thing in the list: show the list from its very top (captions above
            # it, and the folded header comes back) - not just the highlighted button
            target = bar.minimum()
        target = max(bar.minimum(), min(bar.maximum(), target))
        if target == start:
            return
        self._glide(bar, target)

    def _topmost_in(self, content: QWidget, w: QWidget) -> bool:
        my_top = w.mapTo(content, QPoint(0, 0)).y()
        return not any(other is not w and content.isAncestorOf(other)
                       and other.mapTo(content, QPoint(0, 0)).y() < my_top - 4
                       for other in self.candidates())

    def _glide(self, bar, target: int) -> None:
        from gamingcrypt.ui.widgets import FoldingHeader

        anim = self._live_anim(bar)
        self._scroll_targets[id(bar)] = target
        if anim is None:
            anim = QPropertyAnimation(bar, b"value", bar)  # owned by the bar: others can stop it
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda b=id(bar): self._scroll_targets.pop(b, None))
            anim.finished.connect(self._scroll_done)
            # its page closed while it glided: "the controller scrolls" must not stay set for good
            anim.destroyed.connect(lambda _o=None: QTimer.singleShot(0, self._scroll_done))
            self._scroll_anims[id(bar)] = anim
        anim.stop()
        anim.setDuration(SCROLL_MS)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        FoldingHeader.programmatic = True
        anim.start()

    def _live_anim(self, bar) -> QPropertyAnimation | None:
        """The bar's animation - entries of deleted pages are dropped (Qt deletes the
        animation with its bar, and a new bar may even get the same id)."""
        self._forget_deleted()
        anim = self._scroll_anims.get(id(bar))
        if anim is not None and anim.targetObject() is not bar:
            self._scroll_anims.pop(id(bar), None)
            self._scroll_targets.pop(id(bar), None)
            anim = None
        return anim

    def _forget_deleted(self) -> None:
        for key, anim in list(self._scroll_anims.items()):
            if not shiboken6.isValid(anim):
                del self._scroll_anims[key]
                self._scroll_targets.pop(key, None)

    def _scroll_done(self) -> None:
        from gamingcrypt.ui.widgets import FoldingHeader

        if not shiboken6.isValid(self) or not shiboken6.isValid(self.window):
            return  # a navigator of a closed window: not its business (another may be gliding)
        self._forget_deleted()
        if not any(a.state() == QPropertyAnimation.State.Running for a in self._scroll_anims.values()):
            FoldingHeader.programmatic = False

    @staticmethod
    def _send_key(target: QWidget, key: Qt.Key) -> None:
        target = target.focusWidget() or target  # e.g. the list inside a dropdown popup
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QApplication.sendEvent(target, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier))

    # actions -------------------------------------------------------------------
    def move(self, dx: int, dy: int) -> None:
        popup = open_list()  # (a drop-down's open list)
        if popup is not None:
            if dy:
                self._send_key(popup, Qt.Key.Key_Down if dy > 0 else Qt.Key.Key_Up)
            return
        current = self.focused() or self._parked()
        if current is not None and current.isEnabled():
            hook = getattr(current, "gamepad_direction", None)
            if callable(hook) and hook(dx, dy):
                return
            if isinstance(current, QSlider) and dx:
                step = max(1, (current.maximum() - current.minimum()) // 20)
                current.setValue(current.value() + dx * step)
                return
        node = current.parentWidget() if current is not None else None
        root = self.root()
        while node is not None:  # a container that knows its own order (e.g. the quick menu's grid)
            if node is not root and not root.isAncestorOf(node):
                break  # outside what the controller is in (a question over the quick menu)
            navigate = getattr(node, "gamepad_navigate", None)
            if callable(navigate):
                target = navigate(current, dx, dy)
                if target is not None:
                    self.focus(target)
                    return
                if getattr(node, "navigation_complete", False):
                    return  # its edge: stay
                break
            node = node.parentWidget()
        target = self.nearest(current, dx, dy)
        if target is _TO_TOP:
            bar = self._scroll_area(current).verticalScrollBar()
            self._glide(bar, bar.minimum())  # first the list's top (and what's above it, e.g. filters)
            return
        if target is not None:
            self.focus(target)
        elif dy < 0:
            # nothing further up, but the list isn't at its top yet: go there
            area = self._scroll_area(current)
            if area is not None and area.verticalScrollBar().value() > area.verticalScrollBar().minimum():
                self._glide(area.verticalScrollBar(), area.verticalScrollBar().minimum())

    @staticmethod
    def _keyboard_of(w: QWidget | None):
        from gamingcrypt.ui.widgets import OnScreenKeyboard

        while w is not None:
            if isinstance(w, OnScreenKeyboard):
                return w
            w = w.parentWidget()
        return None

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
        keyboard = self._keyboard_of(current)
        if keyboard is not None:
            keys = [w for w in options if keyboard.isAncestorOf(w)]
            best = self._best(current, keys, dx, dy)
            if best is not None:
                return best
            field = keyboard.target()
            if dy < 0 and field is not None and field.isVisible():
                return field  # off the top row: back to what it types into (not a card behind it)
            if keyboard.dismissable:
                return None  # its edges: stay on the keys
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
            if dx:
                return self._wrap(current, dx)  # sideways never leaves the list
            bar = area.verticalScrollBar()
            if dy < 0 and bar.value() > bar.minimum() and self._scroll_targets.get(id(bar)) != bar.minimum():
                return _TO_TOP
            options = [w for w in options if not content.isAncestorOf(w)]
        return self._best(current, options, dx, dy) or (self._wrap(current, dx) if dx else None)

    @staticmethod
    def _rect(w: QWidget) -> QRect:
        return QRect(w.mapToGlobal(QPoint(0, 0)), QSize(w.width(), w.height()))

    def _seen(self, w: QWidget) -> QRect:
        """The part that's on screen: lists cut off what's scrolled away (a card half under the
        on-screen keyboard isn't in the keyboard's row)."""
        rect = self._rect(w)
        area = self._scroll_area(w)
        while area is not None and not rect.isEmpty():
            viewport = area.viewport()
            rect = rect.intersected(QRect(viewport.mapToGlobal(QPoint(0, 0)), viewport.size()))
            area = self._scroll_area(area)
        if not rect.isEmpty() and self._covered(w, rect):
            return QRect()  # e.g. a card under the filter bar lying over the list
        return rect

    def _covered(self, w: QWidget, rect: QRect) -> bool:
        """Something else lies over the middle of what's visible of it."""
        window = w.window()
        hit = window.childAt(window.mapFromGlobal(rect.center()))
        return hit is not None and hit is not w and not w.isAncestorOf(hit) and not hit.isAncestorOf(w) \
            and not isinstance(hit, QScrollArea) and hit is not self._scroll_area(w).viewport() \
            if self._scroll_area(w) is not None else False

    @staticmethod
    def _gap(a0: int, a1: int, b0: int, b1: int) -> int:
        """Distance between two ranges, 0 when they overlap."""
        return max(0, b0 - a1, a0 - b1)

    ROW_TOLERANCE = 24  # widgets this close in height count as one row

    def _anchor(self, w: QWidget) -> float:
        """The column to keep when going up / down: a narrow widget's centre; inside a wide one
        (the search field, a list row) the column kept so far - or its left edge."""
        rect = self._rect(w)
        if rect.width() < self.root().width() * 0.45:
            return float(rect.center().x())
        if self.anchor_x is not None and rect.left() <= self.anchor_x <= rect.right():
            return self.anchor_x
        return float(rect.left() + 1)

    def _best(self, current: QWidget, options: list[QWidget], dx: int, dy: int) -> QWidget | None:
        """What an average user expects: left / right stays in the row, up / down goes to the
        next row in the same column, and a row of tabs is entered at the selected tab."""
        mine = self._rect(current)
        if dx:
            seen = self._seen(current)
            area = self._scroll_area(current)
            row = []
            for w in options:
                # in the same list compare where they are, not what's on screen: right after
                # going down the list is still gliding there, and the neighbours aren't in view yet
                same_list = area is not None and area.isAncestorOf(w) and self._scroll_area(w) is area
                rect = self._rect(w) if same_list else self._seen(w)
                mine = self._rect(current) if same_list else seen
                if rect.isEmpty() or mine.isEmpty():
                    continue
                overlap = min(mine.bottom(), rect.bottom()) - max(mine.top(), rect.top())
                if overlap < min(mine.height(), rect.height()) * 0.5:
                    continue  # another row
                ahead = rect.left() - mine.right() if dx > 0 else mine.left() - rect.right()
                centre = (rect.center().x() - mine.center().x()) * dx
                if centre <= 4:
                    continue  # not in that direction
                row.append((max(ahead, 0), abs(rect.center().y() - mine.center().y()), w))
            if not row:
                return None
            return min(row, key=lambda r: (r[0], r[1]))[2]  # sideways: always the next one
        ahead_of = []
        area = self._scroll_area(current)
        for hidden_too in (False, True):
            ahead_of = self._ahead(current, mine, options, dy, area, hidden_too)
            if ahead_of:
                break  # (the second time: a list with nothing on screen yet, e.g. a page of text first)
        if not ahead_of:
            return None
        nearest = min(a for a, _r, _w in ahead_of)
        row = [(rect, w) for a, rect, w in ahead_of if a <= nearest + self.ROW_TOLERANCE]
        column = self.anchor_x if self.anchor_x is not None and self._rect(current).left() <= self.anchor_x \
            <= self._rect(current).right() else self._anchor(current)

        def distance(item) -> tuple:
            rect = item[0]
            return (self._gap(int(column), int(column), rect.left(), rect.right()), rect.left())

        return self._enter_group(current, min(row, key=distance)[1])

    def _ahead(self, current: QWidget, mine: QRect, options: list[QWidget], dy: int, area, hidden_too: bool) -> list:
        ahead_of = []
        for w in options:
            # in the same list: also what's scrolled away; elsewhere only what's on screen
            same_list = area is not None and area.isAncestorOf(w)
            rect = self._rect(w) if same_list or hidden_too else self._seen(w)
            if rect.isEmpty():
                continue
            ahead = rect.top() - mine.bottom() if dy > 0 else mine.top() - rect.bottom()
            if ahead < -8:  # beside or behind, not below / above
                continue
            if (rect.center().y() - mine.center().y()) * dy <= 4:
                continue
            ahead_of.append((max(ahead, 0), rect, w))
        return ahead_of

    @staticmethod
    def _enter_group(current: QWidget, target: QWidget) -> QWidget:
        """Coming into a row of tabs / chips (one of them selected) from above or below: the selected
        one. (Sideways into such a row - from the power button, a sort direction, a drop-down next to
        filter chips - goes to the neighbour, like everywhere else.)
        Only real choices (tabs, buttons made with choice=True) - not on / off buttons side by side
        (Options and Favorite: right from Play must not skip Options)."""

        def picks(b) -> bool:
            return isinstance(b, QAbstractButton) and b.isCheckable() and (
                b.objectName() == "tab" or bool(b.property("choice")))

        parent = target.parentWidget()
        if not picks(target) or parent is None:
            return target
        group = [b for b in parent.findChildren(QAbstractButton, options=Qt.FindChildOption.FindDirectChildrenOnly)
                 if picks(b) and b.isVisible() and b.isEnabled()]
        if len(group) < 2 or current in group:
            return target
        return next((b for b in group if b.isChecked()), target)

    def _wrap(self, current: QWidget, dx: int) -> QWidget | None:
        """The end of a row of a grid (cards that wrap): on with the next row's first one."""
        from gamingcrypt.ui.widgets import FlowLayout

        parent = current.parentWidget()
        layout = parent.layout() if parent is not None else None
        if not isinstance(layout, FlowLayout):
            return None
        items = [layout.itemAt(i).widget() for i in range(layout.count())]
        items = [w for w in items if w is not None and w.isVisible() and w.isEnabled()
                 and w.focusPolicy() & Qt.FocusPolicy.TabFocus]
        if current not in items:
            return None
        index = items.index(current) + dx
        return items[index] if 0 <= index < len(items) else None

    def activate(self) -> None:
        popup = open_list()  # (a drop-down's open list)
        if popup is not None:
            self._send_key(popup, Qt.Key.Key_Return)
            return
        w = self.focused()
        if w is None and self._parked() is not None:
            return  # it's busy (greyed out): A waits
        if w is None:
            target = self.nearest(None, 0, 1)
            if target is not None:
                self.focus(target)
            return
        hook = getattr(w, "gamepad_activate", None)
        if callable(hook) and hook():
            return
        if isinstance(w, QAbstractButton):
            self._keep_if_greyed(w, w.click)
        elif hasattr(w, "tapped"):
            self._keep_if_greyed(w, w.tapped.emit)
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
        popup = open_list()  # (a drop-down's open list)
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

        w = self.focused() or self._parked()
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
        self.hook("gamepad_start")

    def page(self, direction: int) -> None:
        """LT / RT: a screen up / down in a list - the highlight goes to what's there, in the
        same column (the end of the list when there's less than a screen left)."""
        current = self.focused() or self._parked()
        area = self._scroll_area(current)
        if current is None or area is None or area.widget() is None:
            return
        content = area.widget()
        items = [w for w in self.candidates() if content.isAncestorOf(w) and w is not current]
        mine = self._center(current)
        ahead = [w for w in items if (self._center(w).y() - mine.y()) * direction > self.ROW_TOLERANCE]
        if not ahead:
            return  # already at that end
        goal = mine.y() + direction * area.viewport().height()
        column = self._anchor(current)

        def distance(w: QWidget) -> tuple[float, float]:
            centre = self._center(w)
            past = max(0.0, (centre.y() - goal) * direction)  # beyond a screen: only if nothing closer
            return (abs(centre.y() - goal) + past, abs(centre.x() - column))

        rows = sorted(ahead, key=distance)
        best_row_y = self._center(rows[0]).y()
        row = [w for w in ahead if abs(self._center(w).y() - best_row_y) <= self.ROW_TOLERANCE]
        target = min(row, key=lambda w: abs(self._center(w).x() - column))
        anchor = self.anchor_x
        self.focus(target)
        self.anchor_x = anchor if anchor is not None else column  # the column is kept

    def hook(self, name: str) -> bool:
        """Y / X / Start: the highlighted widget, or the nearest page / tab above it, that has
        ``name()`` and takes it (returns True)."""
        w = self.focused() or self._parked()
        while w is not None:
            hook = getattr(w, name, None)
            if callable(hook) and hook():
                return True
            w = w.parentWidget()
        return False

    def switch_tab(self, delta: int) -> None:
        if self.tab_switch is not None:
            self.tab_switch(delta)

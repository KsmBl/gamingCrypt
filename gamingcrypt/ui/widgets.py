"""Reusable touch friendly widgets."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScroller,
    QScrollerProperties,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def enable_touch_scroll(area: QAbstractScrollArea) -> None:
    """Kinetic flick scrolling with finger (and mouse drag for testing)."""
    viewport = area.viewport()
    QScroller.grabGesture(viewport, QScroller.ScrollerGestureType.LeftMouseButtonGesture)
    scroller = QScroller.scroller(viewport)
    props = scroller.scrollerProperties()
    props.setScrollMetric(QScrollerProperties.ScrollMetric.DecelerationFactor, 0.25)
    props.setScrollMetric(
        QScrollerProperties.ScrollMetric.HorizontalOvershootPolicy,
        QScrollerProperties.OvershootPolicy.OvershootAlwaysOff,
    )
    scroller.setScrollerProperties(props)


def big_button(text: str, object_name: str = "", checkable: bool = False, choice: bool = False) -> QPushButton:
    """choice: one of a row where one is picked (filters, seasons, sort order) - the controller
    enters such a row at the picked one. Plain on / off buttons (Favorite, Options) aren't."""
    button = QPushButton(text)
    if object_name:
        button.setObjectName(object_name)
    button.setCheckable(checkable or choice)
    if choice:
        button.setProperty("choice", True)
    # Reachable with the controller, but a finger tap doesn't steal focus from text fields.
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    if object_name in ("", "primary", "danger") and "\n" not in text:
        # one height for every button in a row: a colour emoji ("🗑", "⚙") made its button taller
        button.setMaximumHeight(BUTTON_HEIGHT)
    return button


BUTTON_HEIGHT = 68  # 42 + padding + the focus ring's room (theme)


class ComingSoon(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        label = QLabel(f"{name}\n\nComing soon")
        label.setObjectName("comingSoon")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class FlowLayout(QLayout):
    """Lays out children left to right and wraps - used for the game grids."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 20, stretch: bool = False):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing
        # stretch: as many (equally wide) items per row as fit, widened to fill the row exactly -
        # the same gap left and right
        self._stretch = stretch
        # Qt asks heightForWidth() constantly (every resize / animation frame); with
        # hundreds of game cards recomputing it each time makes scrolling choppy.
        self._height_cache: dict[int, int] = {}

    def invalidate(self):
        self._height_cache.clear()
        super().invalidate()

    def addItem(self, item):  # noqa: N802 (Qt API)
        self._height_cache.clear()
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        self._height_cache.clear()
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        if width not in self._height_cache:
            self._height_cache[width] = self._do_layout(QRect(0, 0, width, 0), apply=False)
        return self._height_cache[width]

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def take_all(self) -> list[QWidget]:
        """Remove all widgets from the layout without deleting them (for re-ordering)."""
        widgets = [item.widget() for item in self._items if item.widget()]
        self._items = []
        self._height_cache.clear()
        return widgets

    def clear(self) -> None:
        self._height_cache.clear()
        while self._items:
            item = self._items.pop()
            if item.widget():
                item.widget().deleteLater()

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        if self._stretch:
            return self._do_stretched(area, apply) - rect.y() + m.bottom()
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            if item.widget() and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height > 0:
                x = area.x()
                y += line_height + self._spacing
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + m.bottom()

    def _do_stretched(self, area: QRect, apply: bool) -> int:
        items = [i for i in self._items if not (i.widget() and i.widget().isHidden())]
        if not items:
            return area.y()
        # the cards' own minimum width (set for this) - not the text-driven size hint
        base = max((i.widget().minimumWidth() if i.widget() and i.widget().minimumWidth() else i.sizeHint().width())
                   for i in items)
        height = max(i.sizeHint().height() for i in items)
        spacing, width = self._spacing, max(area.width(), 1)
        # fewer items than fit in a row: they keep (about) their size and start left
        columns = max(1, (width + spacing) // (base + spacing))
        item_w = max(1, (width - spacing * (columns - 1)) // columns)
        for index, item in enumerate(items):
            row, column = divmod(index, columns)
            if apply:
                x = area.x() + column * (item_w + spacing)
                w = item_w if column < columns - 1 else area.right() + 1 - x  # last one ends at the edge
                item.setGeometry(QRect(x, area.y() + row * (height + spacing), w, height))
        rows = (len(items) + columns - 1) // columns
        return area.y() + rows * height + (rows - 1) * spacing


class OnScreenKeyboard(QWidget):
    """Simple QWERTY keyboard that types into the attached QLineEdit."""

    submitted = Signal()

    LETTERS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
    SYMBOLS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|"]

    def __init__(self, target: QLineEdit | None = None, parent: QWidget | None = None, compact: bool = False):
        super().__init__(parent)
        self._target = target
        # Pop-up keyboards (search fields) close on B, on a tap elsewhere and when the
        # controller highlight leaves them; permanent ones (lock screen, forms) stay.
        self.dismissable = False
        self._dismisser: _TapOutsideDismisser | None = None
        if compact:
            self.setStyleSheet("QPushButton#key { min-height: 42px; padding: 2px; }")
        self._shift = False
        self._symbols = False
        self._letter_buttons: list[QPushButton] = []
        self._grid = QGridLayout(self)
        self._grid.setSpacing(6)
        self._build()

    def set_target(self, target: QLineEdit) -> None:
        self._target = target

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self.dismissable and self._dismisser is None:
            from PySide6.QtWidgets import QApplication

            self._dismisser = _TapOutsideDismisser(self)
            QApplication.instance().installEventFilter(self._dismisser)

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        if self._dismisser is not None:
            from PySide6.QtWidgets import QApplication

            QApplication.instance().removeEventFilter(self._dismisser)
            self._dismisser.deleteLater()
            self._dismisser = None

    def owns(self, widget: QWidget | None) -> bool:
        """Is ``widget`` part of this keyboard or the field it types into?"""
        while widget is not None:
            if widget is self or widget is self._target:
                return True
            widget = widget.parentWidget()
        return False

    def target(self) -> QLineEdit | None:
        return self._target

    def _rows(self) -> list[str]:
        return self.SYMBOLS if self._symbols else self.LETTERS

    def _build(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._letter_buttons = []
        rows = self._rows()
        for r, row in enumerate(rows):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            if r == 3:
                row_layout.addWidget(self._special("⇧", self.toggle_shift, checkable=True, checked=self._shift))
            for ch in row:
                text = ch.upper() if self._shift else ch
                button = self._key(text, lambda _=False, t=text: self.type_text(t))
                self._letter_buttons.append(button)
                row_layout.addWidget(button)
            if r == 3:
                row_layout.addWidget(self._special("⌫", self.backspace))
            self._grid.addWidget(row_widget, r, 0)
        bottom = QWidget()
        bottom_layout = QHBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)
        bottom_layout.addWidget(self._special("abc" if self._symbols else "#+=", self.toggle_symbols))
        space = self._special("space", lambda: self.type_text(" "))
        space.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bottom_layout.addWidget(space, 1)
        enter = self._special("⏎", self.submitted.emit)
        enter.setObjectName("primary")
        bottom_layout.addWidget(enter)
        self._grid.addWidget(bottom, len(rows), 0)

    def _key(self, text, slot) -> QPushButton:
        button = big_button(text, "key")
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(slot)
        return button

    def _special(self, text, slot, checkable=False, checked=False) -> QPushButton:
        button = big_button(text, "key", checkable=checkable)
        button.setChecked(checked)
        button.clicked.connect(lambda _=False: slot())
        return button

    def type_text(self, text: str) -> None:
        if self._target is not None:
            self._target.insert(text)
        if self._shift and not self._symbols:
            self._shift = False
            self._build()

    def backspace(self) -> None:
        if self._target is not None:
            self._target.backspace()

    def toggle_shift(self) -> None:
        self._shift = not self._shift
        self._build()

    def toggle_symbols(self) -> None:
        self._symbols = not self._symbols
        self._build()

    def key_labels(self) -> list[str]:
        return [b.text() for b in self._letter_buttons]


class _TapOutsideDismisser(QObject):
    """App-wide: a tap outside the keyboard and its text field closes the keyboard.

    The tap itself is not swallowed - the button that was tapped still works.
    """

    def __init__(self, keyboard: "OnScreenKeyboard"):
        super().__init__(keyboard)
        self.keyboard = keyboard

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(obj, QWidget) and obj.isWindow() is False:
            if self.keyboard.isVisible() and not self.keyboard.owns(obj):
                self.keyboard.hide()
        return False


class KeyboardFocusFilter(QObject):
    """Shows ``keyboard`` and points it at whichever watched QLineEdit got touched."""

    def __init__(self, keyboard: OnScreenKeyboard, parent: QObject | None = None):
        super().__init__(parent)
        self.keyboard = keyboard

    def watch(self, edit: QLineEdit) -> None:
        edit.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802
        # Only on a real tap - auto focus at startup must not pop up the keyboard.
        if isinstance(obj, QLineEdit) and event.type() == QEvent.Type.MouseButtonPress:
            self.keyboard.set_target(obj)
            self.keyboard.show()
        return False


def focus_and_reveal(widget: QWidget) -> None:
    """Give ``widget`` the (controller) highlight and scroll it into view."""
    from PySide6.QtCore import QPropertyAnimation
    from PySide6.QtWidgets import QScrollArea

    widget.setFocus(Qt.FocusReason.OtherFocusReason)
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            # a glide still running from earlier would move the list away again
            for anim in parent.verticalScrollBar().findChildren(QPropertyAnimation):
                anim.stop()
            parent.ensureWidgetVisible(widget, 40, 40)
        parent = parent.parentWidget()


def set_status(label: QLabel, text: str, error: bool = False) -> None:
    """Set a status label's text and switch its error styling."""
    label.setText(text)
    label.setProperty("error", error)
    label.style().unpolish(label)
    label.style().polish(label)


class FoldingHeader(QObject):
    """Folds ``header`` away while scrolling down a list and brings it back when scrolling up.

    Gives the game grid / download list more room on small handheld screens.
    """

    DURATION_MS = 180
    START_PX = 60  # don't fold for tiny scrolls near the top
    UP_PX = 12  # scrolling up at least this much unfolds again
    SETTLE_MS = 300  # ignore the scroll jump that folding itself causes
    # Set while the controller navigation scrolls: stepping up through a grid must not
    # unfold (and re-layout) the header on every step - only at the very top.
    programmatic = False

    def __init__(self, scroll_area: QAbstractScrollArea, header: QWidget):
        super().__init__(header)
        from PySide6.QtCore import QElapsedTimer, QEasingCurve, QPropertyAnimation

        self.header = header
        self.scroll_area = scroll_area
        self.bar = scroll_area.verticalScrollBar()
        self._padded: tuple[QWidget, int] | None = None  # (content, its own minimum height)
        self.folded = False
        self.last = self.bar.value()
        self.anchor = self.last
        self.settle = QElapsedTimer()
        self.anim = QPropertyAnimation(header, b"maximumHeight", self)
        self.anim.setDuration(self.DURATION_MS)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._finished)
        self.bar.valueChanged.connect(self._scrolled)
        self.bar.rangeChanged.connect(self._range_changed)

    def _scrolled(self, value: int) -> None:
        if self.settle.isValid() and self.settle.elapsed() < self.SETTLE_MS:
            self.last = self.anchor = value
            return
        if value > self.last:
            self.anchor = value  # lowest point of this downward move
            if not self.folded and value > self.START_PX:
                self.fold()
        elif FoldingHeader.programmatic:
            if self.folded and value <= self.START_PX:
                self.unfold()
            self.anchor = value
        elif value < self.anchor - self.UP_PX or value <= 0:
            if self.folded:
                self.unfold()
            self.anchor = value
        self.last = value

    def fold(self) -> None:
        self._keep_scrollable()
        self.folded = True
        self.settle.start()
        self.anim.stop()
        self.anim.setStartValue(self.header.height())
        self.anim.setEndValue(0)
        self.anim.start()

    def _keep_scrollable(self) -> None:
        """A short list that fits once the header is gone would leave nothing to scroll up
        with - the header could never come back. Some room at the bottom keeps it scrollable."""
        content = getattr(self.scroll_area, "widget", lambda: None)()
        if content is None:
            return
        missing = self.bar.value() + 2 * self.UP_PX + self.header.height() - self.bar.maximum()
        if missing > 0:
            if self._padded is None:
                self._padded = (content, content.minimumHeight())
            content.setMinimumHeight(content.height() + missing)

    def _unpad(self) -> None:
        if self._padded is not None:
            content, height = self._padded
            self._padded = None
            content.setMinimumHeight(height)

    def unfold(self) -> None:
        self._unpad()
        self.folded = False
        self.settle.start()
        self.anim.stop()
        self.header.setMaximumHeight(0)
        self.header.show()
        self.anim.setStartValue(0)
        self.anim.setEndValue(max(self.header.sizeHint().height(), 1))
        self.anim.start()

    def _range_changed(self, _minimum: int, maximum: int) -> None:
        """The list got short while folded (filtered, rotated): no way to scroll up - unfold."""
        from PySide6.QtCore import QAbstractAnimation

        if self.folded and maximum <= 0 and self.anim.state() != QAbstractAnimation.State.Running:
            self.unfold()

    def _finished(self) -> None:
        if self.folded:
            self.header.hide()  # hidden widgets can't get controller focus
            if self.bar.maximum() <= 0:
                self.unfold()
        else:
            self.header.setMaximumHeight(16777215)


class SlidingHeader(QObject):
    """The header lies over the top of a scroll area and slides away with the scrolling - back
    as soon as it scrolls up (like YouTube's top bar).

    Unlike FoldingHeader the list keeps its size: nothing is re-laid out while scrolling, so a
    short list doesn't jump or fight the finger (folding shrank its scroll range under the
    finger). ``spacer`` is the first widget in the scroll content: it keeps the header's room.
    """

    SNAP_MS = 160  # partly shown when scrolling stops: all the way in or out, as it was going
    SNAP_DELAY_MS = 220

    def __init__(self, scroll_area: QAbstractScrollArea, header: QWidget, spacer: QWidget):
        super().__init__(header)
        from PySide6.QtCore import QTimer, QVariantAnimation

        self.scroll_area, self.header, self.spacer = scroll_area, header, spacer
        self.bar = scroll_area.verticalScrollBar()
        # cut off at the list's top edge, like the cards scrolling out
        self.clip = QWidget(scroll_area.parentWidget())
        header.setParent(self.clip)
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # hides what's beneath
        self.offset = 0  # how far it's slid up (0: all there)
        self.last = self.bar.value()
        self.going_up = False  # the last scroll direction decides how a partly shown header snaps
        self.snap_timer = QTimer(self)
        self.snap_timer.setSingleShot(True)
        self.snap_timer.setInterval(self.SNAP_DELAY_MS)
        self.snap_timer.timeout.connect(self._snap)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(self.SNAP_MS)
        self.anim.valueChanged.connect(lambda v: self._set_offset(int(v)))
        self.bar.valueChanged.connect(self._scrolled)
        for watched in (scroll_area, header):
            watched.installEventFilter(self)
        from PySide6.QtWidgets import QApplication

        QApplication.instance().focusChanged.connect(self._focus_changed)
        self.place()

    @property
    def height(self) -> int:
        width = self.scroll_area.width()
        if self.header.hasHeightForWidth():
            return self.header.heightForWidth(width)
        return self.header.sizeHint().height()

    @property
    def hidden(self) -> bool:
        return self.offset >= self.height

    def place(self) -> None:
        area, viewport = self.scroll_area, self.scroll_area.viewport()
        height = self.height
        if self.spacer.height() != height:
            self.spacer.setFixedHeight(height)
        self.offset = max(0, min(self.offset, height))
        top = area.mapTo(area.parentWidget(), viewport.geometry().topLeft())
        shown = self.offset < height
        self.clip.setGeometry(area.x(), top.y(), area.width(), max(1, height - self.offset))
        self.header.setGeometry(0, -self.offset, area.width(), height)
        # slid away completely: out of reach for the controller too
        self.clip.setVisible(shown)
        self.header.setVisible(shown)
        self.clip.raise_()

    def _set_offset(self, offset: int) -> None:
        self.offset = offset
        self.place()

    @property
    def short(self) -> bool:
        """The list scrolls less than the header is high: it just scrolls along like the list
        (sliding back over the cards would cover them for nothing)."""
        return self.bar.maximum() <= self.height

    def _scrolled(self, value: int) -> None:
        delta, self.last = value - self.last, value
        if delta:
            self.going_up = delta < 0
        height = self.height
        if self.short:
            self.anim.stop()
            self._set_offset(max(0, min(value, height)))
            return
        offset = max(0, min(height, self.offset + delta))
        if FoldingHeader.programmatic:
            # controller navigation: never cover the card it just scrolled to
            offset = max(offset, min(value, height)) if delta < 0 else offset
        offset = min(offset, max(0, value))  # at the top it's always all there
        self.anim.stop()
        self._set_offset(offset)
        self.snap_timer.start()

    def _snap(self) -> None:
        viewport = self.scroll_area.viewport()
        if QScroller.hasScroller(viewport) and QScroller.scroller(viewport).state() != QScroller.State.Inactive:
            self.snap_timer.start()  # finger still on it, or still gliding: not under its hands
            return
        height, value = self.height, self.bar.value()
        if self.short or not 0 < self.offset < height:
            return
        # up: all of it back (like YouTube); down: away - near the top only as far as the list went
        self._animate_to(0 if self.going_up else min(height, value))

    def _animate_to(self, target: int) -> None:
        self.anim.stop()
        self.anim.setStartValue(self.offset)
        self.anim.setEndValue(target)
        self.anim.start()

    def show_header(self) -> None:
        if self.offset:
            self._animate_to(0)

    def _focus_changed(self, _old, new) -> None:
        if new is not None and self.header.isAncestorOf(new):
            self.show_header()  # e.g. the controller went up to the search field

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.LayoutRequest):
            self.place()
        return False

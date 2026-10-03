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


def big_button(text: str, object_name: str = "", checkable: bool = False) -> QPushButton:
    button = QPushButton(text)
    if object_name:
        button.setObjectName(object_name)
    button.setCheckable(checkable)
    # Reachable with the controller, but a finger tap doesn't steal focus from text fields.
    button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
    return button


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

    def __init__(self, parent: QWidget | None = None, spacing: int = 20):
        super().__init__(parent)
        self._items = []
        self._spacing = spacing

    def addItem(self, item):  # noqa: N802 (Qt API)
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

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
        return widgets

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            if item.widget():
                item.widget().deleteLater()

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
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


class OnScreenKeyboard(QWidget):
    """Simple QWERTY keyboard that types into the attached QLineEdit."""

    submitted = Signal()

    LETTERS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
    SYMBOLS = ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|"]

    def __init__(self, target: QLineEdit | None = None, parent: QWidget | None = None, compact: bool = False):
        super().__init__(parent)
        self._target = target
        # Pop-up keyboards (search fields) close on "back"; permanent ones stay.
        self.hide_on_back = False
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


def set_status(label: QLabel, text: str, error: bool = False) -> None:
    """Set a status label's text and switch its error styling."""
    label.setText(text)
    label.setProperty("error", error)
    label.style().unpolish(label)
    label.style().polish(label)

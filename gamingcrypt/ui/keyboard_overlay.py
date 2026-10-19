"""The on-screen keyboard opened by its device button (Settings -> Controller -> Device buttons):
anywhere in GamingCrypt, for the text field that's highlighted - or the page's first one.

Docked at the bottom of the window (at the top when the field is down there), steered like the
pop-up keyboards of search fields: B, the button again or a tap elsewhere closes it, ⏎ presses
Enter in the field.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QLineEdit, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import OnScreenKeyboard

MAX_WIDTH = 1200
MARGIN = 16


class _Keys(OnScreenKeyboard):
    hidden = Signal()  # B / a tap elsewhere hides the keys (see navigator): the panel goes too

    def hideEvent(self, event):  # noqa: N802 - Qt API
        super().hideEvent(event)
        self.hidden.emit()


def text_field(root: QWidget) -> QLineEdit | None:
    """The field to type into: the highlighted one, else the first one on the page (top left)."""
    focus = QApplication.focusWidget()
    if _usable(focus) and (focus is root or root.isAncestorOf(focus)):
        return focus
    fields = [w for w in root.findChildren(QLineEdit) if _usable(w)]
    if not fields:
        return None
    return min(fields, key=lambda w: (w.mapTo(root, w.rect().topLeft()).y(), w.mapTo(root, w.rect().topLeft()).x()))


def _usable(w) -> bool:
    return (isinstance(w, QLineEdit) and w.isVisible() and w.isEnabled() and not w.isReadOnly()
            and not isinstance(w.parentWidget(), QComboBox))


def page_keyboard(edit: QLineEdit) -> OnScreenKeyboard | None:
    """The field's own keyboard (search fields, forms), opened as by a tap - None if it has none."""
    pos = QPointF(edit.width() / 2, edit.height() / 2)
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(edit, QMouseEvent(kind, pos, edit.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                                                 Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    for keyboard in edit.window().findChildren(OnScreenKeyboard):
        if keyboard.isVisible() and keyboard.target() is edit and not isinstance(keyboard, _Keys):
            return keyboard
    return None


class KeyboardOverlay(QFrame):
    closed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)
        self.keys = _Keys(compact=True)
        self.keys.dismissable = True
        self.keys.submitted.connect(self.enter)
        self.keys.hidden.connect(self.close_keyboard)
        layout.addWidget(self.keys)
        parent.installEventFilter(self)
        self.hide()

    def target(self) -> QLineEdit | None:
        return self.keys.target()

    def open_for(self, edit: QLineEdit) -> None:
        self.keys.set_target(edit)
        self.keys.show()
        self.place()
        self.show()
        self.raise_()
        first = next((k for k in self.keys.findChildren(QWidget)
                      if k.focusPolicy() & Qt.FocusPolicy.TabFocus and k.isVisible()), None)
        if first is not None:
            first.setFocus(Qt.FocusReason.OtherFocusReason)

    def place(self) -> None:
        parent = self.parentWidget()
        width = min(MAX_WIDTH, parent.width() - 2 * MARGIN)
        height = self.sizeHint().height()
        x = (parent.width() - width) // 2
        y = parent.height() - height - MARGIN
        edit = self.target()
        if edit is not None and edit.isVisible():
            bottom = edit.mapTo(parent, edit.rect().bottomLeft()).y()
            if bottom > y - MARGIN:
                y = MARGIN  # the field is down there: out of its way
        self.setGeometry(x, y, width, height)

    def enter(self) -> None:
        edit = self.target()
        self.close_keyboard()
        if edit is not None:
            for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                QApplication.sendEvent(edit, QKeyEvent(kind, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))

    def close_keyboard(self) -> None:
        if not self.isVisible():
            return
        edit = self.target()
        self.hide()
        if edit is not None and edit.isVisible():
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.closed.emit()

    def gamepad_back(self) -> bool:
        self.close_keyboard()
        return True

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize and self.isVisible():
            self.place()
        return False

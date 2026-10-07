"""Confirmations, all the same way: a small box over the dimmed page with the question, Cancel
(selected first - the safe choice) and the red action. B or a tap beside it cancels.

Instead of "tap again to …" buttons: those were easy to miss, and a second tap meant for
something else could confirm."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button

WIDTH = 620


class Modal(QWidget):
    """Lays ``content`` over ``host`` (dimmed) until it's closed; ``dismissed`` on a tap beside it."""

    dismissed = Signal()

    def __init__(self, host: QWidget, content: QWidget):
        super().__init__(host)
        self.host, self.content = host, content
        outer = QVBoxLayout(self)
        outer.addStretch()
        row = QHBoxLayout()
        row.addStretch()
        content.setFixedWidth(min(WIDTH, max(320, host.width() - 60)))
        row.addWidget(content)
        row.addStretch()
        outer.addLayout(row)
        outer.addStretch()
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        content.show()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
        return False

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 150))

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.content.geometry().contains(event.position().toPoint()):
            self.dismissed.emit()
        event.accept()

    def close_modal(self) -> None:
        self.host.removeEventFilter(self)
        self.hide()
        self.deleteLater()


class ConfirmBox(QFrame):
    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, question: str, action: str, danger: bool = True):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self.question = QLabel(question)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        self.action_button = big_button(action, "danger" if danger else "primary")
        self.action_button.clicked.connect(self.confirmed.emit)
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.action_button)
        layout.addLayout(row)

    def gamepad_back(self) -> bool:
        self.cancelled.emit()
        return True


def show_modal(host: QWidget, content: QWidget, cancel: Callable[[], None]) -> Modal:
    """``content`` (with its own buttons) over ``host``; a tap beside it calls ``cancel``."""
    modal = Modal(host, content)
    modal.dismissed.connect(cancel)
    button = getattr(content, "cancel_button", None)
    if button is not None:
        button.setFocus(Qt.FocusReason.TabFocusReason)  # the safe choice first
    return modal


def ask(host: QWidget, question: str, action: str, on_yes: Callable[[], None], danger: bool = True) -> Modal:
    """A yes / no question: ``on_yes`` runs after the action button; anything else just closes it."""
    box = ConfirmBox(question, action, danger)
    modal = show_modal(host, box, lambda: modal.close_modal())
    box.cancelled.connect(modal.close_modal)
    box.confirmed.connect(lambda: (modal.close_modal(), on_yes()))
    return modal


def open_modal(window: QWidget, on_screen: bool = True) -> Modal | None:
    """The question shown in this window, if any (the controller stays inside it).
    on_screen=False: also one on a page that isn't on screen right now."""
    return next((m for m in window.findChildren(Modal)
                 if (m.isVisible() if on_screen else not m.isHidden())), None)

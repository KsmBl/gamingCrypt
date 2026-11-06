"""Asking for the code of whoever is logged in again - to encrypt a stick with it, or to open an
encrypted stick when GamingCrypt doesn't know it (started again while unlocked).

The code is checked (the app's check: the code that unlocked, see MainWindow.password_for_code) and
turned into the drive's volume password (scrypt, a second or so) - that's what's handed on.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, set_status


class CodeEntry(QWidget):
    """The code's input, checked: ``accepted(password)`` when it's right."""

    accepted = Signal(str)

    def __init__(self, method: str, check: Callable[[str], str | None], parent: QWidget | None = None):
        super().__init__(parent)
        self.check = check
        self.working = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.input = SecretInput(method)
        self.input.secret_entered.connect(self.try_code)
        self.input.invalid.connect(lambda message: set_status(self.status, message, error=True))
        layout.addWidget(self.input, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def focus_first(self) -> None:
        self.input.widget.setFocus(Qt.FocusReason.TabFocusReason)

    def try_code(self, secret: str) -> None:
        if self.working:
            return
        self.working = True
        set_status(self.status, "Checking…")
        check = self.check
        run_async(lambda: check(secret), self._checked, self._failed, owner=self)

    def _checked(self, password: str | None) -> None:
        self.working = False
        if not password:
            self.input.clear(error=True)
            set_status(self.status, "Wrong code - try again", error=True)
            return
        set_status(self.status, "")
        self.accepted.emit(password)

    def _failed(self, exc) -> None:
        self.working = False
        self.input.clear(error=True)
        set_status(self.status, str(exc), error=True)


class CodePrompt(QFrame):
    """A box over the screen: the code, then ``accepted(password)``."""

    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self, title: str, text: str, method: str, check: Callable[[str], str | None], parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("section")
        layout.addWidget(heading)
        self.question = QLabel(f"{text} Enter your {METHOD_LABELS.get(method, 'code')}.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.entry = CodeEntry(method, check)
        self.entry.accepted.connect(self.accepted.emit)
        layout.addWidget(self.entry)
        row = FlowLayout(spacing=12)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)

    @property
    def working(self) -> bool:
        return self.entry.working

    def focus_first(self) -> None:
        self.entry.focus_first()

    def cancel(self) -> None:
        if not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True

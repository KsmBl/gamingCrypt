"""Asking for the code of whoever is logged in again - to encrypt a stick with it, or to open an
encrypted stick when GamingCrypt doesn't know it (started again while unlocked).

The whole screen, as the lock screen is: its title, "Enter your PIN", the same PIN pad, swipe pattern,
5x5 dots or password - as big as there - and Cancel. The code is checked (the app's check: the code
that unlocked, see MainWindow.password_for_code) and turned into the drive's volume password (scrypt,
a second or so) - that's what's handed on.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.modal import Modal
from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status


def fit_pad(screen: QWidget, secret_input) -> None:
    """The lock screen's 5x5 dots or swipe pattern as big as there's room for on this screen - their
    own size where there is (400 / 360 px), smaller on a 720 px high one, where they didn't fit."""
    from gamingcrypt.ui.secret_input import DotGridPad, PatternWidget, SIDE_BUTTON, SIDE_GAP

    pad = getattr(secret_input, "widget", None)
    target = pad.canvas if isinstance(pad, DotGridPad) else pad if isinstance(pad, PatternWidget) else None
    layout = screen.layout()
    if target is None or layout is None or not screen.height():
        return
    largest = 400 if isinstance(pad, DotGridPad) else 360
    others = layout.minimumSize().height() - secret_input.minimumSizeHint().height()
    around = secret_input.minimumSizeHint().height() - target.minimumHeight()  # (the 5x5's field, its hint)
    side = screen.height() - others - around
    margins = layout.contentsMargins()
    width = screen.width() - margins.left() - margins.right()
    if isinstance(pad, DotGridPad):
        width -= 2 * (SIDE_BUTTON.width() + SIDE_GAP) + 20  # (⌫ and ✓ beside the dots)
    side = max(220, min(largest, side, width))
    if target.minimumWidth() != side:
        target.setMinimumSize(side, side)


class CodeEntry(QWidget):
    """The code's input - the lock screen's - checked: ``accepted(password)`` when it's right."""

    accepted = Signal(str)

    def __init__(self, method: str, check: Callable[[str], str | None], parent: QWidget | None = None):
        super().__init__(parent)
        self.check = check
        self.working = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.input = SecretInput(method, hint=True)  # (as on the lock screen: the controller's buttons too)
        self.input.secret_entered.connect(self.try_code)
        self.input.invalid.connect(lambda message: self.say(message, error=True))
        layout.addWidget(self.input, 1)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

    def say(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)

    def focus_first(self) -> None:
        self.input.widget.setFocus(Qt.FocusReason.TabFocusReason)

    def try_code(self, secret: str) -> None:
        if self.working:
            return
        self.working = True
        self.say("Checking…")
        check = self.check
        run_async(lambda: check(secret), self._checked, self._failed, owner=self)

    def _checked(self, password: str | None) -> None:
        self.working = False
        if not password:
            self.input.clear(error=True)
            self.say("Wrong code - try again", error=True)
            return
        self.say("")
        self.accepted.emit(password)

    def _failed(self, exc) -> None:
        self.working = False
        self.input.clear(error=True)
        self.say(str(exc), error=True)


class CodeScreen(QWidget):
    """The whole screen, as the lock screen: a title, what it's for, the code's input, Cancel."""

    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self, title: str, text: str, method: str, check: Callable[[str], str | None], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # (the theme: a whole screen)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.subtitle = QLabel(f"Enter your {METHOD_LABELS.get(method, 'code')}")
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)
        self.question = QLabel(text)
        self.question.setObjectName("cardMeta")
        self.question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.entry = CodeEntry(method, check)
        self.entry.accepted.connect(self.accepted.emit)
        layout.addWidget(self.entry, 1)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        row.addStretch()
        layout.addLayout(row)

    @property
    def working(self) -> bool:
        return self.entry.working

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        fit_pad(self, self.entry.input)

    def focus_first(self) -> None:
        self.entry.focus_first()

    def cancel(self) -> None:
        if not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True


class FullScreen(Modal):
    """A Modal (the controller stays in it, LB / RB don't switch tabs) that is the whole screen."""

    def __init__(self, host: QWidget, content: QWidget):
        QWidget.__init__(self, host)
        self.host, self.content = host, content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        host.installEventFilter(self)
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        content.show()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.host.rect())
        return False

    def paintEvent(self, _event) -> None:  # noqa: N802 - (the content paints the screen)
        pass

    def mousePressEvent(self, event) -> None:  # noqa: N802 - (nothing beside it to tap)
        event.accept()


def ask_code(widget: QWidget, title: str, text: str, method: str, check: Callable[[str], str | None],
             accepted: Callable[[str], None], cancelled: Callable[[], None] | None = None) -> CodeScreen:
    """The code screen over the whole window; it closes itself - accepted(password) / cancelled()."""
    screen = CodeScreen(title, text, method, check)
    holder = FullScreen(widget.window() or widget, screen)

    def close() -> None:
        holder.close_modal()

    screen.accepted.connect(lambda password: (close(), accepted(password)))
    screen.cancelled.connect(lambda: (close(), cancelled() if cancelled is not None else None))
    screen.holder = holder
    screen.focus_first()
    return screen

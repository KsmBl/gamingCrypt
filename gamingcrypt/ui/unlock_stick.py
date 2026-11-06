"""Settings → Storage → Unlock: an encrypted stick that doesn't open with today's code (it was
encrypted while the admin had another one, or on another device). Opened once with that code -
then it gets today's, and opens by itself from then on (stick_crypt.py)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from gamingcrypt.system import stick_crypt
from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, set_status


def methods_of(volume: str) -> list[str]:
    """The kinds of code that open it: the admin's first, then the users' (its sidecar)."""
    from gamingcrypt.unlock import sidecar

    info = sidecar.read_sidecar(volume) or {}
    found = [info.get("method") or "password"]
    for user in info.get("users") or []:
        if user.get("slot") and user.get("method") in METHOD_LABELS and user["method"] not in found:
            found.append(user["method"])
    return [m for m in found if m in METHOD_LABELS] or ["password"]


def unlock(stick, secret: str, config: dict | None = None, factory=None) -> str:
    """Opened with that code, and given today's password where it's known (config: the app's - for
    the sidecar written anew). What happened."""
    volume = stick.container
    old = stick_crypt.password_from_code(volume, secret)
    if old is None:
        raise stick_crypt.CryptError("That code doesn't fit this stick")
    opened = stick_crypt.open_stick(stick, old, factory)
    if opened.problem:
        raise stick_crypt.CryptError("That code doesn't fit this stick" if opened.problem == stick_crypt.EARLIER
                                     else opened.problem)
    new = stick_crypt.keys.password
    if new and new != old and config is not None:
        if stick_crypt.rekey(volume, old, new, config["unlock"], config.get("users"), factory):
            return f"{stick.name} is open - and opens with today's code from now on"
    return f"{stick.name} is open"


class UnlockStick(QFrame):
    unlocked = Signal(str)  # what happened
    cancelled = Signal()

    def __init__(self, stick, config: dict | None = None, factory=None, parent=None):
        super().__init__(parent)
        self.stick, self.config, self.factory = stick, config, factory
        self.working = False
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel(f"🔓 Unlock {stick.name}")
        title.setObjectName("section")
        layout.addWidget(title)
        self.question = QLabel("It was encrypted with another code - an earlier one of yours, or another device's. "
                               "Enter that code: it gets today's code then, and opens by itself from then on.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.methods = methods_of(stick.container)
        self.method_row = FlowLayout(spacing=12)
        self.method_buttons = {}
        for method in self.methods if len(self.methods) > 1 else []:
            button = big_button(METHOD_LABELS[method], checkable=True)
            button.clicked.connect(lambda _c=False, m=method: self.use(m))
            self.method_row.addWidget(button)
            self.method_buttons[method] = button
        layout.addLayout(self.method_row)
        self.input_holder = QVBoxLayout()
        layout.addLayout(self.input_holder)
        self.input = None
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = FlowLayout(spacing=12)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.use(self.methods[0])

    def use(self, method: str) -> None:
        if self.input is not None:
            self.input.deleteLater()
        for name, button in self.method_buttons.items():
            button.setChecked(name == method)
        self.input = SecretInput(method)
        self.input.secret_entered.connect(self.try_code)
        self.input.invalid.connect(lambda message: set_status(self.status, message, error=True))
        self.input_holder.addWidget(self.input, alignment=Qt.AlignmentFlag.AlignHCenter)

    def focus_first(self) -> None:
        self.input.widget.setFocus(Qt.FocusReason.TabFocusReason)

    def try_code(self, secret: str) -> None:
        if self.working:
            return
        self.working = True
        set_status(self.status, "Opening it… (this takes a few seconds)")
        stick, config, factory = self.stick, self.config, self.factory
        run_async(lambda: unlock(stick, secret, config, factory), self._done, self._failed, owner=self)

    def _done(self, message: str) -> None:
        self.working = False
        self.unlocked.emit(message)

    def _failed(self, exc) -> None:
        self.working = False
        self.input.clear(error=True)
        set_status(self.status, str(exc), error=True)

    def cancel(self) -> None:
        if not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True

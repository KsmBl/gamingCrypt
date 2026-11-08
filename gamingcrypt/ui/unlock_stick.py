"""Settings → Storage → Unlock: an encrypted stick that doesn't open with today's code (it was
encrypted while the admin had another one, or on another device). Opened once with that code -
then it gets today's, and opens by itself from then on (stick_crypt.py)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.system import stick_crypt
from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status


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


class UnlockStick(QWidget):
    """The whole screen, as the lock screen: the kinds of code that opened it (when there are several:
    the admin's, the users'), its input, Cancel."""

    unlocked = Signal(str)  # what happened
    cancelled = Signal()

    def __init__(self, stick, config: dict | None = None, factory=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # (the theme: a whole screen)
        self.stick, self.config, self.factory = stick, config, factory
        self.working = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        title = QLabel(f"🔓 Unlock {stick.name}")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.methods = methods_of(stick.container)
        self.method_buttons = {}
        chooser = QHBoxLayout()
        chooser.addStretch()
        for method in self.methods if len(self.methods) > 1 else []:
            button = big_button(METHOD_LABELS[method], choice=True)
            button.clicked.connect(lambda _c=False, m=method: self.use(m))
            chooser.addWidget(button)
            self.method_buttons[method] = button
        chooser.addStretch()
        layout.addLayout(chooser)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)
        self.question = QLabel("It was encrypted with another code - an earlier one of yours, or another device's. "
                               "Enter that code: it gets today's code then, and opens by itself from then on.")
        self.question.setObjectName("cardMeta")
        self.question.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.input_box = QVBoxLayout()
        layout.addLayout(self.input_box, 1)
        self.input = None
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        row.addStretch()
        layout.addLayout(row)
        self.use(self.methods[0])

    def use(self, method: str) -> None:
        if self.input is not None:
            self.input_box.removeWidget(self.input)
            self.input.deleteLater()
        for name, button in self.method_buttons.items():
            button.setChecked(name == method)
        self.input = SecretInput(method, hint=True)  # (the lock screen's)
        self.input.secret_entered.connect(self.try_code)
        self.input.invalid.connect(lambda message: set_status(self.status, message, error=True))
        self.input_box.addWidget(self.input, 1)
        self.subtitle.setText(f"Enter its {METHOD_LABELS[method]}")
        if self.height():
            from gamingcrypt.ui.code_prompt import fit_pad

            fit_pad(self, self.input)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        from gamingcrypt.ui.code_prompt import fit_pad

        fit_pad(self, self.input)

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

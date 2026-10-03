"""First-start setup and "reset authentication": choose an unlock method and
re-key the VeraCrypt volume so that the new PIN / password / pattern opens it."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import KeyboardFocusFilter, OnScreenKeyboard, big_button, set_status
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker

UnlockerFactory = Callable[[dict], VeraCryptUnlocker]


def _label(text: str, name: str = "subtitle") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label


class AuthSetupWizard(QWidget):
    """Steps: [volume] -> current secret -> choose method -> new secret -> confirm -> apply.

    ``first_start`` adds the volume step and asks for the container's current
    password; otherwise the current secret is entered with the configured method.
    """

    completed = Signal()
    cancelled = Signal()

    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory: UnlockerFactory = VeraCryptUnlocker.from_config,
        first_start: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.first_start = first_start
        self.busy = False
        self.current_secret = ""
        self.new_method = ""
        self.new_secret = ""
        unlock = config["unlock"]
        self.volume = unlock.get("volume", "")
        self.mount_point = unlock.get("mount_point", "")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        self.title = _label("Welcome to GamingCrypt" if first_start else "Reset authentication", "title")
        layout.addWidget(self.title)
        self.hint = _label("")
        layout.addWidget(self.hint)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.volume_page = self._build_volume_page()
        self.method_page = self._build_method_page()
        self.stack.addWidget(self.volume_page)
        self.stack.addWidget(self.method_page)
        self.input_page: SecretInput | None = None

        self.status = _label("", "status")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.cancel_button = big_button("Skip setup" if first_start else "Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        if first_start:
            self.show_volume_step()
        else:
            self.show_current_step()

    # pages ------------------------------------------------------------------
    def _build_volume_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        self.volume_edit = QLineEdit(self.volume)
        self.volume_edit.setPlaceholderText("VeraCrypt volume, e.g. /dev/sda3 or /home/me/games.vc")
        self.mount_edit = QLineEdit(self.mount_point)
        self.mount_edit.setPlaceholderText("Mount point (optional), e.g. /mnt/games")
        v.addWidget(self.volume_edit)
        v.addWidget(self.mount_edit)
        self.volume_keyboard = OnScreenKeyboard(self.volume_edit)
        self._focus_filter = KeyboardFocusFilter(self.volume_keyboard, self)
        self._focus_filter.watch(self.volume_edit)
        self._focus_filter.watch(self.mount_edit)
        self.volume_keyboard.submitted.connect(self._volume_next)
        v.addWidget(self.volume_keyboard)
        next_button = big_button("Next", "primary")
        next_button.clicked.connect(self._volume_next)
        v.addWidget(next_button, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _build_method_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)
        h.addStretch()
        self.method_buttons = {}
        for method, label in METHOD_LABELS.items():
            button = big_button(label)
            button.setMinimumSize(220, 160)
            button.clicked.connect(lambda _=False, m=method: self.choose_method(m))
            self.method_buttons[method] = button
            h.addWidget(button)
        h.addStretch()
        return page

    def _show_input(self, method: str, hint: str, handler) -> None:
        if self.input_page is not None:
            self.stack.removeWidget(self.input_page)
            self.input_page.deleteLater()
        self.input_page = SecretInput(method)
        self.input_page.secret_entered.connect(handler)
        self.input_page.invalid.connect(lambda msg: set_status(self.status, msg, error=True))
        self.stack.addWidget(self.input_page)
        self.stack.setCurrentWidget(self.input_page)
        self.hint.setText(hint)

    # steps ------------------------------------------------------------------
    def show_volume_step(self) -> None:
        self.step = "volume"
        self.hint.setText("Which VeraCrypt volume holds your games?")
        self.stack.setCurrentWidget(self.volume_page)

    def _volume_next(self) -> None:
        self.submit_volume(self.volume_edit.text(), self.mount_edit.text())

    def submit_volume(self, volume: str, mount_point: str) -> None:
        volume = volume.strip()
        if not volume:
            set_status(self.status, "Please enter the path of the volume", error=True)
            return
        self.volume = volume
        self.mount_point = mount_point.strip()
        set_status(self.status, "")
        self.show_current_step()

    def show_current_step(self) -> None:
        self.step = "current"
        if self.first_start or not self.config["unlock"].get("method"):
            method, hint = "password", "Enter the current password of the volume"
        else:
            method = self.config["unlock"]["method"]
            hint = f"Enter your current {METHOD_LABELS.get(method, 'password')}"
        self._show_input(method, hint, self.submit_current)

    def submit_current(self, secret: str) -> None:
        self.current_secret = secret
        set_status(self.status, "")
        self.show_method_step()

    def show_method_step(self) -> None:
        self.step = "method"
        self.hint.setText("How do you want to unlock from now on?")
        self.stack.setCurrentWidget(self.method_page)

    def choose_method(self, method: str) -> None:
        self.new_method = method
        self.step = "new"
        self._show_input(method, f"Choose your new {METHOD_LABELS[method]}", self.submit_new)

    def submit_new(self, secret: str) -> None:
        self.new_secret = secret
        self.step = "confirm"
        set_status(self.status, "")
        self._show_input(self.new_method, f"Repeat your new {METHOD_LABELS[self.new_method]}", self.submit_confirm)

    def submit_confirm(self, secret: str) -> None:
        if secret != self.new_secret:
            set_status(self.status, "That didn't match - try again", error=True)
            self.choose_method(self.new_method)
            return
        self.apply()

    def apply(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.step = "apply"
        set_status(self.status, "Updating the volume… this can take a few seconds")
        unlock_cfg = dict(self.config["unlock"], volume=self.volume, mount_point=self.mount_point)
        unlocker = self.unlocker_factory(unlock_cfg)
        current, new = self.current_secret, self.new_secret
        run_async(
            lambda: unlocker.change_password(current, new),
            self._applied,
            lambda exc: self._applied(UnlockResult(False, str(exc))),
        )

    def _applied(self, result: UnlockResult) -> None:
        self.busy = False
        if not result.success:
            set_status(self.status, result.message, error=True)
            self.show_current_step()
            return
        unlock = self.config["unlock"]
        unlock["method"] = self.new_method
        unlock["volume"] = self.volume
        unlock["mount_point"] = self.mount_point
        self.save(self.config)
        set_status(self.status, "Done")
        self.completed.emit()

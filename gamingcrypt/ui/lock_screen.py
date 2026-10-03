"""Start screen: unlock the VeraCrypt volume with the configured method."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker


class LockScreen(QWidget):
    """Emits ``unlocked`` once the volume was mounted successfully."""

    unlocked = Signal()

    def __init__(self, unlocker: VeraCryptUnlocker, method: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.unlocker = unlocker
        self.busy = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        title = QLabel("🔒 GamingCrypt")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self.input = SecretInput(method)
        self.method = self.input.method
        subtitle = QLabel(f"Enter your {METHOD_LABELS[self.method]}")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        self.input.secret_entered.connect(self._attempt)
        self.input.invalid.connect(lambda msg: set_status(self.status, msg, error=True))
        layout.addWidget(self.input, 1)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.skip_button = big_button("Continue without unlocking")
        self.skip_button.clicked.connect(self.unlocked.emit)
        layout.addWidget(self.skip_button, alignment=Qt.AlignmentFlag.AlignCenter)
        if unlocker.configured:
            self.skip_button.hide()
        else:
            set_status(self.status, "No VeraCrypt volume configured", error=True)

    def _attempt(self, secret: str) -> None:
        if self.busy:
            return
        self.busy = True
        set_status(self.status, "Unlocking…")
        run_async(
            lambda: self.unlocker.unlock(secret),
            self._finished,
            lambda exc: self._finished(UnlockResult(False, str(exc))),
        )

    def _finished(self, result: UnlockResult) -> None:
        self.busy = False
        if result.success:
            set_status(self.status, result.message)
            self.input.clear()
            self.unlocked.emit()
        else:
            set_status(self.status, result.message, error=True)
            self.input.clear(error=True)

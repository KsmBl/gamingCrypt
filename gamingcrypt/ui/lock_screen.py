"""Start screen: unlock the VeraCrypt volume with the configured method."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker


class LockScreen(QWidget):
    """Emits ``unlocked`` once the volume was mounted successfully."""

    unlocked = Signal()
    power_requested = Signal(str)  # "shutdown" / "restart" / "boot:<UEFI entry>"

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
        self.subtitle = QLabel(f"Enter your {METHOD_LABELS[self.method]}")
        self.subtitle.setObjectName("subtitle")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.subtitle)
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

        # power: without unlocking (e.g. to start Windows instead)
        power = QHBoxLayout()
        power.addStretch()
        self.shutdown_button = big_button("⏻  Shut down")
        self.restart_button = big_button("↻  Restart")
        self.windows_button = big_button("⊞  Restart into Windows")
        self.shutdown_button.clicked.connect(lambda: self.power_requested.emit("shutdown"))
        self.restart_button.clicked.connect(lambda: self.power_requested.emit("restart"))
        self.windows_button.clicked.connect(self._boot_other)
        for button in (self.shutdown_button, self.restart_button, self.windows_button):
            power.addWidget(button)
        power.addStretch()
        layout.addLayout(power)
        self.other_system = None
        self.windows_button.hide()  # until another system was found

    def set_systems(self, entries) -> None:
        """Offer the first other system (Windows preferred) - see system/boot.py."""
        entries = sorted(entries, key=lambda e: not e.windows)
        self.other_system = entries[0] if entries else None
        if self.other_system is not None:
            self.windows_button.setText(("⊞  " if self.other_system.windows else "↻  ")
                                        + f"Restart into {self.other_system.name}")
        self.windows_button.setVisible(self.other_system is not None)

    def _boot_other(self) -> None:
        if self.other_system is not None:
            self.power_requested.emit(f"boot:{self.other_system.num}")

    def show_error(self, message: str) -> None:
        set_status(self.status, message, error=True)

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

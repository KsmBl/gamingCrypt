"""Settings tab. For now: show the security setup and reset the unlock method."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui.auth_setup import AuthSetupWizard, UnlockerFactory
from gamingcrypt.ui.secret_input import METHOD_LABELS
from gamingcrypt.ui.widgets import big_button, set_status
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker


class SettingsTab(QStackedWidget):
    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory: UnlockerFactory = VeraCryptUnlocker.from_config,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.wizard: AuthSetupWizard | None = None

        self.overview = QWidget()
        layout = QVBoxLayout(self.overview)
        layout.setContentsMargins(40, 30, 40, 30)
        heading = QLabel("Security")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.method_label = QLabel()
        self.method_label.setObjectName("detailMeta")
        self.volume_label = QLabel()
        self.volume_label.setObjectName("detailMeta")
        self.volume_label.setWordWrap(True)
        layout.addWidget(self.method_label)
        layout.addWidget(self.volume_label)
        self.reset_button = big_button("Reset authentication method", "primary")
        self.reset_button.clicked.connect(self.start_reset)
        layout.addWidget(self.reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        layout.addStretch()
        more = QLabel("More settings coming soon")
        more.setObjectName("subtitle")
        more.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(more)
        layout.addStretch()
        self.addWidget(self.overview)
        self.refresh()

    def refresh(self) -> None:
        unlock = self.config["unlock"]
        method = METHOD_LABELS.get(unlock.get("method", ""), "not set")
        self.method_label.setText(f"Unlock method: {method}")
        self.volume_label.setText(f"Volume: {unlock.get('volume') or 'not configured'}")

    def start_reset(self) -> None:
        unlock = self.config["unlock"]
        first_start = not unlock.get("volume") or not unlock.get("method")
        self.wizard = AuthSetupWizard(self.config, self.save, self.unlocker_factory, first_start=first_start)
        self.wizard.completed.connect(lambda: self._close_wizard("Unlock method changed"))
        self.wizard.cancelled.connect(lambda: self._close_wizard(""))
        self.addWidget(self.wizard)
        self.setCurrentWidget(self.wizard)

    def _close_wizard(self, message: str) -> None:
        self.setCurrentWidget(self.overview)
        if self.wizard is not None:
            self.removeWidget(self.wizard)
            self.wizard.deleteLater()
            self.wizard = None
        self.refresh()
        set_status(self.status, message)

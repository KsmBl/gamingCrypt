"""Settings -> Updates: check GitHub, see what's new, update with one tap."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from gamingcrypt import __version__
from gamingcrypt.system import helper_status
from gamingcrypt.system.updater import Updater, finish_install
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button, set_status

MAX_LINES = 10


class UpdatesPage(QWidget):
    def __init__(self, updater: Updater | None = None, restart: Callable[[], None] | None = None,
                 parent: QWidget | None = None, helper_outdated: Callable[[], bool] = helper_status.outdated,
                 finisher: Callable = finish_install):
        super().__init__(parent)
        self.updater = updater or Updater()
        self.restart = restart
        self.helper_outdated = helper_outdated
        self.finisher = finisher
        self.info = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.version = QLabel(f"GamingCrypt {__version__}")
        self.version.setObjectName("cardTitle")
        layout.addWidget(self.version)
        self.changes = QLabel("")
        self.changes.setObjectName("detailMeta")
        self.changes.setWordWrap(True)
        layout.addWidget(self.changes)
        row = QHBoxLayout()
        self.check_button = big_button("↻  Check for updates")
        self.check_button.clicked.connect(self.check)
        self.update_button = big_button("⬇  Update now", "primary")
        self.update_button.clicked.connect(self.update_now)
        self.update_button.hide()
        row.addWidget(self.check_button)
        row.addWidget(self.update_button)
        row.addStretch()
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        # parts that need root (helper, gaming session, rules): finish with the password once
        self.finish_box = QFrame()
        self.finish_box.setObjectName("card")
        box = QVBoxLayout(self.finish_box)
        box.setContentsMargins(22, 16, 22, 16)
        self.finish_text = QLabel("To finish the update, GamingCrypt needs your password once (it installs the "
                                  "helper, the gaming session and device rules). It isn't stored.")
        self.finish_text.setWordWrap(True)
        box.addWidget(self.finish_text)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Your password")
        box.addWidget(self.password)
        self.keyboard = OnScreenKeyboard(self.password, compact=True)
        self.keyboard.submitted.connect(self.finish)
        box.addWidget(self.keyboard)
        self.finish_button = big_button("Finish update", "primary")
        self.finish_button.clicked.connect(self.finish)
        box.addWidget(self.finish_button)
        self.finish_box.hide()
        layout.addWidget(self.finish_box)
        self.busy = False

    def check(self) -> None:
        if self.busy:
            return
        self._busy(True, "Checking…")
        run_async(self.updater.check, self.show_info, lambda exc: self._failed(str(exc)), owner=self)
        run_async(self.helper_outdated, lambda old: self.finish_box.setVisible(bool(old) or self.finish_box.isVisible()),
                  lambda _e: None, owner=self)

    def show_info(self, info) -> None:
        self._busy(False, info.message, error=not info.ok)
        self.info = info
        lines = info.changes[:MAX_LINES]
        text = "\n".join(f"• {line}" for line in lines)
        if len(info.changes) > len(lines):
            text += f"\n… and {len(info.changes) - len(lines)} more"
        self.changes.setText(text)
        self.update_button.setVisible(info.available)

    def update_now(self) -> None:
        if self.busy or self.info is None or not self.info.available:
            return
        self._busy(True, "Updating - this takes a minute…")
        self.update_button.setEnabled(False)
        run_async(self.updater.apply, self._applied, lambda exc: self._failed(str(exc)), owner=self)

    def _applied(self, result) -> None:
        ok, message, root_parts = result
        self.update_button.setEnabled(True)
        if not ok:
            self._failed(message)
            return
        self.update_button.hide()
        text = "Updated."
        if root_parts:
            self.finish_box.show()  # helper / session changed: finish with the password, then restart
            self._busy(False, "Updated - finish it below with your password.")
            return
        if self.restart is not None:
            self._busy(False, text + " Restarting…")
            self.restart()
        else:
            self._busy(False, text + " Restart GamingCrypt to use the new version.")

    def finish(self) -> None:
        password = self.password.text()
        if self.busy or not password:
            return
        self._busy(True, "Finishing the update - this takes a minute…")
        self.finish_button.setEnabled(False)
        source = self.updater.source
        run_async(lambda: self.finisher(source, password), self._finished, lambda exc: self._failed(str(exc)),
                  owner=self)

    def _finished(self, result) -> None:
        ok, message = result
        self.finish_button.setEnabled(True)
        self.password.clear()
        if not ok:
            self._failed(message)
            return
        self.finish_box.hide()
        if self.restart is not None:
            self._busy(False, "Update finished. Restarting…")
            self.restart()
        else:
            self._busy(False, "Update finished. Restart GamingCrypt to use the new version.")

    def _failed(self, message: str) -> None:
        self._busy(False, message, error=True)

    def _busy(self, busy: bool, text: str, error: bool = False) -> None:
        self.busy = busy
        self.check_button.setEnabled(not busy)
        set_status(self.status, text, error=error)

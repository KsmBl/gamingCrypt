"""Settings tab. For now: show the security setup and reset the unlock method."""

from __future__ import annotations

from typing import Callable

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.steam import accounts, library

from gamingcrypt.ui.auth_setup import AuthSetupWizard, UnlockerFactory
from gamingcrypt.ui.secret_input import METHOD_LABELS
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.system_settings import AudioSection, DisplaySection, PowerSection
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button, enable_touch_scroll, set_status

API_KEY_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


class ApiKeyPage(QWidget):
    """Enter the Steam Web API key with the on-screen keyboard."""

    def __init__(self, tab: "SettingsTab"):
        super().__init__()
        self.tab = tab
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        title = QLabel("Steam Web API key")
        title.setObjectName("title")
        layout.addWidget(title)
        hint = QLabel("Lets GamingCrypt list every game you own, not only installed ones.\n"
                      "Get your key at steamcommunity.com/dev/apikey (any domain name works).")
        hint.setObjectName("detailMeta")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.edit = QLineEdit(tab.config["steam"].get("api_key", ""))
        self.edit.setPlaceholderText("32 characters, e.g. 0123456789ABCDEF0123456789ABCDEF")
        layout.addWidget(self.edit)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.keyboard = OnScreenKeyboard(self.edit, compact=True)
        self.keyboard.submitted.connect(self.save)
        layout.addWidget(self.keyboard)
        buttons = QHBoxLayout()
        cancel = big_button("Cancel")
        cancel.clicked.connect(lambda: tab.close_page(""))
        buttons.addWidget(cancel)
        buttons.addStretch()
        save = big_button("Save", "primary")
        save.clicked.connect(self.save)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def save(self) -> None:
        key = self.edit.text().strip()
        if key and not API_KEY_RE.match(key):
            set_status(self.status, "That doesn't look like a Steam API key (32 letters/digits 0-9, A-F)", error=True)
            return
        self.tab.config["steam"]["api_key"] = key
        self.tab.save(self.tab.config)
        self.tab.close_page("Steam API key saved" if key else "Steam API key removed")
from gamingcrypt.unlock import kdf
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker


class SettingsTab(QStackedWidget):
    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory: UnlockerFactory = VeraCryptUnlocker.from_config,
        system: SystemControls | None = None,
        steam_service=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.system = system if system is not None else SystemControls()
        self._steam_service = steam_service
        self.switching = False
        self.wizard: AuthSetupWizard | None = None

        self.overview = QScrollArea()
        self.overview.setWidgetResizable(True)
        self.overview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(self.overview)
        content = QWidget()
        self.overview.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(14)
        self.display_section = DisplaySection(self.system, config, save)
        self.power_section = PowerSection(self.system, config, save)
        self.audio_section = AudioSection(self.system)
        for section in (self.display_section, self.power_section, self.audio_section):
            layout.addWidget(section)
        heading = QLabel("Security")
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.method_label = QLabel()
        self.method_label.setObjectName("detailMeta")
        self.volume_label = QLabel()
        self.volume_label.setObjectName("detailMeta")
        self.volume_label.setWordWrap(True)
        self.kdf_label = QLabel()
        self.kdf_label.setObjectName("detailMeta")
        self.kdf_label.setWordWrap(True)
        layout.addWidget(self.method_label)
        layout.addWidget(self.volume_label)
        layout.addWidget(self.kdf_label)
        self.reset_button = big_button("Reset authentication method", "primary")
        self.reset_button.clicked.connect(self.start_reset)
        layout.addWidget(self.reset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        steam_heading = QLabel("Steam")
        steam_heading.setObjectName("title")
        layout.addWidget(steam_heading)
        self.account_label = QLabel()
        self.account_label.setObjectName("detailMeta")
        layout.addWidget(self.account_label)
        self.accounts_box = QVBoxLayout()
        layout.addLayout(self.accounts_box)
        self.account_buttons: dict[str, object] = {}
        self.api_key_label = QLabel()
        self.api_key_label.setObjectName("detailMeta")
        layout.addWidget(self.api_key_label)
        self.api_key_button = big_button("Set Steam API key")
        self.api_key_button.clicked.connect(self.edit_api_key)
        layout.addWidget(self.api_key_button, alignment=Qt.AlignmentFlag.AlignLeft)
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
        text = f"Key derivation: {kdf.describe(unlock.get('kdf'))}"
        if unlock.get("kdf"):
            text += "\nBack up ~/.config/gamingcrypt/config.json - its salt is needed to unlock the volume."
        self.kdf_label.setText(text)
        steam = self.config["steam"]
        root = library.find_steam_root(steam.get("root", ""))
        found = accounts.list_accounts(root)
        if root is None:
            self.account_label.setText("Steam: not found on this device")
        elif not found:
            self.account_label.setText("Steam account: not detected - log in to Steam once")
        elif len(found) == 1:
            self.account_label.setText(f"Steam account: {found[0].persona}")
        else:
            self.account_label.setText(f"Steam accounts on this device: {len(found)}")
        self._fill_accounts(found if len(found) > 1 else [])
        has_key = bool(steam.get("api_key"))
        self.api_key_label.setText("Web API key: set - your whole library is shown" if has_key
                                   else "Web API key: not set - only installed games are shown")
        self.api_key_button.setText("Change Steam API key" if has_key else "Set Steam API key")

    def start_reset(self) -> None:
        unlock = self.config["unlock"]
        first_start = not unlock.get("volume") or not unlock.get("method")
        self.wizard = AuthSetupWizard(self.config, self.save, self.unlocker_factory, first_start=first_start)
        self.wizard.completed.connect(lambda: self._close_wizard("Unlock method changed"))
        self.wizard.cancelled.connect(lambda: self._close_wizard(""))
        self.addWidget(self.wizard)
        self.setCurrentWidget(self.wizard)

    @property
    def steam(self):
        if self._steam_service is None:
            from gamingcrypt.config import cache_dir
            from gamingcrypt.steam.service import SteamService

            self._steam_service = SteamService(self.config["steam"], cache_dir())
        return self._steam_service

    def _fill_accounts(self, found: list) -> None:
        while self.accounts_box.count():
            item = self.accounts_box.takeAt(0)
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        self.account_buttons = {}
        for account in found:
            row = QHBoxLayout()
            text = account.persona + ("  ·  active" if account.most_recent else "")
            if not account.remembers_password:
                text += "  (password needed)"
            label = QLabel(text)
            label.setObjectName("cardTitle" if account.most_recent else "detailMeta")
            row.addWidget(label, 1)
            if not account.most_recent:
                button = big_button("Switch")
                button.setEnabled(not self.switching)
                button.clicked.connect(lambda _=False, a=account: self.switch_account(a))
                self.account_buttons[account.steam_id] = button
                row.addWidget(button)
            self.accounts_box.addLayout(row)

    def switch_account(self, account) -> None:
        if self.switching:
            return
        self.switching = True
        for button in self.account_buttons.values():
            button.setEnabled(False)
        set_status(self.status, f"Switching to {account.persona} - Steam restarts…")
        run_async(lambda: self.steam.switch_account(account), self._switched,
                  lambda exc: self._switched((False, str(exc))), owner=self)

    def _switched(self, result) -> None:
        self.switching = False
        ok, message = result
        self.refresh()
        set_status(self.status, message, error=not ok)

    def edit_api_key(self) -> None:
        self.key_page = ApiKeyPage(self)
        self.addWidget(self.key_page)
        self.setCurrentWidget(self.key_page)

    def close_page(self, message: str) -> None:
        page = self.currentWidget()
        self.setCurrentWidget(self.overview)
        if page is not self.overview:
            self.removeWidget(page)
            page.deleteLater()
        self.refresh()
        set_status(self.status, message)

    def _close_wizard(self, message: str) -> None:
        self.setCurrentWidget(self.overview)
        if self.wizard is not None:
            self.removeWidget(self.wizard)
            self.wizard.deleteLater()
            self.wizard = None
        self.refresh()
        set_status(self.status, message)

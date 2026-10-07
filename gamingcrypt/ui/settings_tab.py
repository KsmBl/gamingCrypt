"""Settings tab. For now: show the security setup and reset the unlock method."""

from __future__ import annotations

from typing import Callable

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

from gamingcrypt.steam import accounts, library

from gamingcrypt.ui.auth_setup import AuthSetupWizard, UnlockerFactory
from gamingcrypt.ui.secret_input import METHOD_LABELS
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.input.service import InputService
from gamingcrypt.ui.controller_settings import ControllerPage
from gamingcrypt.ui.system_settings import AudioSection, DisplaySection, PowerSection
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button, enable_touch_scroll, set_status

SUB_TABS = ["Device", "Network", "Services", "Controller", "Games", "Storage", "Security", "Health", "Updates"]
LOCK_AFTER_SLEEP = [("Never", None), ("Right away", 0), ("After 5 minutes", 5), ("After 15 minutes", 15),
                    ("After 1 hour", 60)]
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
    libraries_changed = Signal()  # Games tab: show / hide libraries
    hotkeys_changed = Signal()  # device buttons (quick menu / lock) recorded

    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory: UnlockerFactory = VeraCryptUnlocker.from_config,
        system: SystemControls | None = None,
        steam_service=None,
        input_service: InputService | None = None,
        restart_gaming=None,
        parent: QWidget | None = None,
        health=None,
        updater=None,
        wifi=None,
        bluetooth=None,
        ssh=None,
        drive_share=None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.system = system if system is not None else SystemControls()
        self._steam_service = steam_service
        self.input = input_service if input_service is not None else InputService(config, save)
        self.switching = False
        self.wizard: AuthSetupWizard | None = None

        # Sub-tabs: Device | Controller | Steam | Security
        self.overview = QWidget()
        outer = QVBoxLayout(self.overview)
        outer.setContentsMargins(30, 10, 30, 0)
        bar = QHBoxLayout()
        self.sub_buttons: dict[str, object] = {}
        self.sub_stack = QStackedWidget()
        self.sub_pages: dict[str, QWidget] = {}
        for name in SUB_TABS:
            button = big_button(name, "tab", checkable=True)
            button.clicked.connect(lambda _=False, n=name: self.show_sub_tab(n))
            bar.addWidget(button)
            self.sub_buttons[name] = button
        bar.addStretch()
        outer.addLayout(bar)
        self.status = QLabel("")
        self.status.setObjectName("status")
        outer.addWidget(self.status)
        outer.addWidget(self.sub_stack, 1)

        def page(name: str) -> QVBoxLayout:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            enable_touch_scroll(scroll)
            content = QWidget()
            scroll.setWidget(content)
            box = QVBoxLayout(content)
            box.setContentsMargins(10, 10, 10, 20)
            box.setSpacing(14)
            self.sub_stack.addWidget(scroll)
            self.sub_pages[name] = scroll
            return box

        # Device
        layout = page("Device")
        from gamingcrypt.ui.system_settings import AppearanceSection

        self.appearance_section = AppearanceSection(config, save)
        layout.addWidget(self.appearance_section)
        self.display_section = DisplaySection(self.system, config, save, restart_gaming)
        self.power_section = PowerSection(self.system, config, save)
        self.audio_section = AudioSection(self.system, config, save)
        for section in (self.display_section, self.power_section, self.audio_section):
            layout.addWidget(section)
        layout.addStretch()

        # Network (Wi-Fi, Bluetooth)
        from gamingcrypt.ui.network_page import BluetoothSection, WifiSection

        layout = page("Network")
        self.wifi_section = WifiSection(self, wifi)
        layout.addWidget(self.wifi_section)
        self.bluetooth_section = BluetoothSection(bluetooth)
        layout.addWidget(self.bluetooth_section)
        layout.addStretch()

        # Services (SSH, the drive as network share)
        from gamingcrypt.ui.services_page import ServicesPage

        layout = page("Services")
        self.services_page = ServicesPage(config, save, ssh=ssh, share=drive_share)
        layout.addWidget(self.services_page)
        layout.addStretch()

        # Controller
        layout = page("Controller")
        self.controller_page = ControllerPage(self.input)
        layout.addWidget(self.controller_page)
        self.controller_test_button = big_button("🎮  Controller test")
        self.controller_test_button.clicked.connect(self.open_controller_test)
        self.emulator_controls_button = big_button("🕹  Emulator controls")
        self.emulator_controls_button.clicked.connect(self.open_emulator_controls)
        buttons = QHBoxLayout()
        buttons.addWidget(self.controller_test_button)
        buttons.addWidget(self.emulator_controls_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        from gamingcrypt.ui.device_buttons import DeviceButtonsSection

        self.device_buttons = DeviceButtonsSection(config, save)
        self.device_buttons.changed.connect(self.hotkeys_changed.emit)
        layout.addWidget(self.device_buttons)
        layout.addStretch()

        # Steam
        layout = page("Games")
        layout.addWidget(self._libraries_section())
        steam_heading = QLabel("Steam")
        steam_heading.setObjectName("section")
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

        # Security
        layout = page("Security")
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
        # lock after sleep (gaming mode: the power button suspends)
        row = QHBoxLayout()
        caption = QLabel("Lock after sleep")
        caption.setFixedWidth(220)
        row.addWidget(caption)
        self.sleep_lock = QComboBox()
        for label, minutes in LOCK_AFTER_SLEEP:
            self.sleep_lock.addItem(label, minutes)
        current = self.config.setdefault("system", {}).get("lock_after_sleep_min")
        self.sleep_lock.setCurrentIndex(max(0, self.sleep_lock.findData(current)))
        self.sleep_lock.currentIndexChanged.connect(self._sleep_lock_chosen)
        row.addWidget(self.sleep_lock, 1)
        layout.addLayout(row)
        hint = QLabel("Ask for your code again when the device wakes up. Your games drive stays unlocked.")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

        # Storage
        from gamingcrypt.ui.storage_page import StoragePage

        layout = page("Storage")
        self.storage_page = StoragePage(lambda: self.steam, emulation_fn=self.emulation_paths)
        layout.addWidget(self.storage_page)
        layout.addStretch()

        # Health
        from gamingcrypt.ui.health_page import HealthPage

        layout = page("Health")
        self.health_page = HealthPage(health)
        layout.addWidget(self.health_page)
        layout.addStretch()

        # Updates
        from gamingcrypt.ui.updates_page import UpdatesPage

        layout = page("Updates")
        self.updates_page = UpdatesPage(updater, restart=restart_gaming if restart_gaming else None)
        layout.addWidget(self.updates_page)
        layout.addStretch()
        self.show_sub_tab(SUB_TABS[0])
        self.addWidget(self.overview)
        self.refresh()

    def open_controller_test(self) -> None:
        from gamingcrypt.ui.controller_test import ControllerTestPage

        page = ControllerTestPage(**self.controller_test_options())
        page.closed.connect(lambda: self.close_page(""))
        self.addWidget(page)
        self.setCurrentWidget(page)

    def open_emulator_controls(self, system_id: str | None = None) -> None:
        """What each controller button is in every emulated system - and changing it."""
        from gamingcrypt.emulation import layouts
        from gamingcrypt.emulation.systems import SYSTEMS
        from gamingcrypt.ui.controls_page import ControlsPage

        page = ControlsPage(layouts.Store(self.config, self.save), system_id or SYSTEMS[0].id,
                            systems=[s.id for s in SYSTEMS])
        page.closed.connect(lambda: self.close_page(""))
        self.addWidget(page)
        self.setCurrentWidget(page)

    def emulation_paths(self):
        """The emulated games' folders on the unlocked drive (None: not there)."""
        import os
        from pathlib import Path

        from gamingcrypt.emulation.library import EmulationPaths

        mount = os.path.expanduser(self.config.get("unlock", {}).get("mount_point", "") or "")
        root = Path(mount) / "Emulation" if mount else None
        return EmulationPaths(root) if root is not None and (root / "roms").is_dir() else None

    def controller_test_options(self) -> dict:
        """Per-system button meanings and layouts (emulated systems)."""
        from gamingcrypt.emulation import layouts
        from gamingcrypt.emulation.systems import SYSTEMS

        store = layouts.Store(self.config, self.save)
        return {"labels_for": store.labels, "systems": [(s.id, s.name) for s in SYSTEMS], "layout_store": store}

    def _libraries_section(self) -> QWidget:
        """Which libraries the Games tab shows."""
        from gamingcrypt.ui.games_tab import CONTINUE, LIBRARIES

        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Libraries")
        heading.setObjectName("section")
        column.addWidget(heading)
        hint = QLabel("Shown on the Games tab")
        hint.setObjectName("cardMeta")
        column.addWidget(hint)
        row = QHBoxLayout()
        hidden = set(self.config.setdefault("libraries", {"hidden": []}).setdefault("hidden", []))
        self.library_buttons = {}
        for key, name in {CONTINUE: "Continue playing", **LIBRARIES}.items():
            button = big_button("", checkable=True)
            button.setChecked(key not in hidden)
            self._library_text(button, name)
            button.toggled.connect(lambda on, k=key, b=button, n=name: self._library_toggled(k, on, b, n))
            row.addWidget(button)
            self.library_buttons[key] = button
        row.addStretch()
        column.addLayout(row)
        # emulated systems (shown when they have games in Emulation/roms/<system>)
        from gamingcrypt.emulation.systems import SYSTEMS
        from gamingcrypt.ui.widgets import FlowLayout

        systems_heading = QLabel("Emulators")
        systems_heading.setObjectName("cardMeta")
        column.addWidget(systems_heading)
        flow_box = QWidget()
        flow = FlowLayout(flow_box)
        for system in SYSTEMS:
            key = f"emu:{system.id}"
            button = big_button("", checkable=True)
            button.setChecked(key not in hidden)
            self._library_text(button, system.name)
            button.toggled.connect(lambda on, k=key, b=button, n=system.name: self._library_toggled(k, on, b, n))
            flow.addWidget(button)
            self.library_buttons[key] = button
        column.addWidget(flow_box)
        return box

    @staticmethod
    def _library_text(button, name: str) -> None:
        button.setText(f"✓  {name}" if button.isChecked() else name)

    def _library_toggled(self, key: str, shown: bool, button, name: str) -> None:
        self._library_text(button, name)
        hidden = self.config["libraries"]["hidden"]
        if shown and key in hidden:
            hidden.remove(key)
        elif not shown and key not in hidden:
            hidden.append(key)
        self.save(self.config)
        self.libraries_changed.emit()

    def _sleep_lock_chosen(self, _index: int) -> None:
        self.config["system"]["lock_after_sleep_min"] = self.sleep_lock.currentData()
        self.save(self.config)

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

    def gamepad_back(self) -> bool:
        page = self.currentWidget()
        if page is self.overview:
            return False
        if page is self.wizard:
            if self.wizard.gamepad_back():
                return True
            if self.wizard.cancel_button.isEnabled():
                self.wizard.cancel_button.click()
            return True
        if page is getattr(self.wifi_section, "password_page", None):
            self.wifi_section.close_password("")
            return True
        self.close_page("")
        return True

    def show_sub_tab(self, name: str) -> None:
        self.current_sub_tab = name
        self.sub_stack.setCurrentWidget(self.sub_pages[name])
        for tab, button in self.sub_buttons.items():
            button.setChecked(tab == name)
        if name == "Health" and not self.health_page.checks:
            self.health_page.refresh()  # first visit: check now
        if name == "Storage":
            self.storage_page.refresh()
        if name == "Network":
            self.wifi_section.refresh()
            self.bluetooth_section.refresh()
        if name == "Services":
            self.services_page.refresh()
        if name == "Updates" and self.updates_page.info is None:
            self.updates_page.check()

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

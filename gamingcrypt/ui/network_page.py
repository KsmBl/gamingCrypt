"""Settings -> Network: Wi-Fi (and Bluetooth, see bluetooth_section) without a desktop."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from gamingcrypt.system.wifi import Network, Wifi
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button, set_status


class WifiPasswordPage(QWidget):
    """Password for a new network, typed on the on-screen keyboard."""

    def __init__(self, section: "WifiSection", network: Network):
        super().__init__()
        self.section, self.network = section, network
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        title = QLabel(f"Wi-Fi password for {network.ssid}")
        title.setObjectName("title")
        title.setWordWrap(True)
        layout.addWidget(title)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Password")
        layout.addWidget(self.edit)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.keyboard = OnScreenKeyboard(self.edit, compact=True)
        self.keyboard.submitted.connect(self.connect_network)
        layout.addWidget(self.keyboard)
        buttons = QHBoxLayout()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(lambda: section.close_password(""))
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        self.connect_button = big_button("Connect", "primary")
        self.connect_button.clicked.connect(self.connect_network)
        buttons.addWidget(self.connect_button)
        layout.addLayout(buttons)

    def connect_network(self) -> None:
        password = self.edit.text()
        if self.network.secured and len(password) < 8:
            set_status(self.status, "Wi-Fi passwords have at least 8 characters", error=True)
            return
        set_status(self.status, f"Connecting to {self.network.ssid}…")
        self.connect_button.setEnabled(False)
        run_async(lambda: self.section.wifi.connect(self.network, password), self._done,
                  lambda exc: self._done((False, str(exc))), owner=self)

    def _done(self, result) -> None:
        ok, message = result
        self.connect_button.setEnabled(True)
        if ok:
            self.section.close_password(message)
        else:
            set_status(self.status, message, error=True)


class WifiSection(QFrame):
    def __init__(self, tab, wifi: Wifi | None = None):
        super().__init__()
        self.tab = tab
        self.wifi = wifi or Wifi()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        heading = QLabel("Wi-Fi")
        heading.setObjectName("section")
        top.addWidget(heading)
        top.addStretch()
        self.toggle = big_button("On", checkable=True)
        self.toggle.toggled.connect(self.set_enabled)
        top.addWidget(self.toggle)
        self.scan_button = big_button("↻  Scan")
        self.scan_button.clicked.connect(lambda: self.refresh(rescan=True))
        top.addWidget(self.scan_button)
        self.body.addLayout(top)
        self.list = QVBoxLayout()
        self.body.addLayout(self.list)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.rows: dict[str, QWidget] = {}
        self.networks: list[Network] = []
        self.busy = False
        if not self.wifi.available:
            self.toggle.hide()
            self.scan_button.hide()
            set_status(self.status, "NetworkManager (nmcli) not found - Wi-Fi can't be changed here.", error=True)

    # list ---------------------------------------------------------------------------------
    def refresh(self, rescan: bool = False) -> None:
        if not self.wifi.available or self.busy:
            return
        self.busy = True
        if rescan:
            set_status(self.status, "Looking for networks…")  # otherwise: keep e.g. "Connected to …"
        wifi = self.wifi
        run_async(lambda: (wifi.enabled(), wifi.networks(rescan)), self._listed,
                  lambda exc: self._failed(str(exc)), owner=self)

    def _listed(self, result) -> None:
        self.busy = False
        enabled, networks = result
        self.toggle.blockSignals(True)
        self.toggle.setChecked(enabled)
        self.toggle.setText("On" if enabled else "Off")
        self.toggle.blockSignals(False)
        self.show_networks(networks if enabled else [])
        if not enabled:
            set_status(self.status, "Wi-Fi is off")
        elif not networks:
            set_status(self.status, "No networks found - try Scan")
        elif self.status.text().startswith("Looking"):
            set_status(self.status, "")

    def show_networks(self, networks: list[Network]) -> None:
        self.networks = networks
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        for network in networks:
            row = QWidget()
            row.setObjectName("menuRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            state = "Connected" if network.in_use else ("Saved" if network.saved else "")
            label = f"{network.bars}  {network.ssid}{'  🔒' if network.secured else ''}"
            button = big_button(label + (f"   ·  {state}" if state else ""), "primary" if network.in_use else "")
            button.clicked.connect(lambda _c=False, n=network: self.choose(n))
            line.addWidget(button, 1)
            if network.saved:
                forget = big_button("Forget")
                forget.clicked.connect(lambda _c=False, n=network: self.forget(n))
                line.addWidget(forget)
            self.list.addWidget(row)
            self.rows[network.ssid] = row

    # actions ------------------------------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        self.toggle.setText("On" if on else "Off")
        run_async(lambda: self.wifi.set_enabled(on), lambda r: self._after_action(r, refresh=True),
                  lambda exc: self._failed(str(exc)), owner=self)

    def choose(self, network: Network) -> None:
        if network.in_use:
            set_status(self.status, f"Connected to {network.ssid}")
            return
        if network.secured and not network.saved:
            self.password_page = WifiPasswordPage(self, network)
            self.tab.addWidget(self.password_page)
            self.tab.setCurrentWidget(self.password_page)
            return
        set_status(self.status, f"Connecting to {network.ssid}…")
        run_async(lambda: self.wifi.connect(network), lambda r: self._after_action(r, refresh=True),
                  lambda exc: self._failed(str(exc)), owner=self)

    def forget(self, network: Network) -> None:
        run_async(lambda: self.wifi.forget(network.ssid), lambda r: self._after_action(r, refresh=True),
                  lambda exc: self._failed(str(exc)), owner=self)

    def close_password(self, message: str) -> None:
        page = getattr(self, "password_page", None)
        self.tab.setCurrentWidget(self.tab.overview)
        if page is not None:
            self.tab.removeWidget(page)
            page.deleteLater()
            self.password_page = None
        if message:
            set_status(self.status, message)
        self.refresh()

    def _after_action(self, result, refresh: bool = False) -> None:
        ok, message = result
        set_status(self.status, message, error=not ok)
        if refresh:
            self.refresh()

    def _failed(self, message: str) -> None:
        self.busy = False
        set_status(self.status, message, error=True)


class BluetoothSection(QFrame):
    """Controllers and headphones: search, pair, connect - and their battery."""

    def __init__(self, bluetooth=None):
        super().__init__()
        from gamingcrypt.system.bluetooth import Bluetooth

        self.bt = bluetooth or Bluetooth()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        heading = QLabel("Bluetooth")
        heading.setObjectName("section")
        top.addWidget(heading)
        top.addStretch()
        self.toggle = big_button("On", checkable=True)
        self.toggle.toggled.connect(self.set_powered)
        top.addWidget(self.toggle)
        self.search_button = big_button("🔍  Search")
        self.search_button.clicked.connect(self.search)
        top.addWidget(self.search_button)
        self.body.addLayout(top)
        self.list = QVBoxLayout()
        self.body.addLayout(self.list)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.rows: dict[str, QWidget] = {}
        self.busy = False
        if not self.bt.available:
            self.toggle.hide()
            self.search_button.hide()
            set_status(self.status, "Bluetooth tools (bluez-utils) not installed - run ./install.sh", error=True)

    def refresh(self) -> None:
        if not self.bt.available or self.busy:
            return
        self.busy = True
        bt = self.bt
        run_async(lambda: (bt.powered(), bt.devices()), self._listed, lambda exc: self._failed(str(exc)), owner=self)

    def search(self) -> None:
        if self.busy:
            return
        self.busy = True
        set_status(self.status, "Searching - put your controller or headphones in pairing mode…")
        bt = self.bt
        run_async(lambda: (bt.scan(), (bt.powered(), bt.devices()))[1], self._listed,
                  lambda exc: self._failed(str(exc)), owner=self)

    def _listed(self, result) -> None:
        self.busy = False
        powered, devices = result
        self.toggle.blockSignals(True)
        self.toggle.setChecked(powered)
        self.toggle.setText("On" if powered else "Off")
        self.toggle.blockSignals(False)
        self.search_button.setEnabled(powered)
        self.show_devices(devices if powered else [])
        if not powered:
            set_status(self.status, "Bluetooth is off")
        elif self.status.text().startswith("Searching"):
            set_status(self.status, "" if devices else "Nothing found")

    def show_devices(self, devices) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        for device in devices:
            row = QWidget()
            row.setObjectName("menuRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            state = "Connected" if device.connected else ("Paired" if device.paired else "Tap to pair")
            battery = f"  ·  🔋 {device.battery}%" if device.battery is not None else ""
            button = big_button(f"{device.symbol}  {device.name}   ·  {state}{battery}",
                                "primary" if device.connected else "")
            button.clicked.connect(lambda _c=False, d=device: self.choose(d))
            line.addWidget(button, 1)
            if device.paired:
                remove = big_button("Remove")
                remove.clicked.connect(lambda _c=False, d=device: self._run(lambda: self.bt.remove(d.mac)))
                line.addWidget(remove)
            self.list.addWidget(row)
            self.rows[device.mac] = row

    def choose(self, device) -> None:
        if device.connected:
            self._run(lambda: self.bt.disconnect(device.mac), f"Disconnecting {device.name}…")
        elif device.paired:
            self._run(lambda: self.bt.connect(device.mac), f"Connecting {device.name}…")
        else:
            self._run(lambda: self.bt.pair(device.mac), f"Pairing {device.name}…")

    def set_powered(self, on: bool) -> None:
        self.toggle.setText("On" if on else "Off")
        self._run(lambda: self.bt.set_powered(on))

    def _run(self, action, text: str = "") -> None:
        if text:
            set_status(self.status, text)
        run_async(action, self._done, lambda exc: self._failed(str(exc)), owner=self)

    def _done(self, result) -> None:
        ok, message = result
        set_status(self.status, message, error=not ok)
        self.refresh()

    def _failed(self, message: str) -> None:
        self.busy = False
        set_status(self.status, message, error=True)

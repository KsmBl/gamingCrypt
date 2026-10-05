"""Bluetooth through bluetoothctl (BlueZ): pair controllers and headphones in gaming mode."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")
ICONS = {"input-gaming": "🎮", "audio-headset": "🎧", "audio-headphones": "🎧", "audio-card": "🔊",
         "input-keyboard": "⌨", "input-mouse": "🖱", "phone": "📱"}


@dataclass
class Device:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False
    battery: int | None = None
    icon: str = ""

    @property
    def symbol(self) -> str:
        return ICONS.get(self.icon, "●")


def parse_info(mac: str, text: str) -> Device:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.strip().split(":", 1)
            fields.setdefault(key.strip(), value.strip())
    battery = re.search(r"\((\d+)\)", fields.get("Battery Percentage", ""))
    return Device(mac, fields.get("Alias") or fields.get("Name") or mac, fields.get("Paired") == "yes",
                  fields.get("Connected") == "yes", int(battery.group(1)) if battery else None,
                  fields.get("Icon", ""))


class Bluetooth:
    def __init__(self, runner: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which):
        self.runner = runner
        self.available = bool(which("bluetoothctl"))

    def _ctl(self, *args: str, timeout: int = 20) -> subprocess.CompletedProcess:
        cmd = ["bluetoothctl", *args]
        try:
            return self.runner(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(cmd, 1, "", str(exc))

    @staticmethod
    def _ok(result: subprocess.CompletedProcess, *markers: str) -> bool:
        text = result.stdout + result.stderr
        return result.returncode == 0 and not re.search(r"Failed|not available|org\.bluez\.Error", text) and (
            not markers or any(m in text for m in markers))

    def powered(self) -> bool:
        return "Powered: yes" in self._ctl("show").stdout

    def set_powered(self, on: bool) -> tuple[bool, str]:
        result = self._ctl("power", "on" if on else "off")
        ok = self._ok(result)
        return ok, "" if ok else "Bluetooth could not be switched " + ("on" if on else "off")

    def devices(self) -> list[Device]:
        found = []
        for line in self._ctl("devices").stdout.splitlines():
            parts = line.split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device" and MAC.match(parts[1].upper()):
                mac = parts[1].upper()
                device = parse_info(mac, self._ctl("info", mac).stdout)
                if device.name == mac and len(parts) == 3:
                    device.name = parts[2]
                found.append(device)
        return sorted(found, key=lambda d: (not d.connected, not d.paired, d.name.lower()))

    def scan(self, seconds: int = 8) -> None:
        self._ctl("--timeout", str(seconds), "scan", "on", timeout=seconds + 10)

    def _check(self, mac: str) -> str:
        mac = mac.upper()
        if not MAC.match(mac):
            raise ValueError(f"not a Bluetooth address: {mac}")
        return mac

    def pair(self, mac: str) -> tuple[bool, str]:
        """Pair, trust (reconnects by itself later) and connect - controllers and headphones
        need no PIN (NoInputNoOutput agent)."""
        mac = self._check(mac)
        paired = self._ctl("--agent", "NoInputNoOutput", "pair", mac, timeout=40)
        if not self._ok(paired, "Pairing successful", "AlreadyExists"):
            return False, "Pairing failed - put the device in pairing mode and try again"
        self._ctl("trust", mac)
        return self.connect(mac)

    def connect(self, mac: str) -> tuple[bool, str]:
        result = self._ctl("connect", self._check(mac), timeout=30)
        ok = self._ok(result, "Connection successful")
        return ok, "Connected" if ok else "Could not connect - is the device on and nearby?"

    def disconnect(self, mac: str) -> tuple[bool, str]:
        ok = self._ok(self._ctl("disconnect", self._check(mac)))
        return ok, "Disconnected" if ok else "Could not disconnect"

    def remove(self, mac: str) -> tuple[bool, str]:
        ok = self._ok(self._ctl("remove", self._check(mac)))
        return ok, "Removed" if ok else "Could not remove the device"

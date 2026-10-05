"""Wi-Fi through NetworkManager (nmcli) - no desktop needed to get online."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class Network:
    ssid: str
    signal: int
    secured: bool
    in_use: bool = False
    saved: bool = False

    @property
    def bars(self) -> str:
        return "▂▄▆█"[: max(1, min(4, (self.signal + 24) // 25))]


def split_terse(line: str) -> list[str]:
    """nmcli -t fields: ':' separated, a literal ':' is written as '\\:'."""
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in parts]


class Wifi:
    def __init__(self, runner: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which):
        self.runner = runner
        self.available = bool(which("nmcli"))

    def _nmcli(self, *args: str, secret: str | None = None, timeout: int = 45) -> subprocess.CompletedProcess:
        cmd = ["nmcli", *(["--ask"] if secret is not None else []), *args]
        try:
            return self.runner(cmd, capture_output=True, text=True, timeout=timeout,
                               input=(secret + "\n") if secret is not None else None)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(cmd, 1, "", str(exc))

    @staticmethod
    def _error(result: subprocess.CompletedProcess) -> str:
        text = (result.stderr or result.stdout or "").strip().splitlines()
        message = text[-1] if text else "nmcli failed"
        return message.removeprefix("Error: ")

    def enabled(self) -> bool:
        return self._nmcli("radio", "wifi").stdout.strip() == "enabled"

    def set_enabled(self, on: bool) -> tuple[bool, str]:
        result = self._nmcli("radio", "wifi", "on" if on else "off")
        return result.returncode == 0, "" if result.returncode == 0 else self._error(result)

    def saved(self) -> set[str]:
        result = self._nmcli("-t", "-f", "NAME,TYPE", "connection", "show")
        names = set()
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) >= 2 and fields[1] == "802-11-wireless":
                names.add(fields[0])
        return names

    def networks(self, rescan: bool = False) -> list[Network]:
        result = self._nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                             "--rescan", "yes" if rescan else "no")
        saved = self.saved()
        found: dict[str, Network] = {}
        for line in result.stdout.splitlines():
            fields = split_terse(line)
            if len(fields) < 4 or not fields[1]:
                continue  # hidden networks have no name
            in_use, ssid, signal, security = fields[0] == "*", fields[1], fields[2], fields[3]
            network = Network(ssid, int(signal) if signal.isdigit() else 0, security not in ("", "--"), in_use,
                              ssid in saved)
            known = found.get(ssid)
            if known is None or network.in_use or (network.signal > known.signal and not known.in_use):
                found[ssid] = network
        return sorted(found.values(), key=lambda n: (not n.in_use, not n.saved, -n.signal, n.ssid.lower()))

    def connect(self, network: Network, password: str | None = None) -> tuple[bool, str]:
        if network.saved and password is None:
            result = self._nmcli("connection", "up", "id", network.ssid)
        elif network.secured:
            result = self._nmcli("device", "wifi", "connect", network.ssid, secret=password or "")
        else:
            result = self._nmcli("device", "wifi", "connect", network.ssid)
        if result.returncode == 0:
            return True, f"Connected to {network.ssid}"
        return False, self._error(result)

    def forget(self, ssid: str) -> tuple[bool, str]:
        result = self._nmcli("connection", "delete", "id", ssid)
        return result.returncode == 0, f"Forgot {ssid}" if result.returncode == 0 else self._error(result)

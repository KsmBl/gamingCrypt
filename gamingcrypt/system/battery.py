"""Battery level and charging state from /sys/class/power_supply."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BatteryState:
    percent: int
    charging: bool  # actively charging
    plugged: bool  # on external power (charging, full or "not charging")

    @property
    def label(self) -> str:
        return f"{'⚡' if self.plugged else '🔋'} {self.percent}%"

    @property
    def status(self) -> str:
        if self.charging:
            return "Charging"
        return "Plugged in" if self.plugged else "On battery"

    @property
    def low(self) -> bool:
        return self.percent <= 15 and not self.plugged


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _percent(supply: Path) -> int | None:
    capacity = _read(supply / "capacity")
    if capacity.isdigit():
        return int(capacity)
    for now, full in (("energy_now", "energy_full"), ("charge_now", "charge_full")):
        a, b = _read(supply / now), _read(supply / full)
        if a.isdigit() and b.isdigit() and int(b) > 0:
            return round(100 * int(a) / int(b))
    return None


def read_battery(sys_root: Path = Path("/sys")) -> BatteryState | None:
    """The device's own battery (not a gamepad's / mouse's), or None without one."""
    base = sys_root / "class" / "power_supply"
    batteries, mains_online = [], False
    for supply in sorted(base.iterdir()) if base.is_dir() else []:
        kind = _read(supply / "type")
        if kind == "Mains" and _read(supply / "online") == "1":
            mains_online = True
        if kind != "Battery" or _read(supply / "scope") == "Device":
            continue  # "Device" scope = battery of a connected controller etc.
        percent = _percent(supply)
        if percent is not None:
            batteries.append((percent, _read(supply / "status")))
    if not batteries:
        return None
    percent = round(sum(p for p, _ in batteries) / len(batteries))
    statuses = {s for _, s in batteries}
    charging = "Charging" in statuses
    plugged = charging or mains_online or (bool(statuses & {"Full", "Not charging"})
                                           and "Discharging" not in statuses)
    return BatteryState(max(0, min(100, percent)), charging, plugged)

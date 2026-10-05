"""Battery level and charging state from /sys/class/power_supply."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class BatteryState:
    percent: int
    charging: bool  # actively charging
    plugged: bool  # on external power (charging, full or "not charging")
    minutes: int | None = None  # time left on battery, or until full while charging

    @property
    def label(self) -> str:
        text = f"{'⚡' if self.plugged else '🔋'} {self.percent}%"
        if self.minutes is not None and (self.charging or not self.plugged):
            hours, minutes = divmod(self.minutes, 60)
            text += f" · {hours}:{minutes:02d}" + (" to full" if self.charging else "")
        return text

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


def _minutes(supply: Path, charging: bool) -> int | None:
    """From the current draw: energy (µWh / µW) or charge (µAh / µA)."""
    for now, full, rate in (("energy_now", "energy_full", "power_now"), ("charge_now", "charge_full", "current_now")):
        a, b, r = _read(supply / now), _read(supply / full), _read(supply / rate)
        if not (a.isdigit() and r.lstrip("-").isdigit()):
            continue
        rate_value = abs(int(r))
        if rate_value <= 0:
            return None  # idle / not reported yet
        amount = (int(b) - int(a)) if charging and b.isdigit() else int(a)
        minutes = round(60 * amount / rate_value)
        return minutes if 0 < minutes < 48 * 60 else None
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
            status = _read(supply / "status")
            batteries.append((percent, status, _minutes(supply, status == "Charging")))
    if not batteries:
        return None
    percent = round(sum(p for p, _s, _m in batteries) / len(batteries))
    statuses = {s for _p, s, _m in batteries}
    charging = "Charging" in statuses
    plugged = charging or mains_online or (bool(statuses & {"Full", "Not charging"})
                                           and "Discharging" not in statuses)
    minutes = batteries[0][2] if len(batteries) == 1 else None
    return BatteryState(max(0, min(100, percent)), charging, plugged, minutes)

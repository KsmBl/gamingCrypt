"""Maximum power consumption (TDP / package power limit).

Read from sysfs as a normal user; changing it needs root and goes through the
GamingCrypt helper (``sudo -n veracrypt-helper power-limit <watts>``), which
only accepts values inside the range the hardware reports.

* AMD: ``/sys/class/drm/card*/device/hwmon/hwmon*/power1_cap`` (+ ryzenadj if installed)
* Intel: ``/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw``
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]
MIN_WATTS = 3


@dataclass
class PowerLimit:
    current_w: int
    min_w: int
    max_w: int
    source: str


def _read_uw(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def read_limit(sys_root: Path = Path("/sys")) -> PowerLimit | None:
    for cap in sorted(sys_root.glob("class/drm/card*/device/hwmon/hwmon*/power1_cap")):
        current = _read_uw(cap)
        if current is None:
            continue
        low = _read_uw(cap.with_name("power1_cap_min")) or 0
        high = _read_uw(cap.with_name("power1_cap_max")) or current
        return PowerLimit(round(current / 1e6), max(MIN_WATTS, round(low / 1e6)), max(round(high / 1e6), MIN_WATTS),
                          "amdgpu")
    rapl = sys_root / "class/powercap/intel-rapl:0"
    current = _read_uw(rapl / "constraint_0_power_limit_uw")
    if current is not None:
        rated = _read_uw(rapl / "constraint_0_max_power_uw") or 0
        # The rated TDP can be below what the firmware already allows; never offer less than that.
        high = max(rated, current) or current
        return PowerLimit(round(current / 1e6), MIN_WATTS, max(round(high / 1e6), MIN_WATTS), "intel-rapl")
    return None


class PowerControl:
    def __init__(self, helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run, sys_root: Path = Path("/sys")):
        self.helper = helper
        self.runner = runner
        self.sys_root = sys_root

    def read(self) -> PowerLimit | None:
        return read_limit(self.sys_root)

    @property
    def can_set(self) -> bool:
        return os.path.exists(self.helper)

    def set(self, watts: int) -> tuple[bool, str]:
        if not self.can_set:
            return False, "Run install.sh to allow changing the power limit"
        try:
            result = self.runner(["sudo", "-n", self.helper, "power-limit", str(int(watts))],
                                 capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or "").strip().removeprefix("Error: gamingcrypt helper: ") or "failed"
        return True, f"Power limit set to {int(watts)} W"


def detect(sys_root: Path = Path("/sys"), runner: Runner = subprocess.run) -> PowerControl | None:
    return PowerControl(runner=runner, sys_root=sys_root) if read_limit(sys_root) else None

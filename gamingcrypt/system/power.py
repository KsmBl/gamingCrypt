"""Maximum power consumption (TDP / package power limit).

Read from sysfs as a normal user; changing it needs root and goes through the
GamingCrypt helper (``sudo -n veracrypt-helper power-limit <watts>``), which
only accepts values inside the range the hardware reports.

* AMD: ``/sys/class/drm/card*/device/hwmon/hwmon*/power1_cap`` (+ ryzenadj if installed)
* Intel: ``/sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw``
* AMD APUs without power1_cap (e.g. Ryzen 4800U handhelds): the CPU's power
  controller (SMU), the way RyzenAdj does it - done by the helper itself.
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


SMU_STATE = Path("/run/gamingcrypt-power-limit")


def smu_limit(cpuinfo: str | None = None, state: Path = SMU_STATE) -> PowerLimit | None:
    """Range from the helper's table (same CPU detection); current = what was last set."""
    from gamingcrypt.helper import veracrypt_helper as helper

    if cpuinfo is None:
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
        except OSError:
            return None
    cpu = helper.cpu_info(cpuinfo)
    limits = helper.smu_range(*cpu) if cpu else None
    if limits is None:
        return None
    try:
        current = int(state.read_text().strip())
    except (OSError, ValueError):
        current = 15 if limits[1] <= 28 else 25  # typical default TDP until set once
    current = max(limits[0], min(limits[1], current))
    return PowerLimit(current, limits[0], limits[1], f"AMD {helper.SMU_FAMILIES[cpu[:2]][0]} SMU")


def read_limit(sys_root: Path = Path("/sys"), cpuinfo: str | None = None,
               state: Path = SMU_STATE) -> PowerLimit | None:
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
    if sys_root != Path("/sys") and cpuinfo is None:
        return None  # tests with a fake /sys: no real CPU
    return smu_limit(cpuinfo, state)


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

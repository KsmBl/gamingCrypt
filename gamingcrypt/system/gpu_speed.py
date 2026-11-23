"""Graphics at full speed while a game runs (a per-game option).

AMD graphics on "auto" drop their clock between frames (on a 4800U from 1750 to 400 MHz many
times a second) and every climb back makes a frame late: micro-stutters in CPU-heavy games.
"Full speed" keeps the top clock (``power_dpm_force_performance_level = high``) - smoother,
a bit more battery. Changing it needs root: ``sudo -n veracrypt-helper gpu-speed full|auto``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]
PROFILE_KEY = "gpu_full"


def available(sys_root: Path = Path("/sys")) -> bool:
    """AMD graphics whose clock can be fixed (Intel / NVIDIA: no such switch)."""
    return any(sys_root.glob("class/drm/card*/device/power_dpm_force_performance_level"))


def set_full(full: bool, helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run) -> tuple[bool, str]:
    if not os.path.exists(helper):
        return False, "Run install.sh to allow changing the graphics speed"
    try:
        result = runner(["sudo", "-n", helper, "gpu-speed", "full" if full else "auto"],
                        capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or "").strip().removeprefix("Error: gamingcrypt helper: ") or "failed"
    return True, "Graphics at full speed" if full else "Graphics speed automatic"

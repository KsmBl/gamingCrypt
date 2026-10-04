"""Runtime controls of the running gamescope (X11 root window properties).

GAMESCOPE_DYNAMIC_REFRESH changes the refresh rate of the internal screen
without restarting gamescope (so a running game keeps running). Whether a rate
is possible depends on the panel - hence the keep/revert question in the UI.
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
DYNAMIC_REFRESH = "GAMESCOPE_DYNAMIC_REFRESH"


def _xprop(args: list[str], runner: Runner) -> subprocess.CompletedProcess | None:
    try:
        return runner(["xprop", "-root", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None


def dynamic_refresh(runner: Runner = subprocess.run) -> int:
    """Current dynamic refresh rate (0 = gamescope's default)."""
    result = _xprop([DYNAMIC_REFRESH], runner)
    if result is None or result.returncode != 0:
        return 0
    match = re.search(r"=\s*(\d+)", result.stdout)
    return int(match.group(1)) if match else 0


def set_dynamic_refresh(hz: int, runner: Runner = subprocess.run) -> bool:
    if hz:
        args = ["-f", DYNAMIC_REFRESH, "32c", "-set", DYNAMIC_REFRESH, str(int(hz))]
    else:
        args = ["-remove", DYNAMIC_REFRESH]  # back to the default
    result = _xprop(args, runner)
    return result is not None and result.returncode == 0

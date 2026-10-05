"""Sleep (suspend) on the power button in gaming mode, and noticing the wake-up.

logind would shut down on the power button; GamingCrypt holds a
``handle-power-key`` inhibitor instead and suspends itself. The inhibitor process
dies with GamingCrypt (PR_SET_PDEATHSIG), so a crash never leaves the button dead.
A wake-up shows as CLOCK_BOOTTIME (counts during sleep) running ahead of
CLOCK_MONOTONIC (doesn't).
"""

from __future__ import annotations

import ctypes
import signal
import subprocess
import time
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
PR_SET_PDEATHSIG = 1
INHIBIT = ["systemd-inhibit", "--what=handle-power-key", "--mode=block", "--who=GamingCrypt",
           "--why=The power button puts the device to sleep", "sleep", "infinity"]


def _die_with_parent() -> None:
    try:
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def inhibit_power_key(popen=subprocess.Popen):
    try:
        return popen(INHIBIT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     preexec_fn=_die_with_parent)
    except OSError:
        return None


def suspend(runner: Runner = subprocess.run) -> tuple[bool, str]:
    try:
        result = runner(["systemctl", "suspend"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or "").strip() or "systemctl suspend failed"
    return True, "Going to sleep…"


def _offset() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()


class SleepClock:
    """``slept()`` -> seconds spent asleep since the last call (0 when awake)."""

    MIN_S = 3.0  # timer hiccups aren't sleep

    def __init__(self, offset: Callable[[], float] = _offset):
        self.offset = offset
        self.last = offset()

    def slept(self) -> float:
        now = self.offset()
        gap, self.last = now - self.last, now
        return gap if gap >= self.MIN_S else 0.0

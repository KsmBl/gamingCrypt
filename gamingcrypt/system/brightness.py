"""Screen brightness through ``brightnessctl`` (works without root via logind)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
MIN_PERCENT = 5  # never let a slider turn the screen black


class Brightness:
    def __init__(self, runner: Runner = subprocess.run):
        self.runner = runner

    def get(self) -> int | None:
        try:
            result = self.runner(["brightnessctl", "-m", "--class=backlight"], capture_output=True, text=True,
                                 timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            return int(result.stdout.strip().splitlines()[0].split(",")[3].rstrip("%"))
        except (IndexError, ValueError):
            return None

    def set(self, percent: int) -> bool:
        percent = max(MIN_PERCENT, min(100, int(percent)))
        try:
            result = self.runner(["brightnessctl", "-q", "--class=backlight", "set", f"{percent}%"],
                                 capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


def detect(which: Callable[[str], str | None] = shutil.which, runner: Runner = subprocess.run) -> Brightness | None:
    return Brightness(runner) if which("brightnessctl") else None

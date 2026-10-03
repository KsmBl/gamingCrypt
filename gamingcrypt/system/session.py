"""Shut down / restart the device (systemd-logind allows this for the logged-in user)."""

from __future__ import annotations

import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
COMMANDS = {"shutdown": ["systemctl", "poweroff"], "restart": ["systemctl", "reboot"]}


def power_action(kind: str, runner: Runner = subprocess.run) -> tuple[bool, str]:
    cmd = COMMANDS[kind]
    try:
        result = runner(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run {' '.join(cmd)}: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "").strip() or f"{' '.join(cmd)} failed"
    return True, "Shutting down…" if kind == "shutdown" else "Restarting…"

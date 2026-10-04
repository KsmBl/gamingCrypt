"""Gaming mode (GamingCrypt on gamescope) <-> desktop mode switching.

The session script ``gamingcrypt-session`` reads ``next-mode`` whenever its
current mode ends: "desktop" starts the desktop session once, otherwise gaming
mode starts again.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]


def state_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".local" / "state")
    return Path(base) / "gamingcrypt"


def in_gaming_session(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("GAMINGCRYPT_SESSION") == "1"


def request_desktop_mode(env: dict | None = None) -> Path:
    path = state_dir(env) / "next-mode"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("desktop\n")
    return path


def leave_desktop(runner: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which) -> bool:
    """From the desktop back to gaming mode: end the desktop compositor (the session
    script then starts gaming mode again)."""
    for tool in ("tilewinmsg", "swaymsg"):
        if which(tool):
            try:
                if runner([tool, "exit"], capture_output=True, timeout=10).returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
    return False

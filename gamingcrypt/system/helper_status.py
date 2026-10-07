"""Is the installed root helper as new as this GamingCrypt?

In-app updates can't replace it (no password), so after an update that changed it,
the old one is still installed and doesn't know the new operations (e.g. the SMB
share). This tells the UI to ask for the password once (Settings -> Updates).
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

from gamingcrypt.helper.veracrypt_helper import HELPER_VERSION
from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]
OUTDATED = "The GamingCrypt helper is outdated - finish the update in Settings → System"


def installed_version(helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run,
                      exists: Callable[[str], bool] = os.path.exists) -> int | None:
    """None: not installed or not allowed; 1: a helper from before versions existed."""
    if not exists(helper):
        return None
    try:
        result = runner(["sudo", "-n", helper, "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if "password is required" in (result.stderr or ""):
        return None
    text = (result.stdout or "").strip()
    return int(text) if result.returncode == 0 and text.isdigit() else 1


def outdated(helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run,
             exists: Callable[[str], bool] = os.path.exists) -> bool:
    version = installed_version(helper, runner, exists)
    return version is None or version < HELPER_VERSION

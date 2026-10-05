"""The SMB share of the Emulation folder (Windows: \\\\<ip>\\GamingCrypt), started and
stopped through the GamingCrypt helper - only while the upload page is open."""

from __future__ import annotations

import getpass
import os
import secrets
import string
import subprocess
from typing import Callable

from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]
SHARE = "GamingCrypt"


def new_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class SmbShare:
    def __init__(self, helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run,
                 exists: Callable[[str], bool] = os.path.exists, user: str | None = None):
        self.helper, self.runner, self.exists = helper, runner, exists
        self.user = user or getpass.getuser()
        self.password = ""
        self.running = False

    def start(self, folder: str) -> tuple[bool, str]:
        if not self.exists(self.helper):
            return False, "Run ./install.sh to allow the network share"
        self.password = new_password()
        try:
            result = self.runner(["sudo", "-n", self.helper, "smb-start", folder], input=self.password + "\n",
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or "").strip().removeprefix("Error: gamingcrypt helper: ") or "failed"
        self.running = True
        return True, ""

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        try:
            self.runner(["sudo", "-n", self.helper, "smb-stop"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass

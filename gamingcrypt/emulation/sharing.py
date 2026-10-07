"""SMB shares, started and stopped through the GamingCrypt helper:

- the temporary one of a folder (Windows: \\\\<ip>\\GamingCrypt), only while an upload page is open
- the whole drive (\\\\<ip>\\GamingCrypt-Drive), while it's switched on in Settings -> Services

Both run in one Samba, which keeps one password per user: while the drive share runs, the
temporary share uses its password instead of a new one (a new one would lock the drive
share's users out)."""

from __future__ import annotations

import getpass
import os
import subprocess
from typing import Callable

from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]
SHARE = "GamingCrypt"
DRIVE_SHARE = "GamingCrypt-Drive"
_drive = {"password": ""}  # set while the drive share runs


def new_password(words: int = 2) -> str:
    """Random words ("MapleOtter"): easy to type on a phone."""
    from gamingcrypt.emulation.words import phrase

    return phrase(words)


def drive_share_password() -> str:
    """The drive share's password while it runs, else ""."""
    return _drive["password"]


class SmbShare:
    START, STOP = "smb-start", "smb-stop"

    def __init__(self, helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run,
                 exists: Callable[[str], bool] = os.path.exists, user: str | None = None):
        self.helper, self.runner, self.exists = helper, runner, exists
        self.user = user or getpass.getuser()
        self.password = ""
        self.running = False

    def start(self, folder: str, password: str | None = None) -> tuple[bool, str]:
        from gamingcrypt.system import helper_status

        if not self.exists(self.helper):
            return False, "Run ./install.sh to allow the network share"
        if helper_status.outdated(self.helper, self.runner, self.exists):
            return False, helper_status.OUTDATED  # an old helper doesn't know the share yet
        password = password or drive_share_password() or new_password()
        try:
            result = self.runner(["sudo", "-n", self.helper, self.START, folder], input=password + "\n",
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or "").strip().removeprefix("Error: gamingcrypt helper: ") or "failed"
        self.password = password
        self.running = True
        return True, ""

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        try:
            self.runner(["sudo", "-n", self.helper, self.STOP], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            pass


class DriveShare(SmbShare):
    """The whole unlocked drive, with the password kept in the config."""

    START, STOP = "smb-drive-start", "smb-drive-stop"

    def start(self, folder: str, password: str | None = None) -> tuple[bool, str]:
        ok, message = super().start(folder, password)
        if ok:
            _drive["password"] = self.password
        return ok, message

    def stop(self, force: bool = False) -> None:
        """force: also when this object didn't start it (e.g. before locking the drive)."""
        if force:
            self.running = True
        _drive["password"] = ""
        super().stop()

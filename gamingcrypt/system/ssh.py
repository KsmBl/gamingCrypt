"""The SSH server (OpenSSH), switched on and off in Settings -> Services.

Reading its state needs no root; switching goes through the GamingCrypt helper
(systemctl enable / disable --now, so it stays that way after a reboot)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from gamingcrypt.helper.veracrypt_helper import ssh_unit
from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class SshState:
    installed: bool
    enabled: bool = False  # starts on boot
    active: bool = False  # running now


class Ssh:
    def __init__(self, helper: str = DEFAULT_HELPER, runner: Runner = subprocess.run,
                 exists: Callable[[str], bool] = os.path.exists):
        self.helper, self.runner, self.exists = helper, runner, exists

    def state(self) -> SshState:
        unit = ssh_unit(self.exists)
        if unit is None:
            return SshState(False)

        def ask(verb: str) -> bool:
            try:
                result = self.runner(["systemctl", verb, unit], capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                return False
            return result.returncode == 0

        return SshState(True, ask("is-enabled"), ask("is-active"))

    def set(self, on: bool) -> tuple[bool, str]:
        from gamingcrypt.system import helper_status

        if not self.exists(self.helper):
            return False, "Run ./install.sh to allow switching SSH"
        if helper_status.outdated(self.helper, self.runner, self.exists):
            return False, helper_status.OUTDATED
        try:
            result = self.runner(["sudo", "-n", self.helper, "ssh", "on" if on else "off"],
                                 capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or "").strip().removeprefix("Error: gamingcrypt helper: ") or "failed"
        return True, ""

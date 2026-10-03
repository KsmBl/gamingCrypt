"""Mounting a VeraCrypt volume through the ``veracrypt`` command line tool.

The password is handed over on stdin (``--stdin``) so it never shows up in the
process list.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Callable, Sequence

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class UnlockResult:
    success: bool
    message: str = ""


@dataclass
class VeraCryptUnlocker:
    volume: str
    mount_point: str = ""
    binary: str = "veracrypt"
    use_sudo: bool = True
    pim: int = 0
    keyfiles: Sequence[str] = field(default_factory=list)
    runner: Runner = subprocess.run
    timeout: float = 120.0

    @classmethod
    def from_config(cls, unlock_cfg: dict, runner: Runner = subprocess.run) -> "VeraCryptUnlocker":
        return cls(
            volume=unlock_cfg.get("volume", ""),
            mount_point=unlock_cfg.get("mount_point", ""),
            binary=unlock_cfg.get("veracrypt_binary", "veracrypt"),
            use_sudo=unlock_cfg.get("use_sudo", True),
            pim=int(unlock_cfg.get("pim", 0) or 0),
            keyfiles=list(unlock_cfg.get("keyfiles", [])),
            runner=runner,
        )

    @property
    def configured(self) -> bool:
        return bool(self.volume)

    def _base(self) -> list[str]:
        prefix = ["sudo", "-n"] if self.use_sudo else []
        return prefix + [self.binary, "--text", "--non-interactive"]

    def mount_command(self) -> list[str]:
        cmd = self._base() + [
            "--stdin",
            f"--pim={self.pim}",
            f"--keyfiles={','.join(self.keyfiles)}",
            "--protect-hidden=no",
            "--mount",
            self.volume,
        ]
        if self.mount_point:
            cmd.append(self.mount_point)
        return cmd

    def change_password_command(self, new_secret: str) -> list[str]:
        # VeraCrypt can only read the *current* password from stdin, the new one
        # has to be passed as argument.
        keyfiles = ",".join(self.keyfiles)
        return self._base() + [
            "--stdin",
            f"--pim={self.pim}",
            f"--keyfiles={keyfiles}",
            f"--new-password={new_secret}",
            f"--new-pim={self.pim}",
            f"--new-keyfiles={keyfiles}",
            "--random-source=/dev/urandom",
            "-C",
            self.volume,
        ]

    def list_command(self) -> list[str]:
        return self._base() + ["--list", self.volume]

    def is_mounted(self) -> bool:
        try:
            result = self.runner(self.list_command(), capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0 and self.volume in (result.stdout or "")

    def _run(self, cmd: list[str], secret: str, ok_message: str) -> UnlockResult:
        try:
            result = self.runner(cmd, input=secret + "\n", capture_output=True, text=True, timeout=self.timeout)
        except FileNotFoundError:
            return UnlockResult(False, f"'{self.binary}' not found - is VeraCrypt installed?")
        except subprocess.TimeoutExpired:
            return UnlockResult(False, "VeraCrypt timed out")
        except (OSError, subprocess.SubprocessError) as exc:
            return UnlockResult(False, f"Could not run VeraCrypt: {exc}")
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if result.returncode == 0 and "error:" not in output.lower():
            return UnlockResult(True, ok_message)
        return UnlockResult(False, explain_error(output))

    def change_password(self, current_secret: str, new_secret: str) -> UnlockResult:
        """Re-key the volume header so ``new_secret`` unlocks it from now on."""
        if not self.configured:
            return UnlockResult(False, "No VeraCrypt volume configured")
        if current_secret == new_secret:
            return UnlockResult(True, "Unchanged")
        return self._run(self.change_password_command(new_secret), current_secret, "Unlock method changed")

    def unlock(self, secret: str) -> UnlockResult:
        if not self.configured:
            return UnlockResult(False, "No VeraCrypt volume configured")
        if self.is_mounted():
            return UnlockResult(True, "Volume already mounted")
        return self._run(self.mount_command(), secret, "Unlocked")


def explain_error(output: str) -> str:
    low = output.lower()
    if "incorrect password" in low or "wrong password" in low or "not a valid volume" in low:
        return "Wrong code - please try again"
    if "a password is required" in low or "administrator privileges" in low:
        return "Missing permissions: run install.sh to set up the sudo rule for VeraCrypt"
    if "already mounted" in low:
        return "Volume is already mounted"
    if "no such file" in low or "does not exist" in low:
        return "Volume not found - is the drive connected?"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "Unlocking failed"

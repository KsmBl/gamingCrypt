"""Mounting a VeraCrypt volume through the ``veracrypt`` command line tool.

The password is handed over on stdin (``--stdin``) so it never shows up in the
process list.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable, Sequence

from gamingcrypt.unlock import kdf as kdf_mod

Runner = Callable[..., subprocess.CompletedProcess]
Progress = Callable[[float], None]
PROGRESS_RE = re.compile(r"Done:\s*([\d.]+)\s*%")

# Root-owned allow-list wrapper installed by install.sh (see helper/veracrypt_helper.py).
DEFAULT_HELPER = "/usr/local/lib/gamingcrypt/veracrypt-helper"


@dataclass
class UnlockResult:
    success: bool
    message: str = ""
    cancelled: bool = False


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
    # With sudo, this helper is called instead of veracrypt when it exists.
    sudo_helper: str = ""
    # scrypt parameters (see kdf.py); None = the secret is the password (legacy).
    kdf: dict | None = None

    @classmethod
    def from_config(cls, unlock_cfg: dict, runner: Runner = subprocess.run) -> "VeraCryptUnlocker":
        return cls(
            volume=os.path.expanduser(unlock_cfg.get("volume", "")),
            mount_point=os.path.expanduser(unlock_cfg.get("mount_point", "")),
            binary=unlock_cfg.get("veracrypt_binary", "veracrypt"),
            use_sudo=unlock_cfg.get("use_sudo", True),
            pim=int(unlock_cfg.get("pim", 0) or 0),
            keyfiles=list(unlock_cfg.get("keyfiles", [])),
            runner=runner,
            sudo_helper=unlock_cfg.get("sudo_helper", DEFAULT_HELPER),
            kdf=unlock_cfg.get("kdf") or None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.volume)

    def _base(self) -> list[str]:
        if self.use_sudo:
            use_helper = self.sudo_helper and os.path.exists(self.sudo_helper)
            return ["sudo", "-n", self.sudo_helper if use_helper else self.binary, "--text", "--non-interactive"]
        return [self.binary, "--text", "--non-interactive"]

    def mount_command(self) -> list[str]:
        cmd = self._base() + [
            "--stdin",
            f"--pim={self.pim}",
            f"--keyfiles={','.join(self.keyfiles)}",
            "--protect-hidden=no",
            "--fs-options=nosuid,nodev",
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

    def create_command(self, path: str, size_gb: int, quick: bool = True, filesystem: str = "ext4") -> list[str]:
        cmd = self._base() + [
            "--stdin",
            "--create",
            path,
            f"--size={int(size_gb)}G",
            "--volume-type=normal",
            "--encryption=AES",
            "--hash=SHA-512",
            f"--filesystem={filesystem}",
            "--pim=0",
            "--keyfiles=",
            "--random-source=/dev/urandom",
        ]
        if quick:
            cmd.append("--quick")
        return cmd

    def create_volume(
        self,
        path: str,
        size_gb: int,
        secret: str,
        quick: bool = True,
        progress: Progress | None = None,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        filesystem: str = "ext4",
        cancel: threading.Event | None = None,
    ) -> UnlockResult:
        """Create a new container file protected by ``secret`` (derived with this
        unlocker's ``kdf``). Reports progress 0-100.

        Setting ``cancel`` stops VeraCrypt and deletes the half-written file.
        """
        if os.path.lexists(path):
            return UnlockResult(False, "A file with that name already exists")
        try:
            secret = self._derive(secret, self.kdf)
        except kdf_mod.KDFError as exc:
            return UnlockResult(False, str(exc))
        cmd = self.create_command(path, size_gb, quick, filesystem)
        try:
            proc = popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except FileNotFoundError:
            return UnlockResult(False, f"'{cmd[2] if self.use_sudo else self.binary}' not found - is VeraCrypt installed?")
        except OSError as exc:
            return UnlockResult(False, f"Could not run VeraCrypt: {exc}")
        if cancel is not None:
            threading.Thread(target=self._terminate_on_cancel, args=(proc, cancel), daemon=True).start()
        try:
            proc.stdin.write(secret + "\n")
            proc.stdin.close()
        except OSError:
            pass
        output, tail = [], ""
        while True:
            chunk = proc.stdout.read(64)
            if not chunk:
                break
            output.append(chunk)
            tail = (tail + chunk)[-200:]
            matches = PROGRESS_RE.findall(tail)
            if matches and progress is not None:
                progress(min(100.0, float(matches[-1])))
        returncode = proc.wait()
        if cancel is not None and cancel.is_set():
            try:
                os.remove(path)  # it didn't exist before, so it's our half-written file
            except OSError:
                pass
            return UnlockResult(False, "Creation cancelled", cancelled=True)
        text = "".join(output)
        if returncode == 0 and "error:" not in text.lower():
            if progress is not None:
                progress(100.0)
            return UnlockResult(True, "Container created")
        return UnlockResult(False, explain_error(text))

    @staticmethod
    def _terminate_on_cancel(proc, cancel: threading.Event) -> None:
        while proc.poll() is None:
            if cancel.wait(0.2):
                try:
                    proc.terminate()  # sudo forwards SIGTERM to the helper
                except OSError:
                    pass
                return

    def dismount_command(self, force: bool = False) -> list[str]:
        return self._base() + (["--force"] if force else []) + ["-d", self.volume]

    def dismount(self) -> UnlockResult:
        """Unmount the drive (panic lock). Forced when something still holds files on it."""
        last = UnlockResult(False, "")
        for force in (False, True):
            try:
                result = self.runner(self.dismount_command(force), capture_output=True, text=True, timeout=60,
                                     stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError) as exc:
                return UnlockResult(False, f"Could not run VeraCrypt: {exc}")
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
            if result.returncode == 0 and "error:" not in output.lower():
                return UnlockResult(True, "Drive locked")
            last = UnlockResult(False, explain_error(output))
        return last

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

    def _derive(self, secret: str, params: dict | None) -> str:
        return kdf_mod.derive_password(secret, params)

    def change_password(self, current_secret: str, new_secret: str, new_kdf: dict | None = None) -> UnlockResult:
        """Re-key the volume header so ``new_secret`` (derived with ``new_kdf``) unlocks it.

        ``current_secret`` is derived with this unlocker's ``kdf``.
        """
        if not self.configured:
            return UnlockResult(False, "No VeraCrypt volume configured")
        try:
            current = self._derive(current_secret, self.kdf)
            new = self._derive(new_secret, new_kdf)
        except kdf_mod.KDFError as exc:
            return UnlockResult(False, str(exc))
        if current == new:
            return UnlockResult(True, "Unchanged")
        return self._run(self.change_password_command(new), current, "Unlock method changed")

    def unlock(self, secret: str) -> UnlockResult:
        if not self.configured:
            return UnlockResult(False, "No VeraCrypt volume configured")
        if self.is_mounted():
            return UnlockResult(True, "Volume already mounted")
        if self.mount_point:
            try:
                os.makedirs(os.path.expanduser(self.mount_point), exist_ok=True)
            except OSError:
                pass  # e.g. below /mnt without permission - VeraCrypt may still manage
        try:
            password = self._derive(secret, self.kdf)
        except kdf_mod.KDFError as exc:
            return UnlockResult(False, str(exc))
        return self._run(self.mount_command(), password, "Unlocked")


def explain_error(output: str) -> str:
    low = output.lower()
    if "incorrect password" in low or "wrong password" in low or "not a valid volume" in low:
        return "Wrong code - please try again"
    if "a password is required" in low or "administrator privileges" in low:
        return "Missing permissions: run install.sh to set up the sudo rule for VeraCrypt"
    if "file exists" in low or "already exists" in low:
        return "A file with that name already exists"
    if "not enough" in low and "space" in low:
        return "Not enough free disk space"
    if "already mounted" in low:
        return "Volume is already mounted"
    if "no such file" in low or "does not exist" in low:
        return "Volume not found - is the drive connected?"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else "Unlocking failed"

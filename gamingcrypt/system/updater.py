"""Updates from inside GamingCrypt: fetch the git repo it was installed from, show what's
new, fast-forward and re-run install.sh.

GamingCrypt has no password, so the in-app update runs ``install.sh --no-sudo`` (the
app itself). When the pulled changes touch the root parts (helper, gaming session,
udev rules - all in install.sh), the user is told to run ./install.sh once in a
terminal.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
ROOT_PARTS = ("install.sh", "gamingcrypt/helper/", "gamingcrypt/session/")


def data_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".local" / "share")
    return Path(base) / "gamingcrypt"


def source_dir(env: dict | None = None) -> Path | None:
    """Where install.sh ran from (it writes this down)."""
    try:
        path = Path((data_dir(env) / "source-dir").read_text().strip())
    except OSError:
        return None
    return path if (path / ".git").exists() else None


@dataclass
class UpdateInfo:
    ok: bool
    behind: int = 0
    changes: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def available(self) -> bool:
        return self.ok and self.behind > 0


class Updater:
    def __init__(self, source: Path | None = None, runner: Runner = subprocess.run):
        self.source = source if source is not None else source_dir()
        self.runner = runner

    def _git(self, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
        return self.runner(["git", "-C", str(self.source), *args], capture_output=True, text=True, timeout=timeout)

    def check(self) -> UpdateInfo:
        if self.source is None:
            return UpdateInfo(False, message="Not installed from a git folder - update with git pull + ./install.sh")
        try:
            fetched = self._git("fetch", "--quiet")
            if fetched.returncode != 0:
                return UpdateInfo(False, message="Could not reach GitHub: " + (fetched.stderr.strip() or "no network?"))
            count = self._git("rev-list", "--count", "HEAD..@{u}")
            if count.returncode != 0:
                return UpdateInfo(False, message="The source folder follows no branch")
            behind = int(count.stdout.strip() or 0)
            log = self._git("log", "--no-merges", "--format=%s", "HEAD..@{u}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return UpdateInfo(False, message=str(exc))
        changes = [line for line in log.stdout.splitlines() if line.strip()]
        return UpdateInfo(True, behind, changes, f"{behind} update(s) available" if behind else "Up to date")

    def needs_terminal(self, old: str, new: str) -> list[str]:
        """Changed root parts that the in-app update can't install."""
        diff = self._git("diff", "--name-only", old, new)
        files = diff.stdout.splitlines() if diff.returncode == 0 else []
        return sorted({part.rstrip("/") for part in ROOT_PARTS for f in files if f.startswith(part)})

    def apply(self) -> tuple[bool, str, list[str]]:
        """(ok, message, root parts that need ./install.sh in a terminal)."""
        if self.source is None:
            return False, "Not installed from a git folder", []
        try:
            old = self._git("rev-parse", "HEAD").stdout.strip()
            pulled = self._git("pull", "--ff-only", "--quiet", timeout=180)
            if pulled.returncode != 0:
                return False, "git pull failed: " + (pulled.stderr.strip().splitlines() or ["?"])[-1], []
            new = self._git("rev-parse", "HEAD").stdout.strip()
            installed = self.runner([str(self.source / "install.sh"), "--no-sudo"], capture_output=True, text=True,
                                    timeout=900, cwd=str(self.source), stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc), []
        if installed.returncode != 0:
            last = (installed.stderr or installed.stdout or "").strip().splitlines()
            return False, "install.sh failed: " + (last[-1] if last else "?"), []
        return True, "Updated", self.needs_terminal(old, new) if old != new else []


ASKPASS = '#!/bin/sh\ncat "{password_file}"\n'
SUDO_WRAPPER = '#!/bin/sh\nexec "{sudo}" -A "$@"\n'


def finish_install(source: Path | None, password: str, runner: Runner = subprocess.run,
                   which=None) -> tuple[bool, str]:
    """Run the full ./install.sh (helper, session, rules ...) with the user's password.

    The password goes into a file only this user can read, in a private temporary
    folder that's deleted right after; sudo reads it through SUDO_ASKPASS.
    """
    import shutil
    import tempfile

    if source is None:
        return False, "Not installed from a git folder - run ./install.sh in a terminal"
    sudo = (which or shutil.which)("sudo")
    if sudo is None:
        return False, "sudo not found"
    folder = Path(tempfile.mkdtemp(prefix="gamingcrypt-install-"))
    try:
        os.chmod(folder, 0o700)
        password_file = folder / "password"
        fd = os.open(password_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(password + "\n")
        askpass = folder / "askpass"
        askpass.write_text(ASKPASS.format(password_file=password_file))
        wrappers = folder / "bin"
        wrappers.mkdir()
        (wrappers / "sudo").write_text(SUDO_WRAPPER.format(sudo=sudo))
        for script in (askpass, wrappers / "sudo"):
            script.chmod(0o700)
        env = dict(os.environ, SUDO_ASKPASS=str(askpass), PATH=f"{wrappers}:{os.environ.get('PATH', '')}")
        check = runner([sudo, "-A", "-k", "-v"], env=env, capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
        if check.returncode != 0:
            return False, "Wrong password"
        installed = runner([str(source / "install.sh")], env=env, cwd=str(source), capture_output=True, text=True,
                           timeout=1800, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if installed.returncode != 0:
        last = (installed.stderr or installed.stdout or "").strip().splitlines()
        return False, "install.sh failed: " + (last[-1] if last else "?")
    return True, "Update finished"

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

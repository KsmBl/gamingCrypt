"""A game's companion: a helper that runs only while its game does - a mod's Linux side, for
example GTA IV's adaptive triggers (a daemon that turns what the game's .asi reports into
DualSense trigger effects).

It's a script named ``gamingcrypt-companion.sh`` in the game's folder (Windows and Linux
games). GamingCrypt starts it with ``sh`` (the game drive may not allow running files) in the
game's folder when the game starts, and ends it - its whole process group - when the game ends,
before GamingCrypt's own trigger effects go back to the controller. Its output goes to
``companion-<appid>.log`` with the other game logs. It's told about the game through
GAMINGCRYPT_APPID and GAMINGCRYPT_GAME_DIR.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path
from typing import Callable

log = logging.getLogger("gamingcrypt.companion")

SCRIPT = "gamingcrypt-companion.sh"
STOP_WAIT_S = 2.0  # it may still turn things off (the triggers): then it's killed


def script(folder: Path) -> Path | None:
    path = Path(folder) / SCRIPT
    return path if path.is_file() else None


class Companions:
    def __init__(self, popen: Callable = subprocess.Popen,
                 killpg: Callable[[int, int], None] = os.killpg):
        self._popen = popen
        self._killpg = killpg
        self._running: dict[int, subprocess.Popen] = {}

    def running(self, appid: int) -> bool:
        proc = self._running.get(appid)
        return proc is not None and proc.poll() is None

    def start(self, appid: int, folder: Path, log_dir: Path) -> bool:
        """The game's companion, when its folder has one (True: started)."""
        found = script(folder)
        if found is None:
            return False
        self.stop(appid)  # (one from an earlier start that didn't end)
        log_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "GAMINGCRYPT_APPID": str(appid), "GAMINGCRYPT_GAME_DIR": str(folder)}
        try:
            with open(log_dir / f"companion-{appid}.log", "wb") as out:
                proc = self._popen(["sh", str(found)], cwd=str(folder), env=env, stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            log.warning("companion of %s didn't start: %s", appid, exc)
            return False
        self._running[appid] = proc
        log.info("companion of %s started: %s", appid, found)
        return True

    def stop(self, appid: int | None = None) -> None:
        """End the game's companion (None: every one) - and wait for it, briefly."""
        for key in ([appid] if appid is not None else list(self._running)):
            proc = self._running.pop(key, None)
            if proc is None or proc.poll() is not None:
                continue
            self._signal(proc, signal.SIGTERM)
            try:
                proc.wait(timeout=STOP_WAIT_S)
            except subprocess.TimeoutExpired:
                self._signal(proc, signal.SIGKILL)
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            log.info("companion of %s ended", key)

    def _signal(self, proc, sig: int) -> None:
        try:
            self._killpg(proc.pid, sig)  # its own session: the script and what it started
        except (ProcessLookupError, PermissionError):
            pass

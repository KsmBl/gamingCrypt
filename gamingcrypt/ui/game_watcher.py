"""Gets the launcher out of the way while a game runs and brings it back afterwards.

Phases: launching (Steam is starting the game) -> starting (game process
exists, not drawing yet) -> playing (it opened the GPU: its window is coming)
-> finished. The launcher only steps aside in "playing", so the desktop never
flashes up while Steam/Proton are still preparing the game.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from gamingcrypt.steam.running import game_processes, uses_gpu

log = logging.getLogger("gamingcrypt.games")

POLL_MS = 1000
LAUNCH_TIMEOUT_S = 180  # a cold Steam start + updates/shader compilation can take a while
WINDOW_DELAY_S = 1.5  # after the GPU was opened: give the window a moment to appear
NO_GPU_FALLBACK_S = 45  # never seen on the GPU (unusual): step aside anyway
# Steam hasn't started the game yet after this long: it's probably showing a window
# (license agreement, cloud conflict, shader processing) that must not stay hidden.
STALL_S = 15
# Some games restart themselves through Steam right after starting (e.g. Unity games
# via SteamAPI_RestartAppIfNecessary): for a moment none of their processes exist.
EXIT_GRACE_S = 6


@dataclass(frozen=True)
class Timing:
    poll_ms: int = POLL_MS
    launch_timeout_s: float = LAUNCH_TIMEOUT_S
    window_delay_s: float = WINDOW_DELAY_S
    stall_s: float = STALL_S
    exit_grace_s: float = EXIT_GRACE_S


STEAM = Timing()
# Started by GamingCrypt itself, with no Steam in between and no restarting (the movie
# player): its window is up right away, and when it's gone it's gone.
QUICK = Timing(poll_ms=200, launch_timeout_s=20, window_delay_s=0.3, stall_s=float("inf"), exit_grace_s=0)


class GameWatcher(QObject):
    started = Signal(int)   # the game's processes exist
    visible = Signal(int)   # its window should be up -> step aside now
    finished = Signal(int)  # the game exited
    failed = Signal(int)    # the game never showed up
    phase_text = Signal(str)  # what's happening right now (for the loading screen)
    stalled = Signal(int)   # no game process for STALL_S -> show what Steam is showing

    def __init__(self, processes: Callable[[int], set[int]] = game_processes,
                 gpu: Callable[[set[int]], bool] = uses_gpu,
                 clock: Callable[[], float] = time.monotonic, parent: QObject | None = None,
                 describe: Callable[[int], str] | None = None):
        super().__init__(parent)
        self.processes = processes
        # appid -> "Compiling shaders…" etc. (set by the app, which knows Steam's folder)
        self.describe = describe
        self.last_phase = ""
        self.gpu = gpu
        self.clock = clock
        self.appid: int | None = None
        self.phase = "idle"
        self.timing = STEAM
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    def drawing_game(self, running: Callable[[], set[int]] | None = None) -> int | None:
        """A Steam game that runs and draws right now (started anywhere, e.g. Big Picture)."""
        from gamingcrypt.steam.running import running_appids

        for appid in sorted((running or running_appids)()):
            if self.gpu(self.processes(appid)):
                return appid
        return None

    @property
    def active(self) -> bool:
        return self.appid is not None

    @property
    def seen(self) -> bool:
        return self.phase in ("starting", "playing")

    def watch(self, appid: int, timing: Timing | None = None) -> None:
        timing = self.timing = timing or STEAM
        self.appid = int(appid)
        self.phase = "launching"
        self.started_at = self.clock()
        self.last_phase = ""
        self.stall_reported = False
        self.seen_at = 0.0
        self.gpu_at: float | None = None
        self.gone_at: float | None = None
        log.info("waiting for app %s to start", appid)
        self.timer.start(timing.poll_ms)

    def poll(self) -> None:
        if self.appid is None:
            return
        appid, now = self.appid, self.clock()
        pids = self.processes(appid)
        if not pids:
            if self.phase == "launching":
                if now - self.started_at > self.timing.launch_timeout_s:
                    log.warning("app %s did not start within %ss", appid, self.timing.launch_timeout_s)
                    self._stop()
                    self.failed.emit(appid)
                else:
                    self._report_phase(appid)
                    if not self.stall_reported and now - self.started_at >= self.timing.stall_s:
                        self.stall_reported = True
                        log.info("app %s: no game process after %ss - showing Steam", appid, self.timing.stall_s)
                        self.stalled.emit(appid)
                return
            if self.gone_at is None:
                self.gone_at = now
                log.info("app %s: no processes - waiting %ss in case it restarts", appid, self.timing.exit_grace_s)
            if now - self.gone_at < self.timing.exit_grace_s:
                return
            log.info("app %s exited", appid)
            self._stop()
            self.finished.emit(appid)
            return
        if self.gone_at is not None:
            log.info("app %s is back (restarted itself)", appid)
            self.gone_at = None
        if self.phase == "launching":
            self.phase = "starting"
            self.seen_at = now
            log.info("app %s started (%d processes)", appid, len(pids))
            self.started.emit(appid)
        if self.phase == "starting":
            if self.gpu_at is None and self.gpu(pids):
                self.gpu_at = now
                log.info("app %s opened the GPU", appid)
            if ((self.gpu_at is not None and now - self.gpu_at >= self.timing.window_delay_s)
                    or now - self.seen_at >= NO_GPU_FALLBACK_S):
                self.phase = "playing"
                self.visible.emit(appid)
                return
            self._report_phase(appid)

    def _report_phase(self, appid: int) -> None:
        if self.phase == "playing" or self.describe is None:
            return
        try:
            text = "Almost there…" if self.gpu_at is not None else self.describe(appid)
        except Exception:  # noqa: BLE001 - a status line must never break launching
            return
        if text and text != self.last_phase:
            self.last_phase = text
            log.info("app %s: %s", appid, text)
            self.phase_text.emit(text)

    def _stop(self) -> None:
        self.timer.stop()
        self.appid = None
        self.phase = "idle"

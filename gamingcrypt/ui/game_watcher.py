"""Gets the launcher out of the way while a game runs and brings it back afterwards.

Phases: launching (Steam is starting the game) -> starting (game process
exists, not drawing yet) -> playing (it opened the GPU: its window is coming)
-> finished. The launcher only steps aside in "playing", so the desktop never
flashes up while Steam/Proton are still preparing the game.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from gamingcrypt.steam.running import game_processes, uses_gpu

log = logging.getLogger("gamingcrypt.games")

POLL_MS = 1000
LAUNCH_TIMEOUT_S = 180  # a cold Steam start + updates/shader compilation can take a while
WINDOW_DELAY_S = 1.5  # after the GPU was opened: give the window a moment to appear
NO_GPU_FALLBACK_S = 45  # never seen on the GPU (unusual): step aside anyway


class GameWatcher(QObject):
    started = Signal(int)   # the game's processes exist
    visible = Signal(int)   # its window should be up -> step aside now
    finished = Signal(int)  # the game exited
    failed = Signal(int)    # the game never showed up

    def __init__(self, processes: Callable[[int], set[int]] = game_processes,
                 gpu: Callable[[set[int]], bool] = uses_gpu,
                 clock: Callable[[], float] = time.monotonic, parent: QObject | None = None):
        super().__init__(parent)
        self.processes = processes
        self.gpu = gpu
        self.clock = clock
        self.appid: int | None = None
        self.phase = "idle"
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    @property
    def active(self) -> bool:
        return self.appid is not None

    @property
    def seen(self) -> bool:
        return self.phase in ("starting", "playing")

    def watch(self, appid: int) -> None:
        self.appid = int(appid)
        self.phase = "launching"
        self.started_at = self.clock()
        self.seen_at = 0.0
        self.gpu_at: float | None = None
        log.info("waiting for app %s to start", appid)
        self.timer.start(POLL_MS)

    def poll(self) -> None:
        if self.appid is None:
            return
        appid, now = self.appid, self.clock()
        pids = self.processes(appid)
        if not pids:
            if self.phase == "launching":
                if now - self.started_at > LAUNCH_TIMEOUT_S:
                    log.warning("app %s did not start within %ss", appid, LAUNCH_TIMEOUT_S)
                    self._stop()
                    self.failed.emit(appid)
                return
            log.info("app %s exited", appid)
            self._stop()
            self.finished.emit(appid)
            return
        if self.phase == "launching":
            self.phase = "starting"
            self.seen_at = now
            log.info("app %s started (%d processes)", appid, len(pids))
            self.started.emit(appid)
        if self.phase == "starting":
            if self.gpu_at is None and self.gpu(pids):
                self.gpu_at = now
                log.info("app %s opened the GPU", appid)
            if ((self.gpu_at is not None and now - self.gpu_at >= WINDOW_DELAY_S)
                    or now - self.seen_at >= NO_GPU_FALLBACK_S):
                self.phase = "playing"
                self.visible.emit(appid)

    def _stop(self) -> None:
        self.timer.stop()
        self.appid = None
        self.phase = "idle"

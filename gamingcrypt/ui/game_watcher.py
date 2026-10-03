"""Gets the launcher out of the way while a game runs and brings it back afterwards."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from gamingcrypt.steam.running import running_appids

POLL_MS = 2000
LAUNCH_TIMEOUT_S = 180  # a cold Steam start + shader compilation can take a while


class GameWatcher(QObject):
    started = Signal(int)
    finished = Signal(int)
    failed = Signal(int)  # the game never showed up

    def __init__(self, running: Callable[[], set[int]] = running_appids, clock: Callable[[], float] = time.monotonic,
                 parent: QObject | None = None):
        super().__init__(parent)
        self.running = running
        self.clock = clock
        self.appid: int | None = None
        self.seen = False
        self.deadline = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    @property
    def active(self) -> bool:
        return self.appid is not None

    def watch(self, appid: int) -> None:
        self.appid = int(appid)
        self.seen = False
        self.deadline = self.clock() + LAUNCH_TIMEOUT_S
        self.timer.start(POLL_MS)

    def poll(self) -> None:
        if self.appid is None:
            return
        appid = self.appid
        if appid in self.running():
            if not self.seen:
                self.seen = True
                self.started.emit(appid)
            return
        if self.seen:
            self._stop()
            self.finished.emit(appid)
        elif self.clock() > self.deadline:
            self._stop()
            self.failed.emit(appid)

    def _stop(self) -> None:
        self.timer.stop()
        self.appid = None

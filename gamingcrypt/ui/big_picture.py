"""Brings GamingCrypt back when Steam's Big Picture is closed."""

from __future__ import annotations

import logging
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from gamingcrypt.system import x11windows
from gamingcrypt.ui.tasks import run_async

log = logging.getLogger("gamingcrypt.bigpicture")

POLL_MS = 2000
APPEAR_TIMEOUT_S = 60  # Steam may have to start first


class BigPictureWatcher(QObject):
    closed = Signal()  # Big Picture went away (or never came) -> come back

    def __init__(self, is_open: Callable[[], bool] = x11windows.big_picture_open,
                 clock: Callable[[], float] = time.monotonic, parent: QObject | None = None):
        super().__init__(parent)
        self.is_open = is_open
        self.clock = clock
        self.active = False
        self.seen = False
        self.checking = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    def watch(self) -> None:
        self.active, self.seen, self.started = True, False, self.clock()
        log.info("waiting for Big Picture")
        self.timer.start(POLL_MS)

    def poll(self) -> None:
        if not self.active or self.checking:
            return
        self.checking = True
        run_async(self.is_open, self._result, lambda _e: self._result(False), owner=self)

    def _result(self, is_open: bool) -> None:
        self.checking = False
        if not self.active:
            return
        if is_open:
            if not self.seen:
                log.info("Big Picture is open")
            self.seen = True
            return
        if self.seen:
            log.info("Big Picture closed")
            self.stop()
            self.closed.emit()
        elif self.clock() - self.started > APPEAR_TIMEOUT_S:
            log.warning("Big Picture did not open within %ss", APPEAR_TIMEOUT_S)
            self.stop()
            self.closed.emit()

    def stop(self) -> None:
        self.active = False
        self.timer.stop()

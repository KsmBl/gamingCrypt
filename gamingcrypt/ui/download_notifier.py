"""Notices about Steam downloads for the toasts: "Download finished: Hades",
"Updates available for 3 games". Polls the download list in the background."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from gamingcrypt.ui.tasks import run_async

POLL_MS = 15_000


class DownloadNotifier(QObject):
    message = Signal(str, str)  # icon, text

    def __init__(self, downloads: Callable[[], list], installed: Callable[[int], bool],
                 parent: QObject | None = None, interval_ms: int = POLL_MS):
        super().__init__(parent)
        self.downloads = downloads
        self.installed = installed
        self.known: dict[int, tuple[str, bool]] | None = None  # appid -> (name, is_update)
        self.busy = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(interval_ms)

    def poll(self) -> None:
        if self.busy:
            return
        self.busy = True

        def work():
            items = {d.appid: (d.name, d.is_update) for d in self.downloads()}
            finished = [(appid, name) for appid, (name, _u) in (self.known or {}).items()
                        if appid not in items and self.installed(appid)]
            return items, finished

        run_async(work, self._result, lambda _e: setattr(self, "busy", False), owner=self)

    def _result(self, result) -> None:
        self.busy = False
        items, finished = result
        first = self.known is None
        new_updates = [name for appid, (name, update) in items.items()
                       if update and (first or appid not in self.known)]
        self.known = items
        for _appid, name in finished:
            self.message.emit("⬇", f"Download finished: {name}")
        if new_updates:
            text = (f"Update available for {new_updates[0]}" if len(new_updates) == 1
                    else f"Updates available for {len(new_updates)} games")
            self.message.emit("↻", text)

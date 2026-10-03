"""Downloads tab: every queued, running or paused Steam download."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.installer import Download, InstallResult
from gamingcrypt.system.io_stats import rate
from gamingcrypt.ui.progress_estimate import ACTIVE_RATE, ProgressEstimator
from gamingcrypt.ui.game_widgets import format_size, load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FoldingHeader, big_button, enable_touch_scroll, set_status

REFRESH_MS = 1000
COVER_W, COVER_H = 80, 120
STATE_TEXT = {"downloading": "Downloading", "paused": "Paused", "queued": "Queued", "waiting": "Waiting"}
APPLY_DELAY_MS = 2500  # several quick ▲/▼ taps -> one Steam restart
MAX_AUTO_APPLY = 2  # if Steam ignores the order, don't keep restarting it


def format_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{format_size(int(value))}/s" if value >= 1024 else f"{int(value)} B/s"


def format_eta(seconds: float) -> str:
    if seconds < 60:
        return "<1 min left"
    if seconds < 3600:
        return f"{round(seconds / 60)} min left"
    return f"{seconds / 3600:.1f} h left"


def describe(d: Download, shown: int | None = None) -> str:
    kind = "Update" if d.is_update else "Install"
    text = f"{kind} · {STATE_TEXT[d.state]}"
    if d.total:
        done = d.downloaded if shown is None else shown
        text += f" · {format_size(done) if done else '0 B'} of {format_size(d.total)}"
    return text


class DownloadRow(QFrame):
    def __init__(self, service, download: Download, tab: "DownloadsTab | None" = None):
        super().__init__()
        self.tab = tab
        self.setObjectName("card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(18)
        cover = QLabel()
        cover.setFixedSize(COVER_W, COVER_H)
        cover.setPixmap(placeholder_cover(download.name, COVER_W, COVER_H))
        load_cover(service, download.appid, cover, COVER_W, COVER_H)
        layout.addWidget(cover)
        text = QVBoxLayout()
        self.name = QLabel(download.name)
        self.name.setObjectName("cardTitle")
        text.addWidget(self.name)
        self.state = QLabel()
        self.state.setObjectName("cardMeta")
        text.addWidget(self.state)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        text.addWidget(self.bar)
        layout.addLayout(text, 1)
        self.percent = QLabel()
        self.percent.setObjectName("cardTitle")
        self.percent.setFixedWidth(90)
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.percent)
        self.up_button = big_button("▲")
        self.down_button = big_button("▼")
        self.cancel_button = big_button("✕")
        for button in (self.up_button, self.down_button, self.cancel_button):
            button.setFixedWidth(64)
            layout.addWidget(button)
        self.up_button.clicked.connect(lambda: tab and tab.move(self.download.appid, -1))
        self.down_button.clicked.connect(lambda: tab and tab.move(self.download.appid, 1))
        self.cancel_button.clicked.connect(self.cancel_tapped)
        self._cancel_armed = False
        self._disarm = QTimer(self)
        self._disarm.setSingleShot(True)
        self._disarm.timeout.connect(self._disarm_cancel)
        self.waiting = False
        self.update_from(download)

    def cancel_tapped(self) -> None:
        # two taps: deleting downloaded data must not happen by accident
        if not self._cancel_armed:
            self._cancel_armed = True
            self.cancel_button.setText("Sure?")
            self.cancel_button.setFixedWidth(110)
            self._disarm.start(4000)
            return
        self._disarm_cancel()
        if self.tab is not None:
            self.tab.cancel(self.download)

    def _disarm_cancel(self) -> None:
        self._cancel_armed = False
        self.cancel_button.setText("✕")
        self.cancel_button.setFixedWidth(64)

    def update_from(self, d: Download, shown: int | None = None, extra: str = "", running: bool = False) -> None:
        self.download = d
        done = d.downloaded if shown is None else shown
        percent = 100.0 * done / d.total if d.total else 0.0
        from dataclasses import replace

        if running and d.state == "queued":
            d = replace(d, state="downloading")  # Steam hasn't caught up with its state yet
        if self.waiting and d.state in ("paused", "queued"):
            d = replace(d, state="waiting")  # paused by GamingCrypt: not at the top of the list
        self.state.setText(describe(d, shown) + (f" · {extra}" if extra else ""))
        self.bar.setValue(round(percent * 10))
        self.percent.setText(f"{percent:.1f}%" if d.total else "")


class DownloadsTab(QWidget):
    count_changed = Signal(int)

    def __init__(self, service, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.rows: dict[int, DownloadRow] = {}
        self.loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 10)
        self.header = QLabel("Downloads")
        self.header.setObjectName("title")
        layout.addWidget(self.header)
        self.stats = QLabel("")
        self.stats.setObjectName("cardTitle")
        self.stats.hide()
        layout.addWidget(self.stats)
        self.message = QLabel("")
        self.message.setObjectName("status")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.items: list[Download] = []
        self.applying = False
        self.apply_attempts: dict[tuple, int] = {}
        self.apply_timer = QTimer(self)
        self.apply_timer.setSingleShot(True)
        self.apply_timer.timeout.connect(self.apply_order)
        self.last_sample = None
        self.estimator = ProgressEstimator()
        self.empty = QLabel("No downloads - games you install show up here.")
        self.empty.setObjectName("subtitle")
        layout.addWidget(self.empty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.list = QVBoxLayout(content)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.folding = FoldingHeader(scroll, self.header)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        service = self.service

        def collect():
            items = service.downloads()
            active = next((d for d in items if d.state == "downloading"), items[0] if items else None)
            sample = service.io_sample(active.library if active else None) if hasattr(service, "io_sample") else None
            needs = service.queue_needs_apply(items) if hasattr(service, "queue_needs_apply") else False
            return items, sample, needs

        run_async(collect, lambda result: self.show_downloads(*result),
                  lambda _e: setattr(self, "loading", False), owner=self)

    @staticmethod
    def running(items: list[Download], net: float | None) -> Download | None:
        """The download that's really in progress.

        Steam often still calls it "queued" (no progress written yet) - then it's the
        first non-paused one with a known size, as long as data is actually arriving.
        """
        marked = next((d for d in items if d.state == "downloading"), None)
        if marked is not None:
            return marked
        if net is None or net < ACTIVE_RATE:
            return None
        return next((d for d in items if d.state == "queued" and d.total), None)

    # queue ---------------------------------------------------------------------------
    def move(self, appid: int, delta: int) -> None:
        if not hasattr(self.service, "move_download"):
            return
        self.items = self.service.move_download(appid, delta)
        self.show_downloads(self.items, None)
        self.apply_attempts.clear()  # a new order deserves new attempts
        set_status(self.message, "New order - applied in a moment (Steam restarts in the background)")
        self.apply_timer.start(APPLY_DELAY_MS)

    def apply_order(self) -> None:
        if self.applying or not self.items or not hasattr(self.service, "apply_download_order"):
            return
        self.applying = True
        key = tuple(d.appid for d in self.items)
        self.apply_attempts[key] = self.apply_attempts.get(key, 0) + 1
        items = list(self.items)
        set_status(self.message, "Applying the download order - Steam restarts in the background…")
        run_async(lambda: self.service.apply_download_order(items), self._applied,
                  lambda exc: self._applied(InstallResult(False, str(exc))), owner=self)

    def _applied(self, result) -> None:
        self.applying = False
        set_status(self.message, result.message, error=not result.ok)

    def cancel(self, download: Download) -> None:
        if not hasattr(self.service, "cancel_download"):
            return
        set_status(self.message, f"Cancelling {download.name}…")
        run_async(lambda: self.service.cancel_download(download),
                  lambda r: (set_status(self.message, r.message, error=not r.ok), self.refresh()),
                  lambda exc: set_status(self.message, str(exc), error=True), owner=self)

    def show_downloads(self, items: list[Download], sample=None, needs_apply: bool = False) -> None:
        self.loading = False
        self.items = list(items)
        if needs_apply and not self.applying and not self.apply_timer.isActive():
            key = tuple(d.appid for d in items)
            if self.apply_attempts.get(key, 0) < MAX_AUTO_APPLY:
                self.apply_timer.start(APPLY_DELAY_MS)  # e.g. the top one finished -> start the next
            elif self.apply_attempts.get(key) == MAX_AUTO_APPLY:
                self.apply_attempts[key] += 1
                set_status(self.message, "Steam doesn't follow the order - it decides which download runs.",
                           error=True)
        net = rate(self.last_sample, sample, "net_rx") if sample is not None else None
        disk = rate(self.last_sample, sample, "disk_written") if sample is not None else None
        previous_net = self.last_sample.net_rx if self.last_sample is not None else None
        if sample is not None:
            self.last_sample = sample
        active = self.running(items, net)
        # Shown whenever something is in the list: Steam often reports a running download
        # as "queued" until it writes its first progress numbers.
        if items and sample is not None:
            parts = [f"↓ {format_rate(net) if net is not None else 'measuring…'}", f"Disk {format_rate(disk)}"]
            if sample.free is not None:
                parts.append(f"{format_size(sample.free)} free")
            self.stats.setText("   ·   ".join(parts))
            self.stats.show()
        else:
            self.stats.hide()
        wanted = [d.appid for d in items]
        for appid in list(self.rows):
            if appid not in wanted:  # finished or cancelled
                self.estimator.forget(appid)
                row = self.rows.pop(appid)
                self.list.removeWidget(row)
                row.deleteLater()
        for index, d in enumerate(items):
            row = self.rows.get(d.appid)
            if row is None:
                row = DownloadRow(self.service, d, self)
                self.rows[d.appid] = row
            row.waiting = index > 0
            row.up_button.setEnabled(index > 0)
            row.down_button.setEnabled(index < len(items) - 1)
            if d is active and sample is not None:
                shown = self.estimator.estimate(d.appid, d.downloaded, d.total, sample.net_rx, since=previous_net)
            else:
                if sample is not None:
                    self.estimator.reset(d.appid, sample.net_rx)
                shown = max(d.downloaded, self.estimator.shown.get(d.appid, 0))
            extra = ""
            if d is active and net:
                extra = format_rate(net)
                if d.total > shown:
                    extra += f" · {format_eta((d.total - shown) / net)}"
            row.update_from(d, shown, extra, running=d is active)
            self.list.insertWidget(index, row)  # keeps the running ones on top
        self.empty.setVisible(not items)
        self.count_changed.emit(len(items))

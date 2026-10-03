"""Downloads tab: every queued, running or paused Steam download."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.installer import Download
from gamingcrypt.system.io_stats import rate
from gamingcrypt.ui.progress_estimate import ACTIVE_RATE, ProgressEstimator
from gamingcrypt.ui.game_widgets import format_size, load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FoldingHeader, enable_touch_scroll

REFRESH_MS = 1000
COVER_W, COVER_H = 80, 120
STATE_TEXT = {"downloading": "Downloading", "paused": "Paused", "queued": "Queued"}


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
        text += f" · {format_size(d.downloaded if shown is None else shown)} of {format_size(d.total)}"
    return text


class DownloadRow(QFrame):
    def __init__(self, service, download: Download):
        super().__init__()
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
        self.update_from(download)

    def update_from(self, d: Download, shown: int | None = None, extra: str = "", running: bool = False) -> None:
        self.download = d
        done = d.downloaded if shown is None else shown
        percent = 100.0 * done / d.total if d.total else 0.0
        if running and d.state == "queued":
            from dataclasses import replace

            d = replace(d, state="downloading")  # Steam hasn't caught up with its state yet
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
            return items, sample

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

    def show_downloads(self, items: list[Download], sample=None) -> None:
        self.loading = False
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
                row = DownloadRow(self.service, d)
                self.rows[d.appid] = row
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

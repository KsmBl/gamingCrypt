"""Downloads tab: every queued, running or paused Steam download."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.installer import Download
from gamingcrypt.ui.game_widgets import format_size, load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import enable_touch_scroll

REFRESH_MS = 2000
COVER_W, COVER_H = 80, 120
STATE_TEXT = {"downloading": "Downloading", "paused": "Paused", "queued": "Queued"}


def describe(d: Download) -> str:
    kind = "Update" if d.is_update else "Install"
    text = f"{kind} · {STATE_TEXT[d.state]}"
    if d.total:
        text += f" · {format_size(d.downloaded)} of {format_size(d.total)}"
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

    def update_from(self, d: Download) -> None:
        self.download = d
        self.state.setText(describe(d))
        self.bar.setValue(round(d.percent * 10))
        self.percent.setText(f"{d.percent:.0f}%" if d.total else "")


class DownloadsTab(QWidget):
    count_changed = Signal(int)

    def __init__(self, service, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.rows: dict[int, DownloadRow] = {}
        self.loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 10)
        title = QLabel("Downloads")
        title.setObjectName("title")
        layout.addWidget(title)
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
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    def refresh(self) -> None:
        if self.loading:
            return
        self.loading = True
        run_async(self.service.downloads, self.show_downloads, lambda _e: setattr(self, "loading", False),
                  owner=self)

    def show_downloads(self, items: list[Download]) -> None:
        self.loading = False
        wanted = [d.appid for d in items]
        for appid in list(self.rows):
            if appid not in wanted:  # finished or cancelled
                row = self.rows.pop(appid)
                self.list.removeWidget(row)
                row.deleteLater()
        for index, d in enumerate(items):
            row = self.rows.get(d.appid)
            if row is None:
                row = DownloadRow(self.service, d)
                self.rows[d.appid] = row
            else:
                row.update_from(d)
            self.list.insertWidget(index, row)  # keeps the running ones on top
        self.empty.setVisible(not items)
        self.count_changed.emit(len(items))

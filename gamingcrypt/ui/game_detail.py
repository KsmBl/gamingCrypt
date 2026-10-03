"""Detail page of a single game: play / download and an options menu (uninstall)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.steam.installer import InstallResult
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.webapi import format_price
from gamingcrypt.ui.game_widgets import format_date, format_playtime, format_size, load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

PROGRESS_INTERVAL_MS = 2000

DETAIL_W, DETAIL_H = 300, 450


class GameDetailPage(QWidget):
    def __init__(self, tab, game: SteamGame, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab = tab
        self.service = tab.service
        self.game = game
        self._uninstall_armed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        top.addStretch()
        layout.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(36)
        self.cover = QLabel()
        self.cover.setFixedSize(DETAIL_W, DETAIL_H)
        self.cover.setPixmap(placeholder_cover(game.name, DETAIL_W, DETAIL_H))
        load_cover(self.service, game.appid, self.cover, DETAIL_W, DETAIL_H)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(10)
        self.title = QLabel(game.name)
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.facts = QLabel()
        self.facts.setObjectName("detailMeta")
        self.facts.setTextFormat(Qt.TextFormat.PlainText)
        info.addWidget(self.facts)
        self.description = QLabel(game.description)
        self.description.setWordWrap(True)
        self.description.setObjectName("detailMeta")
        info.addWidget(self.description)
        info.addStretch()

        actions = QHBoxLayout()
        self.main_button = big_button("", "primary")
        self.main_button.setMinimumWidth(260)
        self.main_button.clicked.connect(self.main_action)
        actions.addWidget(self.main_button)
        self.options_button = big_button("⚙ Options", checkable=True)
        self.options_button.toggled.connect(self.toggle_options)
        actions.addWidget(self.options_button)
        actions.addStretch()
        info.addLayout(actions)

        self.options_panel = QFrame()
        self.options_panel.setObjectName("card")
        options = QVBoxLayout(self.options_panel)
        proton_row = QHBoxLayout()
        proton_row.addWidget(QLabel("Proton"))
        self.proton_combo = QComboBox()
        self.proton_combo.setMinimumWidth(360)
        self.proton_combo.currentIndexChanged.connect(self.proton_chosen)
        proton_row.addWidget(self.proton_combo, 1)
        options.addLayout(proton_row)
        self.uninstall_button = big_button("🗑 Uninstall", "danger")
        self.uninstall_button.clicked.connect(self.uninstall_tapped)
        options.addWidget(self.uninstall_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_panel.hide()
        info.addWidget(self.options_panel)

        self.status = QLabel("")
        self.status.setObjectName("status")
        info.addWidget(self.status)
        body.addLayout(info, 1)
        layout.addLayout(body, 1)

        self._disarm_timer = QTimer(self)
        self._disarm_timer.setSingleShot(True)
        self._disarm_timer.timeout.connect(self._disarm_uninstall)
        self.downloading = False
        self._fetching_size = False
        self._last_sample = None
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self.poll_progress)
        self.refresh()
        self._fetch_size()
        if not game.installed and self._silent and self.service.install_progress(game.appid).state != "missing":
            self._start_watching()  # a download queued earlier is still running

    def refresh(self) -> None:
        g = self.game
        state = "Installed" if g.installed else "Not installed"
        if g.installed and g.update_pending:
            state += " · update pending"
        lines = [
            state,
            format_playtime(g.playtime_minutes),
            self.size_text(),
            f"Released: {format_date(g.release_date)}",
            f"Price: {format_price(g.price_cents, g.currency)}",
            f"Latest update: {format_date(g.last_updated)}",
        ]
        self.facts.setText("\n".join(line for line in lines if line))
        self.main_button.setText("▶  Play" if g.installed else ("Downloading…" if self.downloading else "⬇  Download"))
        self.main_button.setEnabled(g.installed or not self.downloading)
        self.uninstall_button.setVisible(g.installed)


    # Proton ---------------------------------------------------------------------------
    def fill_proton_choices(self) -> None:
        """Default + every installed Proton (official and custom like GE-Proton)."""
        tools = self.service.compat_tools() if hasattr(self.service, "compat_tools") else []
        current = self.service.compat_tool(self.game.appid) if hasattr(self.service, "compat_tool") else None
        self.proton_combo.blockSignals(True)
        self.proton_combo.clear()
        self.proton_combo.addItem("Default (Steam decides)", "")
        for tool in tools:
            self.proton_combo.addItem(tool.display, tool.name)
        if current and self.proton_combo.findData(current) < 0:
            self.proton_combo.addItem(f"{current} (not installed)", current)
        self.proton_combo.setCurrentIndex(max(0, self.proton_combo.findData(current or "")))
        self.proton_combo.blockSignals(False)

    def proton_chosen(self, _index: int) -> None:
        name = self.proton_combo.currentData() or None
        label = self.proton_combo.currentText()
        self.proton_combo.setEnabled(False)
        set_status(self.status, f"Switching to {label} - Steam restarts in the background…")
        appid = self.game.appid
        run_async(lambda: self.service.set_compat_tool(appid, name), self._proton_set,
                  lambda exc: self._proton_set((False, str(exc))), owner=self)

    def _proton_set(self, result) -> None:
        ok, message = result
        self.proton_combo.setEnabled(True)
        set_status(self.status, message, error=not ok)
        if not ok:
            self.fill_proton_choices()  # show what's really set

    def game_session_ended(self, appid: int, failed: bool) -> None:
        """Called when the launched game exits (or never started)."""
        if appid != self.game.appid:
            return
        if failed:
            set_status(self.status, f"{self.game.name} didn't start - check Steam", error=True)
        else:
            set_status(self.status, "")

    def size_text(self) -> str:
        g = self.game
        if g.installed and g.size_on_disk:
            return f"Size on disk: {format_size(g.size_on_disk)}"
        if g.store_size:
            return f"Size: ~{format_size(g.store_size)} (store)"
        return "Size: loading…" if self._fetching_size else "Size: unknown"

    def _fetch_size(self) -> None:
        """Not installed and no size yet: ask the store now instead of waiting for the library."""
        needs = getattr(self.service, "needs_metadata", None)
        if self.game.store_size or (self.game.installed and self.game.size_on_disk) or not callable(needs) \
                or not needs(self.game):
            return
        self._fetching_size = True
        self.refresh()  # "Size: loading…"
        appid = self.game.appid
        run_async(lambda: self.service.fetch_metadata(appid), self._size_fetched,
                  lambda _e: self._size_fetched(None), owner=self)

    def _size_fetched(self, _meta) -> None:
        self._fetching_size = False
        if _meta is not None:
            self.service.apply_metadata(self.game)
        self.refresh()

    @property
    def _silent(self) -> bool:
        return getattr(self.service, "silent_install", False)

    def main_action(self) -> None:
        client = self.service.client
        if self.game.installed:
            ok = client.play(self.game.appid)
            set_status(self.status, f"Starting {self.game.name}…" if ok else "Could not reach Steam - is it installed?",
                       error=not ok)
            return
        if not self._silent:
            ok = client.install(self.game.appid)
            set_status(self.status, "Download started in Steam" if ok else "Could not reach Steam - is it installed?",
                       error=not ok)
            return
        self.downloading = True
        self.refresh()
        set_status(self.status, "Preparing the download - Steam restarts in the background…")
        appid, name = self.game.appid, self.game.name
        run_async(lambda: self.service.install_game(appid, name), self._install_started,
                  lambda exc: self._install_started(InstallResult(False, str(exc))), owner=self)

    def _install_started(self, result) -> None:
        if not result.ok:
            self.downloading = False
            self.refresh()
            set_status(self.status, result.message, error=True)
            return
        set_status(self.status, result.message)
        self._start_watching()

    def _start_watching(self) -> None:
        self.downloading = True
        self.refresh()
        self._progress_timer.start(PROGRESS_INTERVAL_MS)
        self.poll_progress()

    def _speed(self) -> str:
        """Current download speed from the network counters (between two polls)."""
        sampler = getattr(self.service, "io_sample", None)
        if not callable(sampler):
            return ""
        from gamingcrypt.system.io_stats import rate
        from gamingcrypt.ui.downloads_tab import format_rate

        sample = sampler(None)
        value = rate(self._last_sample, sample, "net_rx")
        self._last_sample = sample
        return format_rate(value) if value is not None else ""

    def poll_progress(self) -> None:
        p = self.service.install_progress(self.game.appid)
        if p.state == "installed":
            self._progress_timer.stop()
            self.downloading = False
            self.game.installed = True
            self.game.update_pending = False
            self.refresh()
            set_status(self.status, f"{self.game.name} is installed ✓")
        elif p.state == "downloading":
            speed = self._speed()
            set_status(self.status, f"Downloading {p.percent:.0f}% · {format_size(p.downloaded)} of "
                                    f"{format_size(p.total)}" + (f" · {speed}" if speed else ""))
        elif p.state == "queued":
            set_status(self.status, "Waiting for Steam to start the download…")
        else:
            self._progress_timer.stop()
            self.downloading = False
            self.refresh()
            set_status(self.status, "The download was cancelled in Steam", error=True)

    def toggle_options(self, visible: bool) -> None:
        if visible:
            self.fill_proton_choices()
        self.options_panel.setVisible(visible)
        if not visible:
            self._disarm_uninstall()

    def uninstall_tapped(self) -> None:
        if not self._uninstall_armed:
            self._uninstall_armed = True
            self.uninstall_button.setText("Tap again to uninstall")
            self._disarm_timer.start(4000)
            return
        self._disarm_uninstall()
        if not getattr(self.service, "silent_uninstall", False):
            ok = self.service.client.uninstall(self.game.appid)
            set_status(self.status, "Confirm the uninstall in Steam" if ok else "Could not reach Steam", error=not ok)
            return
        self.uninstall_button.setEnabled(False)
        self.main_button.setEnabled(False)
        set_status(self.status, f"Uninstalling {self.game.name}…")
        appid = self.game.appid
        run_async(lambda: self.service.uninstall_game(appid), self._uninstalled,
                  lambda exc: self._uninstalled(InstallResult(False, str(exc))), owner=self)

    def _uninstalled(self, result) -> None:
        self.uninstall_button.setEnabled(True)
        if result.ok:
            self.game.installed = False
            self.game.size_on_disk = 0
            self.options_button.setChecked(False)
        self.refresh()
        set_status(self.status, result.message, error=not result.ok)

    def _disarm_uninstall(self) -> None:
        self._uninstall_armed = False
        self.uninstall_button.setText("🗑 Uninstall")

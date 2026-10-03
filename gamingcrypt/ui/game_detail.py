"""Detail page of a single game: play / download and an options menu (uninstall)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.webapi import format_price
from gamingcrypt.ui.game_widgets import format_date, format_playtime, format_size, load_cover, placeholder_cover
from gamingcrypt.ui.widgets import big_button, set_status

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
        self.uninstall_button = big_button("🗑 Uninstall", "danger")
        self.uninstall_button.clicked.connect(self.uninstall_tapped)
        options.addWidget(self.uninstall_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.no_options = QLabel("No options available - the game is not installed")
        self.no_options.setObjectName("detailMeta")
        options.addWidget(self.no_options)
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
        self.refresh()

    def refresh(self) -> None:
        g = self.game
        state = "Installed" if g.installed else "Not installed"
        if g.installed and g.update_pending:
            state += " · update pending"
        lines = [
            state,
            format_playtime(g.playtime_minutes),
            f"Size on disk: {format_size(g.size_on_disk)}" if g.installed else None,
            f"Released: {format_date(g.release_date)}",
            f"Price: {format_price(g.price_cents, g.currency)}",
            f"Latest update: {format_date(g.last_updated)}",
        ]
        self.facts.setText("\n".join(line for line in lines if line))
        self.main_button.setText("▶  Play" if g.installed else "⬇  Download")
        self.uninstall_button.setVisible(g.installed)
        self.no_options.setVisible(not g.installed)

    def main_action(self) -> None:
        client = self.service.client
        if self.game.installed:
            ok = client.play(self.game.appid)
            message = f"Starting {self.game.name}…"
        else:
            ok = client.install(self.game.appid)
            message = "Download started in Steam"
        set_status(self.status, message if ok else "Could not reach Steam - is it installed?", error=not ok)

    def toggle_options(self, visible: bool) -> None:
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
        ok = self.service.client.uninstall(self.game.appid)
        set_status(self.status, "Confirm the uninstall in Steam" if ok else "Could not reach Steam", error=not ok)

    def _disarm_uninstall(self) -> None:
        self._uninstall_armed = False
        self.uninstall_button.setText("🗑 Uninstall")

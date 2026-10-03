"""The whole Steam library with sorting; prices / dates are fetched in the background."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.sorting import SORT_OPTIONS, sort_games
from gamingcrypt.ui.game_widgets import GameCard
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, FoldingHeader, big_button, enable_touch_scroll

METADATA_SORTS = {"release_date", "price", "last_update"}


class SteamLibraryPage(QWidget):
    # Steam's store API allows ~200 requests / 5 min; we do 2 per game.
    FETCH_DELAY_MS = 1500

    def __init__(self, tab, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab = tab
        self.service = tab.service
        self.games: dict[int, SteamGame] = {}
        self.cards: dict[int, GameCard] = {}
        self.order: list[int] = []
        self.sort_key = "name"
        self.descending = SORT_OPTIONS["name"][1]
        self.loading = True
        self._pending: list[int] = []
        self._fetch_total = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        self.header = QWidget()
        header = QVBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel("Steam")
        title.setObjectName("title")
        top.addWidget(title)
        self.count_label = QLabel("")
        self.count_label.setObjectName("subtitle")
        top.addWidget(self.count_label)
        top.addStretch()
        self.store_button = big_button("🛒 Store", "primary")
        self.store_button.clicked.connect(tab.open_store)
        top.addWidget(self.store_button)
        header.addLayout(top)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort:"))
        self.sort_buttons = {}
        for key, (label, _desc) in SORT_OPTIONS.items():
            button = big_button(label, checkable=True)
            button.clicked.connect(lambda _=False, k=key: self.set_sort(k))
            self.sort_buttons[key] = button
            sort_row.addWidget(button)
        self.direction_button = big_button("")
        self.direction_button.clicked.connect(self.toggle_direction)
        sort_row.addWidget(self.direction_button)
        sort_row.addStretch()
        header.addLayout(sort_row)

        self.status = QLabel("Loading library…")
        self.status.setObjectName("status")
        header.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        self.grid_widget = QWidget()
        self.grid = FlowLayout(self.grid_widget)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll, 1)
        self.scroll = scroll
        self.folding = FoldingHeader(scroll, self.header)

        self._update_sort_buttons()
        run_async(self.service.load_library, self._loaded, self._load_failed, owner=self)

    # loading ----------------------------------------------------------------
    def _loaded(self, games: list[SteamGame]) -> None:
        self.loading = False
        self.games = {g.appid: g for g in games}
        self.tab.games.update(self.games)
        self.grid.clear()
        self.cards = {}
        for game in games:
            card = GameCard(game, self.service, self.sort_key)
            card.clicked.connect(self.tab.open_game)
            self.cards[game.appid] = card
        installed = sum(1 for g in games if g.installed)
        account = self.service.account() if hasattr(self.service, "account") else None
        prefix = f"{account['name']} · " if account else ""
        self.count_label.setText(f"{prefix}{len(games)} games · {installed} installed")
        self.apply_sort()
        self.status.setText(self.empty_hint(games))
        self._pending = [g.appid for g in games if self.service.needs_metadata(g)]
        self._fetch_total = len(self._pending)
        self._fetch_next()

    def empty_hint(self, games: list[SteamGame]) -> str:
        """Explain *why* the list is short instead of just showing "0 games"."""
        full = getattr(self.service, "full_library_available", True)
        if getattr(self.service, "root", True) is None:
            return "Steam wasn't found on this device. Install Steam and log in once, then open this page again."
        if not games and not full:
            return ("No installed games yet. To see every game you own, add your Steam Web API key "
                    "in Settings → Steam.")
        if not games:
            return "No Steam games found."
        if not full:
            return "Showing installed games only - add your Steam Web API key in Settings → Steam to see your whole library."
        return ""

    def _load_failed(self, exc: Exception) -> None:
        self.loading = False
        self.status.setText(f"Could not load the library: {exc}")

    def _fetch_next(self) -> None:
        if not self._pending:
            if self._fetch_total and self.sort_key in METADATA_SORTS:
                self.apply_sort()
            return
        appid = self._pending.pop(0)
        done = self._fetch_total - len(self._pending)
        self.count_label.setToolTip(f"Loading store data {done}/{self._fetch_total}")
        run_async(lambda: self.service.fetch_metadata(appid),
                  lambda _m: self._metadata_done(appid), lambda _e: self._metadata_done(appid), owner=self)

    def _metadata_done(self, appid: int) -> None:
        game = self.games.get(appid)
        if game is not None:
            self.service.apply_metadata(game)
            self.cards[appid].set_sort_key(self.sort_key)
        delay = self.FETCH_DELAY_MS if self._pending else 0
        QTimer.singleShot(delay, self, self._fetch_next)

    # sorting ----------------------------------------------------------------
    def set_sort(self, key: str) -> None:
        if key == self.sort_key:
            self.descending = not self.descending
        else:
            self.sort_key = key
            self.descending = SORT_OPTIONS[key][1]
        self._update_sort_buttons()
        self.apply_sort()

    def toggle_direction(self) -> None:
        self.descending = not self.descending
        self._update_sort_buttons()
        self.apply_sort()

    def _update_sort_buttons(self) -> None:
        for key, button in self.sort_buttons.items():
            button.setChecked(key == self.sort_key)
        self.direction_button.setText("↓ Desc" if self.descending else "↑ Asc")

    def apply_sort(self) -> None:
        ordered = sort_games(list(self.games.values()), self.sort_key, self.descending)
        self.order = [g.appid for g in ordered]
        self.grid.take_all()
        for appid in self.order:
            card = self.cards[appid]
            card.set_sort_key(self.sort_key)
            self.grid.addWidget(card)
        self.grid.invalidate()

    def on_return(self) -> None:
        # Coming back from a game page: install state may have changed.
        run_async(self.service.load_library, self._refreshed, owner=self)

    def _refreshed(self, games: list[SteamGame]) -> None:
        for game in games:
            if game.appid in self.games:
                self.games[game.appid].installed = game.installed
                self.cards[game.appid].game = self.games[game.appid]
                self.cards[game.appid].set_sort_key(self.sort_key)

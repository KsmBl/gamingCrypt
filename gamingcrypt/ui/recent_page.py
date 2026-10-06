"""Library "Recently played": the last 10 games you played, newest first."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.game_widgets import GameCard, format_date
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, enable_touch_scroll

LIMIT = 10


def recently_played(games: list[SteamGame], limit: int = LIMIT) -> list[SteamGame]:
    played = [g for g in games if g.last_played]
    return sorted(played, key=lambda g: g.last_played, reverse=True)[:limit]


class RecentPage(QWidget):
    title_text = "Recently played"

    def __init__(self, tab, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab = tab
        self.service = tab.service
        self.loading = True
        self.order: list[int] = []
        self.cards: dict[int, GameCard] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(self.title_text)
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        layout.addLayout(top)
        self.status = QLabel("Loading…")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        self.grid_widget = QWidget()
        self.grid = FlowLayout(self.grid_widget)
        scroll.setWidget(self.grid_widget)
        layout.addWidget(scroll, 1)
        run_async(self.service.load_library, self._loaded,
                  lambda exc: self._failed(exc), owner=self)

    def _loaded(self, games: list[SteamGame]) -> None:
        self.loading = False
        roms = [r for rs in getattr(self.tab, "roms", {}).values() for r in rs if r.last_played]
        recent = recently_played(list(games) + roms)  # Steam and emulated games together
        self.order = [g.appid for g in recent]
        for game in recent:
            card = self._card(game)
            card.meta.setText(("● " if getattr(game, "installed", True) else "") + f"Played {format_date(game.last_played)}")
            self.cards[game.appid] = card
            self.grid.addWidget(card)
        self.status.setText("" if recent else "You haven't played any game yet")
        self._focus_first()

    def _focus_first(self) -> None:
        from gamingcrypt.ui.widgets import settle_focus

        if self.order:
            settle_focus(self, self.cards.get(self.order[0]))  # the first game, not "‹ Back"

    def _card(self, game):
        """GameCard for Steam games, RomCard for emulated ones."""
        from gamingcrypt.emulation.library import RomGame

        if isinstance(game, RomGame):
            from gamingcrypt.ui.emulation_pages import RomCard

            card = RomCard(game, covers=getattr(self.tab, "covers", None))
            card.clicked.connect(self.tab.open_rom)
            return card
        self.tab.games[game.appid] = game  # so the game page can open
        card = GameCard(game, self.service)
        card.clicked.connect(self.tab.open_game)
        return card

    def _failed(self, exc: Exception) -> None:
        self.loading = False
        self.status.setText(f"Could not load your games: {exc}")


class FavoritesPage(RecentPage):
    """Library "Favorites": the games starred on their page."""

    title_text = "Favorites"

    def _loaded(self, games: list[SteamGame]) -> None:
        self.loading = False
        wanted = set(self.tab.profiles.favorites())
        roms = [r for rs in getattr(self.tab, "roms", {}).values() for r in rs]
        favorites = sorted((g for g in list(games) + roms if g.appid in wanted), key=lambda g: g.name.lower())
        self.order = [g.appid for g in favorites]
        for game in favorites:
            card = self._card(game)
            self.cards[game.appid] = card
            self.grid.addWidget(card)
        self.status.setText("" if favorites else "No favorites yet - tap ☆ Favorite on a game's page")
        self._focus_first()

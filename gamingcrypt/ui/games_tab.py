"""Games tab: search installed games, enter a source (Steam) and navigate deeper."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.sorting import filter_games, sort_games
from gamingcrypt.ui.game_widgets import GameCard, SourceCard
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, KeyboardFocusFilter, OnScreenKeyboard, big_button, enable_touch_scroll


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label


class GamesHome(QWidget):
    def __init__(self, tab: "GamesTab"):
        super().__init__()
        self.tab = tab
        self.installed: list[SteamGame] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 10)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search installed games")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_results)
        layout.addWidget(self.search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 10, 0, 10)

        self.sources_heading = heading("Libraries")
        self.content_layout.addWidget(self.sources_heading)
        sources = QHBoxLayout()
        self.steam_card = SourceCard("Steam", "Your Steam library")
        self.steam_card.tapped.connect(tab.open_steam)
        sources.addWidget(self.steam_card)
        sources.addStretch()
        self.sources = QWidget()
        self.sources.setLayout(sources)
        self.content_layout.addWidget(self.sources)

        self.results_heading = heading("Installed games")
        self.content_layout.addWidget(self.results_heading)
        self.grid_widget = QWidget()
        self.grid = FlowLayout(self.grid_widget)
        self.content_layout.addWidget(self.grid_widget)
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("subtitle")
        self.content_layout.addWidget(self.empty_label)
        self.content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.keyboard.hide)
        self.keyboard.hide()
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)

    def set_installed(self, games: list[SteamGame]) -> None:
        self.installed = sort_games(games, "name")
        self.refresh_results()

    def refresh_results(self) -> None:
        query = self.search.text()
        searching = bool(query.strip())
        self.sources.setVisible(not searching)
        self.sources_heading.setVisible(not searching)
        self.results_heading.setText(f'Results for "{query.strip()}"' if searching else "Installed games")
        matches = filter_games(self.installed, query, installed_only=True)
        self.grid.clear()
        for game in matches:
            card = GameCard(game, self.tab.service)
            card.clicked.connect(self.tab.open_game)
            self.grid.addWidget(card)
        self.result_appids = [g.appid for g in matches]
        if matches:
            self.empty_label.setText("")
        elif searching:
            self.empty_label.setText("No installed game matches your search")
        else:
            self.empty_label.setText("No installed games found")


class GamesTab(QStackedWidget):
    """Navigation stack: home -> Steam library -> game details / store."""

    def __init__(self, service, parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.games: dict[int, SteamGame] = {}
        self.home = GamesHome(self)
        self.addWidget(self.home)
        self.reload_installed()

    # navigation -------------------------------------------------------------
    def push(self, page: QWidget) -> None:
        self.addWidget(page)
        self.setCurrentWidget(page)

    def back(self) -> None:
        page = self.currentWidget()
        if page is self.home:
            return
        self.removeWidget(page)
        page.deleteLater()
        self.setCurrentIndex(self.count() - 1)
        current = self.currentWidget()
        if hasattr(current, "on_return"):
            current.on_return()
        if current is self.home:
            self.reload_installed()

    def back_button(self) -> QWidget:
        button = big_button("‹ Back")
        button.clicked.connect(self.back)
        return button

    # data -------------------------------------------------------------------
    def reload_installed(self) -> None:
        run_async(self.service.installed_games, self._installed_loaded, owner=self)

    def _installed_loaded(self, games: list[SteamGame]) -> None:
        for game in games:
            self.games[game.appid] = game
        self.home.set_installed(games)

    # entry points (filled by the library / detail / store pages) -------------
    def open_steam(self) -> None:
        from gamingcrypt.ui.steam_page import SteamLibraryPage

        self.push(SteamLibraryPage(self))

    def open_game(self, appid: int) -> None:
        from gamingcrypt.ui.game_detail import GameDetailPage

        game = self.games.get(appid)
        if game is not None:
            self.push(GameDetailPage(self, game))

    def open_store(self) -> None:
        pass

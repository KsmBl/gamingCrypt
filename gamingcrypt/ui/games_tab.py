"""Games tab: search installed games, enter a source (Steam) and navigate deeper."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.sorting import filter_games, sort_games
from gamingcrypt.ui.game_widgets import GameCard, SourceCard
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import (
    FlowLayout,
    FoldingHeader,
    KeyboardFocusFilter,
    OnScreenKeyboard,
    big_button,
    enable_touch_scroll,
    focus_and_reveal,
    set_status,
)


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("cardTitle")
    return label


class GamesHome(QWidget):
    def __init__(self, tab: "GamesTab"):
        super().__init__()
        self.tab = tab
        self.installed: list[SteamGame] = []
        self.cards: dict[int, GameCard] = {}
        self.selected_appid: int | None = None
        self.result_appids: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 10)

        self.header = QWidget()
        header = QVBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search installed games")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_results)
        header.addWidget(self.search)
        self.notice = QLabel("")
        self.notice.setObjectName("status")
        self.notice.setWordWrap(True)
        self.notice.hide()
        header.addWidget(self.notice)

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
        self.recent_card = SourceCard("Recently played", "Your last 10 games")
        self.recent_card.tapped.connect(tab.open_recent)
        sources.addWidget(self.recent_card)
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
        self.folding = FoldingHeader(scroll, self.header)

        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.keyboard.hide)
        self.keyboard.hide()
        self.keyboard.dismissable = True
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)

    def remember_selection(self, appid: int) -> None:
        self.selected_appid = appid

    def show_notice(self, text: str, error: bool = False) -> None:
        set_status(self.notice, text, error=error)
        self.notice.setVisible(bool(text))

    def set_installed(self, games: list[SteamGame]) -> None:
        self.installed = sort_games([g for g in games if g.installed], "name")
        self.refresh_results()

    def refresh_results(self) -> None:
        query = self.search.text()
        searching = bool(query.strip())
        self.sources.setVisible(not searching)
        self.sources_heading.setVisible(not searching)
        self.results_heading.setText(f'Results for "{query.strip()}"' if searching else "Installed games")
        matches = filter_games(self.installed, query, installed_only=True)
        focused = self.window().focusWidget() if self.window() else None
        if isinstance(focused, GameCard):
            self.selected_appid = focused.game.appid
        # cards are made once and only re-ordered: typing must stay fast
        for card in self.grid.take_all():
            card.hide()
        for game in matches:
            card = self.cards.get(game.appid)
            if card is None or card.game is not game:
                if card is not None:
                    card.deleteLater()
                card = GameCard(game, self.tab.service)
                card.clicked.connect(self.tab.open_game)
                self.cards[game.appid] = card
            self.grid.addWidget(card)
            card.show()
        self.grid.invalidate()
        self.result_appids = [g.appid for g in matches]
        card = self.cards.get(self.selected_appid) if self.selected_appid is not None else None
        if card is not None and card.isVisible() and isinstance(focused, GameCard):
            focus_and_reveal(card)  # hiding/re-adding cards must not lose the selection
        if matches:
            self.empty_label.setText("")
        elif searching:
            self.empty_label.setText("No installed game matches your search")
        else:
            self.empty_label.setText("No installed games found")


class GamesTab(QStackedWidget):
    """Navigation stack: home -> Steam library -> game details / store."""

    def __init__(self, service, library_path: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.service = service
        self.games: dict[int, SteamGame] = {}
        self._came_from: list = []
        self.home = GamesHome(self)
        self.addWidget(self.home)
        self.reload_installed()
        if library_path:
            self.home.show_notice("Setting up your encrypted drive as Steam library…")
            run_async(lambda: self.service.ensure_library(library_path), self._library_checked,
                      lambda exc: self.home.show_notice(f"Could not set up the Steam library: {exc}", error=True),
                      owner=self)

    def _library_checked(self, result) -> None:
        if result.status == "added":
            self.home.show_notice("✓ " + result.message)
            self.reload_installed()
        elif result.status in ("failed", "no_steam"):
            self.home.show_notice(result.message, error=True)
        else:
            self.home.show_notice("")

    # navigation -------------------------------------------------------------
    def push(self, page: QWidget) -> None:
        # remember what was selected, so "back" can select it again
        self._came_from.append(self.window().focusWidget() if self.window() else None)
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
        previous = self._came_from.pop() if self._came_from else None
        if previous is not None and shiboken6.isValid(previous) and current.isAncestorOf(previous):
            if isinstance(previous, GameCard) and current is self.home:
                self.home.remember_selection(previous.game.appid)
            if previous.isVisible():
                focus_and_reveal(previous)
        if hasattr(current, "on_return"):
            current.on_return()
        if current is self.home:
            self.reload_installed()

    def gamepad_back(self) -> bool:
        if self.currentWidget() is self.home:
            return False
        self.back()
        return True

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

    # entry points -----------------------------------------------------------
    def open_steam(self) -> None:
        from gamingcrypt.ui.steam_page import SteamLibraryPage

        self.push(SteamLibraryPage(self))

    def open_game(self, appid: int) -> None:
        from gamingcrypt.ui.game_detail import GameDetailPage

        game = self.games.get(appid)
        if game is not None:
            page = GameDetailPage(self, game)
            self.push(page)
            page.main_button.setFocus()  # Play / Download is the obvious next step

    def open_recent(self) -> None:
        from gamingcrypt.ui.recent_page import RecentPage

        self.push(RecentPage(self))

    def open_store(self) -> None:
        from gamingcrypt.ui.store_page import StorePage

        self.push(StorePage(self))

import pytest
from PySide6.QtCore import QPoint, Qt

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.game_widgets import GameCard, format_date, format_playtime, format_size, meta_text
from gamingcrypt.ui.games_tab import GamesTab
from tests.fakes import FakeService


def make_tab(qtbot, service=None):
    tab = GamesTab(service or FakeService())
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.installed != [])
    return tab


def test_formatters():
    assert format_date(None) == "-"
    assert format_date(1303084800) == "18 Apr 2011"
    assert format_size(0) == "-"
    assert format_size(12_000_000_000) == "11.2 GB"
    assert format_size(500) == "500 B"
    assert format_playtime(0) == "Never played"
    assert format_playtime(30) == "30 min played"
    assert format_playtime(90) == "1.5 h played"


def test_meta_text_follows_sort_key():
    g = SteamGame(1, "X", release_date=1303084800, price_cents=195, currency="EUR", last_updated=1303084800)
    assert meta_text(g, "release_date") == "Released 18 Apr 2011"
    assert meta_text(g, "price") == "1.95 €"
    assert meta_text(g, "last_update") == "Updated 18 Apr 2011"
    assert meta_text(g, "name") == "Not installed"


def test_home_lists_only_installed_games(qtbot):
    tab = make_tab(qtbot)
    assert tab.home.result_appids == [1145360, 620]  # Hades, Portal 2 - not Portal / Witcher
    assert tab.home.results_heading.text() == "Installed games"
    assert tab.home.sources.isVisibleTo(tab.home)
    assert not hasattr(tab.home, "filter_buttons")


def test_search_installed_only(qtbot):
    tab = make_tab(qtbot)
    tab.home.search.setText("portal")
    assert tab.home.result_appids == [620]  # "Portal" isn't installed
    assert not tab.home.sources.isVisibleTo(tab.home)
    tab.home.search.setText("zzz")
    assert tab.home.result_appids == []
    assert "No installed game matches" in tab.home.empty_label.text()


def test_cards_are_reused_while_typing(qtbot):
    tab = make_tab(qtbot)
    card = tab.home.cards[620]
    tab.home.search.setText("por")
    tab.home.search.setText("")
    assert tab.home.cards[620] is card


def test_not_installed_never_listed(qtbot):
    from gamingcrypt.steam.models import SteamGame

    tab = make_tab(qtbot)
    tab.home.set_installed([SteamGame(1, "Queued", installed=False), SteamGame(2, "Done", installed=True)])
    assert tab.home.result_appids == [2]


def test_no_installed_games(qtbot):
    tab = GamesTab(FakeService(games=[]))
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.empty_label.text() != "")
    assert "No installed games" in tab.home.empty_label.text()


# --- Recently played ---------------------------------------------------------------

def test_recently_played_library(qtbot):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.recent_page import RecentPage

    games = [SteamGame(i, f"Game {i}", installed=i % 2 == 0, last_played=1_700_000_000 + i * 1000)
             for i in range(1, 15)]
    games.append(SteamGame(99, "Never played"))
    service = FakeService(games=games)
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.home.recent_card.tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, RecentPage)
    qtbot.waitUntil(lambda: not page.loading)
    assert page.order == [14, 13, 12, 11, 10, 9, 8, 7, 6, 5]  # last 10, newest first
    assert page.cards[14].meta.text().startswith("● Played ")  # installed marker + date
    assert not page.cards[13].meta.text().startswith("●")
    page.cards[13].tapped.emit()  # not installed -> still opens its game page
    from gamingcrypt.ui.game_detail import GameDetailPage

    assert isinstance(tab.currentWidget(), GameDetailPage) and tab.currentWidget().game.appid == 13
    tab.back()
    assert tab.currentWidget() is page


def test_recently_played_empty(qtbot):
    from gamingcrypt.ui.recent_page import RecentPage

    tab = GamesTab(FakeService(games=[]))
    qtbot.addWidget(tab)
    tab.open_recent()
    page = tab.currentWidget()
    assert isinstance(page, RecentPage)
    qtbot.waitUntil(lambda: not page.loading)
    assert "haven't played" in page.status.text()


def test_keyboard_appears_on_search_tap(qtbot):
    tab = make_tab(qtbot)
    tab.show()
    assert tab.home.keyboard.isHidden()
    qtbot.mouseClick(tab.home.search, Qt.MouseButton.LeftButton)
    assert not tab.home.keyboard.isHidden()
    tab.home.keyboard.type_text("hades")
    assert tab.home.result_appids == [1145360]
    tab.home.keyboard.submitted.emit()
    assert tab.home.keyboard.isHidden()


def test_card_tap_vs_flick(qtbot):
    card = GameCard(SteamGame(5, "Celeste", installed=True))
    qtbot.addWidget(card)
    card.show()
    clicks = []
    card.clicked.connect(clicks.append)
    qtbot.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    assert clicks == [5]
    qtbot.mousePress(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))
    qtbot.mouseRelease(card, Qt.MouseButton.LeftButton, pos=QPoint(50, 200))
    assert clicks == [5]
    assert card.meta.text().startswith("● ")


def test_navigation_stack(qtbot):
    from PySide6.QtWidgets import QLabel

    tab = make_tab(qtbot)
    page = QLabel("page")
    tab.push(page)
    assert tab.currentWidget() is page
    tab.back()
    assert tab.currentWidget() is tab.home
    tab.back()  # no-op on home
    assert tab.currentWidget() is tab.home


def test_keyboard_not_shown_on_programmatic_focus(qtbot):
    tab = make_tab(qtbot)
    tab.show()
    tab.home.search.setFocus()
    assert tab.home.keyboard.isHidden()


def test_library_setup_notice(qtbot):
    from gamingcrypt.steam.library_setup import LibraryResult

    service = FakeService()
    calls = []

    def ensure(path):
        calls.append(path)
        return LibraryResult("added", f"Your encrypted drive ({path}) is now a Steam library")

    service.ensure_library = ensure
    tab = GamesTab(service, library_path="/home/me/GamingCrypt")
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: "✓" in tab.home.notice.text())
    assert calls == ["/home/me/GamingCrypt"]
    assert tab.home.notice.isVisibleTo(tab.home)


def test_library_setup_failure_and_quiet_cases(qtbot):
    from gamingcrypt.steam.library_setup import LibraryResult

    service = FakeService()
    service.ensure_library = lambda path: LibraryResult("failed", "Close Steam so GamingCrypt can add it")
    tab = GamesTab(service, library_path="/x")
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: "Close Steam" in tab.home.notice.text())
    assert tab.home.notice.property("error") is True
    service.ensure_library = lambda path: LibraryResult("already")
    tab2 = GamesTab(service, library_path="/x")
    qtbot.addWidget(tab2)
    qtbot.waitUntil(lambda: not tab2.home.notice.isVisibleTo(tab2.home))


def test_no_library_path_means_no_setup(qtbot):
    service = FakeService()
    service.ensure_library = lambda path: pytest.fail("must not run")
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    assert tab.home.notice.isHidden()

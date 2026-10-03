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


def test_home_lists_all_games_with_filters(qtbot):
    tab = make_tab(qtbot)
    # installed ones come first (local), the rest of the library follows
    qtbot.waitUntil(lambda: len(tab.home.result_appids) == 4)
    assert tab.home.result_appids == [1145360, 400, 620, 292030]  # Hades, Portal, Portal 2, Witcher
    assert tab.home.filter_buttons["all"].isChecked() and tab.home.results_heading.text() == "All games"
    tab.home.filter_buttons["installed"].click()
    assert tab.home.result_appids == [1145360, 620]
    tab.home.filter_buttons["not_installed"].click()
    assert tab.home.result_appids == [400, 292030]
    assert tab.home.sources.isVisibleTo(tab.home)


def test_search_within_filter(qtbot):
    tab = make_tab(qtbot)
    qtbot.waitUntil(lambda: len(tab.home.result_appids) == 4)
    tab.home.search.setText("portal")
    assert tab.home.result_appids == [400, 620]  # installed or not
    assert not tab.home.sources.isVisibleTo(tab.home)
    assert "portal" in tab.home.results_heading.text()
    tab.home.filter_buttons["installed"].click()
    assert tab.home.result_appids == [620]
    tab.home.search.setText("zzz")
    assert tab.home.result_appids == []
    assert "No game matches" in tab.home.empty_label.text()


def test_cards_are_reused_while_typing(qtbot):
    tab = make_tab(qtbot)
    qtbot.waitUntil(lambda: len(tab.home.result_appids) == 4)
    portal_card = tab.home.cards[620]
    tab.home.search.setText("por")
    tab.home.search.setText("")
    assert tab.home.cards[620] is portal_card


def test_slower_library_never_uninstalls_a_game(qtbot):
    from gamingcrypt.steam.models import SteamGame

    tab = make_tab(qtbot)
    tab.home.set_library([SteamGame(620, "Portal 2", installed=False)])  # stale/offline list
    assert tab.home.all_games[620].installed


def test_no_installed_games(qtbot):
    tab = GamesTab(FakeService(games=[]))
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.empty_label.text() != "")
    assert "No games found" in tab.home.empty_label.text()
    tab.home.filter_buttons["not_installed"].click()
    assert tab.home.empty_label.text() == "Every game is installed"


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

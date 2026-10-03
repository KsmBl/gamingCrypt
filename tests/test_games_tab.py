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


def test_home_lists_only_installed_games_sorted(qtbot):
    tab = make_tab(qtbot)
    assert tab.home.result_appids == [1145360, 620]  # Hades, Portal 2
    assert tab.home.sources.isVisibleTo(tab.home)


def test_search_filters_installed_only(qtbot):
    tab = make_tab(qtbot)
    tab.home.search.setText("portal")
    assert tab.home.result_appids == [620]  # "Portal" (not installed) is excluded
    assert not tab.home.sources.isVisibleTo(tab.home)
    assert "portal" in tab.home.results_heading.text()
    tab.home.search.setText("zzz")
    assert tab.home.result_appids == []
    assert "No installed game" in tab.home.empty_label.text()


def test_no_installed_games(qtbot):
    tab = GamesTab(FakeService(games=[]))
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.empty_label.text() != "")
    assert "No installed games" in tab.home.empty_label.text()


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

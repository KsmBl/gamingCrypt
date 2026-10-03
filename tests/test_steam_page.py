from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.steam_page import SteamLibraryPage
from tests.fakes import FakeService


def open_page(qtbot, service=None):
    SteamLibraryPage.FETCH_DELAY_MS = 0
    tab = GamesTab(service or FakeService())
    qtbot.addWidget(tab)
    tab.home.steam_card.tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, SteamLibraryPage)
    qtbot.waitUntil(lambda: not page.loading)
    return tab, page


def test_shows_whole_library_sorted_by_name(qtbot):
    tab, page = open_page(qtbot)
    assert page.order == [1145360, 400, 620, 292030]  # Hades, Portal, Portal 2, The Witcher 3
    assert "4 games · 2 installed" == page.count_label.text()
    assert page.sort_buttons["name"].isChecked()


def test_sort_by_each_key(qtbot):
    tab, page = open_page(qtbot)
    page.sort_buttons["playtime"].click()
    assert page.order == [292030, 620, 1145360, 400]
    assert page.cards[292030].meta.text() == "100.0 h played"
    page.sort_buttons["price"].click()
    assert page.order[:2] == [292030, 620]
    assert page.cards[620].meta.text() == "● 1.95 €"
    page.sort_buttons["release_date"].click()
    assert page.order[:2] == [292030, 620]  # newest first: 2015 before 2011
    page.sort_buttons["last_update"].click()
    assert page.order[:2] == [1145360, 620]


def test_direction_toggle_and_same_button(qtbot):
    tab, page = open_page(qtbot)
    page.direction_button.click()
    assert page.descending and page.direction_button.text() == "↓ Desc"
    assert page.order[0] == 292030  # The Witcher 3
    page.sort_buttons["name"].click()  # tapping the active sort flips direction
    assert not page.descending
    assert page.order[0] == 1145360


def test_unknown_values_go_last(qtbot):
    tab, page = open_page(qtbot)
    page.set_sort("price")
    page.toggle_direction()
    assert page.order[-2:] == [1145360, 400]  # no price known, sorted by name


def test_metadata_is_fetched_in_background(qtbot):
    service = FakeService(metadata={400: {"price_cents": 499, "currency": "EUR", "release_date": 1191888000}})
    tab, page = open_page(qtbot, service)
    qtbot.waitUntil(lambda: service.fetched == [400])
    qtbot.waitUntil(lambda: page.games[400].price_cents == 499)
    page.set_sort("price")
    assert page.cards[400].meta.text() == "4.99 €"


def test_empty_library_and_local_only_hint(qtbot):
    tab, page = open_page(qtbot, FakeService(games=[]))
    assert "No Steam games" in page.status.text()
    service = FakeService()
    service.full_library_available = False
    tab, page = open_page(qtbot, service)
    assert "API key" in page.status.text()


def test_back_returns_home(qtbot):
    tab, page = open_page(qtbot)
    tab.back()
    assert tab.currentWidget() is tab.home

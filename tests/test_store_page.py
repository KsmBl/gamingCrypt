from gamingcrypt.steam.webapi import StoreItem
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.steam_page import SteamLibraryPage
from gamingcrypt.ui.store_page import StorePage, price_text
from tests.fakes import FakeService

ITEMS = [
    StoreItem(620, "Portal 2", 195, "EUR", "", original_cents=975),       # owned + installed
    StoreItem(400, "Portal", 975, "EUR", ""),                             # owned, not installed
    StoreItem(570, "Dota 2", 0, "", ""),                                  # free
    StoreItem(1086940, "Baldur's Gate 3", 5999, "EUR", ""),               # not owned
]


def open_store(qtbot, service=None):
    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = service or FakeService(store_items=ITEMS)
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.open_steam()
    library = tab.currentWidget()
    qtbot.waitUntil(lambda: not library.loading)
    library.store_button.click()
    page = tab.currentWidget()
    assert isinstance(page, StorePage)
    return tab, page


def search(qtbot, page, term):
    page.search.setText(term)
    page.keyboard.submitted.emit()
    qtbot.waitUntil(lambda: not page.searching)


def test_price_text():
    assert price_text(ITEMS[0]) == "1.95 €  (-80%)"
    assert price_text(ITEMS[2]) == "Free"
    assert price_text(ITEMS[3]) == "59.99 €"


def test_search_shows_actions_per_ownership(qtbot):
    tab, page = open_store(qtbot)
    search(qtbot, page, "a")
    actions = {row.item.appid: (row.action, row.button.text()) for row in page.rows}
    assert actions[620][0] == "play"
    assert actions[400][0] == "install"
    assert actions[570][0] == "install"
    assert actions == {**actions, 1086940: ("buy", "Buy in Steam")}
    assert page.keyboard.isHidden()


def test_actions_call_steam_client(qtbot):
    tab, page = open_store(qtbot)
    search(qtbot, page, "a")
    for row in page.rows:
        row.button.click()
    assert tab.service.client.actions == [("play", 620), ("install", 400), ("install", 570), ("store", 1086940)]
    assert "store page" in page.status.text()


def test_new_search_replaces_results_and_empty_result(qtbot):
    tab, page = open_store(qtbot)
    search(qtbot, page, "portal")
    assert [r.item.appid for r in page.rows] == [620, 400]
    search(qtbot, page, "zzz")
    assert page.rows == [] and page.status.text() == "Nothing found"


def test_empty_query_does_nothing(qtbot):
    tab, page = open_store(qtbot)
    page.search.setText("   ")
    page.do_search()
    assert tab.service.store_queries == []


def test_store_unreachable(qtbot):
    service = FakeService()

    def boom(term):
        raise RuntimeError("offline")

    service.search_store = boom
    tab, page = open_store(qtbot, service)
    search(qtbot, page, "x")
    assert "not reachable" in page.status.text()


def test_owned_game_installs_without_steam_dialog(qtbot):
    from tests.fakes import SilentInstallService

    service = SilentInstallService(store_items=ITEMS)
    tab, page = open_store(qtbot, service)
    search(qtbot, page, "a")
    rows = {row.item.appid: row for row in page.rows}
    assert rows[400].action == "download"            # owned, not installed
    assert rows[570].action == "install"             # free, not owned yet -> Steam dialog
    assert rows[570].button.text() == "⬇  Install (Steam)"
    rows[400].button.click()
    assert "Preparing" in page.status.text()
    qtbot.waitUntil(lambda: "Download started" in page.status.text())
    assert service.installs == [400] and service.client.actions == []

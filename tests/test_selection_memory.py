import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.game_detail import GameDetailPage
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.navigator import GamepadNavigator
from gamingcrypt.ui.steam_page import SteamLibraryPage
from tests.fakes import FakeService


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


def press(nav, code):
    nav.on_event(e.EV_KEY, code, 1)
    nav.on_event(e.EV_KEY, code, 0)


def shown_tab(qtbot, games=None):
    tab = GamesTab(FakeService(games=games))
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitExposed(tab)
    qtbot.waitUntil(lambda: tab.home.result_appids != [])
    return tab


def test_steam_library_play_is_selected_and_back_returns_to_the_game(qtbot):
    SteamLibraryPage.FETCH_DELAY_MS = 0
    games = [SteamGame(i, f"Game {i:02}", installed=i % 2 == 0) for i in range(1, 30)]
    tab = shown_tab(qtbot, games)
    tab.open_steam()
    library = tab.currentWidget()
    qtbot.waitUntil(lambda: not library.loading)
    nav = GamepadNavigator(tab)
    card = library.cards[library.order[17]]  # somewhere down the list
    nav.focus(card)
    press(nav, e.BTN_SOUTH)  # A opens the game ...
    detail = tab.currentWidget()
    assert isinstance(detail, GameDetailPage)
    assert tab.focusWidget() is detail.main_button  # ... with Play / Download selected
    press(nav, e.BTN_EAST)  # B
    assert tab.currentWidget() is library
    assert tab.focusWidget() is card  # the same game again
    viewport = library.scroll.viewport()
    top = card.mapTo(viewport, card.rect().topLeft()).y()
    assert 0 <= top and top + card.height() <= viewport.height()  # and scrolled into view


def test_installed_list_keeps_the_selection_through_its_refresh(qtbot):
    tab = shown_tab(qtbot)
    nav = GamepadNavigator(tab)
    card = tab.home.cards[620]  # Portal 2
    nav.focus(card)
    press(nav, e.BTN_SOUTH)
    assert tab.focusWidget() is tab.currentWidget().main_button
    press(nav, e.BTN_EAST)
    assert tab.focusWidget() is card
    qtbot.wait(50)  # going back reloads the installed list (cards get re-added) ...
    tab.home.refresh_results()
    assert tab.focusWidget() is card  # ... the game stays selected


def test_recently_played_back_selects_the_game(qtbot):
    games = [SteamGame(i, f"G{i}", installed=True, last_played=1_700_000_000 + i) for i in range(1, 6)]
    tab = shown_tab(qtbot, games)
    tab.open_recent()
    recent = tab.currentWidget()
    qtbot.waitUntil(lambda: not recent.loading)
    nav = GamepadNavigator(tab)
    card = recent.cards[3]
    nav.focus(card)
    press(nav, e.BTN_SOUTH)
    assert tab.focusWidget() is tab.currentWidget().main_button
    press(nav, e.BTN_EAST)
    assert tab.focusWidget() is card


def test_touch_still_works_without_any_selection(qtbot):
    tab = shown_tab(qtbot)
    tab.open_game(620)
    tab.back()  # nothing was selected before (touch) - no crash, home is shown
    assert tab.currentWidget() is tab.home

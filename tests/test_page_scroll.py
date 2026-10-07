"""LT / RT: a screen up / down in long lists, in the same column."""

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.hint_bar import hints_for
from gamingcrypt.ui.navigator import GamepadNavigator
from tests.fakes import FakeService


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


@pytest.fixture
def tab(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab

    games = [SteamGame(i, f"Game {i:03}", installed=True) for i in range(1, 61)]
    t = GamesTab(FakeService(games=games))
    qtbot.addWidget(t)
    t.resize(1280, 800)
    t.show()
    qtbot.waitExposed(t)
    qtbot.waitUntil(lambda: len(t.home.result_appids) == 60)
    return t


def centre(w):
    return w.mapToGlobal(w.rect().center())


def test_triggers_page_through_the_grid(qtbot, tab):
    nav = GamepadNavigator(tab)
    first = tab.home.cards[tab.home.result_appids[1]]  # the second column
    nav.focus(first)
    assert "LT / RT  Page" in hints_for(first)
    start = centre(first)
    viewport = first.parentWidget()
    while viewport is not None and not hasattr(viewport, "verticalScrollBar"):
        viewport = viewport.parentWidget()
    height = viewport.viewport().height()
    nav.on_event(e.EV_KEY, e.BTN_TR2, 1)
    nav.on_event(e.EV_KEY, e.BTN_TR2, 0)
    down = nav.focused()
    assert down is not first and abs(centre(down).x() - start.x()) < 5  # same column
    assert height * 0.6 < centre(down).y() - start.y() <= height + 400  # about a screen further
    nav.on_event(e.EV_ABS, e.ABS_Z, 200)  # analog LT
    nav.on_event(e.EV_ABS, e.ABS_Z, 0)
    assert nav.focused() is first


def test_the_end_of_the_list_and_no_repeat_while_held(qtbot, tab):
    nav = GamepadNavigator(tab)
    last = tab.home.cards[tab.home.result_appids[-1]]
    nav.focus(tab.home.cards[tab.home.result_appids[0]])
    nav.on_event(e.EV_ABS, e.ABS_RZ, 255)
    nav.on_event(e.EV_ABS, e.ABS_RZ, 200)  # still held: one page only
    once = nav.focused()
    nav.on_event(e.EV_ABS, e.ABS_RZ, 0)
    for _ in range(20):
        nav.on_event(e.EV_KEY, e.BTN_TR2, 1)
        nav.on_event(e.EV_KEY, e.BTN_TR2, 0)
    assert once is not tab.home.cards[tab.home.result_appids[0]]
    assert centre(nav.focused()).y() == centre(last).y()  # the last row - and no further


def test_outside_lists_nothing_happens(qtbot, tab):
    nav = GamepadNavigator(tab)
    nav.focus(tab.home.search)
    nav.on_event(e.EV_KEY, e.BTN_TR2, 1)
    assert nav.focused() is tab.home.search
    assert "Page" not in hints_for(tab.home.search)

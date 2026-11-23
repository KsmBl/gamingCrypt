"""The triggers (LT / RT, a PS5 controller's L2 / R2 - analog and as buttons) move nothing in
GamingCrypt: they're for games, and tried out in Settings → Controller."""

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


def test_triggers_move_nothing(qtbot, tab):
    nav = GamepadNavigator(tab)
    first = tab.home.cards[tab.home.result_appids[1]]
    nav.focus(first)
    for ev_type, code, values in ((e.EV_KEY, e.BTN_TR2, (1, 0)), (e.EV_KEY, e.BTN_TL2, (1, 0)),
                                  (e.EV_ABS, e.ABS_RZ, (255, 128, 0)), (e.EV_ABS, e.ABS_Z, (255, 0))):
        for value in values:
            nav.on_event(ev_type, code, value)
        assert nav.focused() is first, code
    assert "LT" not in hints_for(first) and "Page" not in hints_for(first)
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 1)  # the rest still moves
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 0)
    assert nav.focused() is not first

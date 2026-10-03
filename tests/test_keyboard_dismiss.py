import pytest
from PySide6.QtCore import QPoint, Qt

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.navigator import GamepadNavigator
from tests.fakes import FakeService


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


def games(qtbot):
    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitExposed(tab)
    qtbot.waitUntil(lambda: tab.home.installed != [])
    home = tab.home
    qtbot.mouseClick(home.search, Qt.MouseButton.LeftButton)  # tap the search field
    assert home.keyboard.isVisible()
    return tab, home


def press(nav, code):
    nav.on_event(e.EV_KEY, code, 1)
    nav.on_event(e.EV_KEY, code, 0)


def test_tap_outside_closes_keyboard(qtbot):
    tab, home = games(qtbot)
    qtbot.mouseClick(home.search, Qt.MouseButton.LeftButton)  # tapping the field again keeps it
    assert home.keyboard.isVisible()
    key = home.keyboard._letter_buttons[10]  # "q" (first key of the second row)
    qtbot.mouseClick(key, Qt.MouseButton.LeftButton)  # typing keeps it open
    assert home.keyboard.isVisible() and home.search.text() == "q"
    home.search.clear()
    tapped = []
    home.steam_card.tapped.connect(lambda: tapped.append(1))
    qtbot.mouseClick(home.steam_card, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert home.keyboard.isHidden()
    assert tapped == [1]  # the tap still did its job


def test_b_closes_keyboard_wherever_the_highlight_is(qtbot):
    tab, home = games(qtbot)
    nav = GamepadNavigator(tab)
    home.search.setFocus()  # highlight on the field, not on the keyboard
    press(nav, e.BTN_EAST)
    assert home.keyboard.isHidden() and tab.focusWidget() is home.search


def test_moving_highlight_away_closes_keyboard(qtbot):
    tab, home = games(qtbot)
    nav = GamepadNavigator(tab)
    first_key = home.keyboard._letter_buttons[0]
    nav.focus(first_key)
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, 1)  # moving between keys keeps it
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, 0)
    assert home.keyboard.isVisible()
    nav.focus(home.steam_card)  # highlight leaves keyboard and field
    assert home.keyboard.isHidden()


def test_permanent_keyboards_stay(qtbot):
    from gamingcrypt.ui.lock_screen import LockScreen
    from tests.test_lock_screen import FakeUnlocker

    screen = LockScreen(FakeUnlocker(), "password")
    qtbot.addWidget(screen)
    screen.resize(1280, 800)
    screen.show()
    qtbot.waitExposed(screen)
    keyboard = screen.input.widget.keyboard
    qtbot.mouseClick(screen.input.widget.reveal, Qt.MouseButton.LeftButton)
    nav = GamepadNavigator(screen)
    press(nav, e.BTN_EAST)
    assert keyboard.isVisible()  # the lock screen's keyboard is the main input

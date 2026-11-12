"""Y on a page with a search field opens its keyboard (from any card on it); on a game's or movie's
own page Y still chooses another picture."""

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.cover_picker import CoverPicker
from gamingcrypt.ui.hint_bar import hints_for
from gamingcrypt.ui.navigator import GamepadNavigator
from gamingcrypt.ui.search_key import search_on_page
from gamingcrypt.ui.widgets import OnScreenKeyboard
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture
from tests.test_picture_shortcuts import games_tab, offline, press  # noqa: F401 - fixture

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


def keyboard_of(edit):
    return next((kb for kb in edit.window().findChildren(OnScreenKeyboard)
                 if kb.isVisible() and kb.target() is edit), None)


def test_y_on_a_card_in_the_games_searches(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    nav = GamepadNavigator(tab)
    card = tab.home.cards[5]
    nav.focus(card)
    assert "Ⓨ  Search" in hints_for(card) and "Picture" not in hints_for(card)
    press(nav, e.BTN_WEST)  # Y (xpad layout)
    keyboard = keyboard_of(tab.home.search)
    assert keyboard is not None and tab.currentWidget() is tab.home
    assert keyboard.isAncestorOf(tab.window().focusWidget())  # (on its keys: typed right away)


def test_y_on_a_games_page_still_picks_a_picture(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    nav = GamepadNavigator(tab)
    tab.open_game(5)
    page = tab.currentWidget()
    nav.focus(page.main_button)
    assert search_on_page(page.main_button) is None
    assert "Ⓨ  Picture" in hints_for(page.main_button)
    press(nav, e.BTN_WEST)
    assert isinstance(tab.currentWidget(), CoverPicker)


def test_the_search_field_itself_says_keyboard_once(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    assert "Ⓨ" not in hints_for(tab.home.search)  # (Ⓐ  Keyboard is there already)


def test_y_twice_keeps_the_keyboard(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    nav = GamepadNavigator(tab)
    nav.focus(tab.home.cards[5])
    press(nav, e.BTN_WEST)
    keyboard = keyboard_of(tab.home.search)
    press(nav, e.BTN_WEST)  # (on its keys now)
    assert keyboard.isVisible() and keyboard_of(tab.home.search) is keyboard


def test_y_on_a_movie_card_searches(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    nav = GamepadNavigator(tab)
    card = next(iter(tab.home.cards.values()))
    nav.focus(card)
    assert "Ⓨ  Search" in hints_for(card)
    press(nav, e.BTN_WEST)
    assert keyboard_of(tab.home.search) is not None


def test_a_hidden_search_isnt_used(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    tab.home.search.hide()
    card = tab.home.cards[5]
    assert search_on_page(card) is None and "Ⓨ  Picture" in hints_for(card)


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_keyboard_fits(qtbot, tmp_path, w, h):
    from tests.test_code_dialogs import rect_in

    tab = games_tab(qtbot, tmp_path)
    tab.resize(w, h)
    qtbot.wait(20)
    nav = GamepadNavigator(tab)
    nav.focus(tab.home.cards[5])
    press(nav, e.BTN_WEST)
    keyboard = keyboard_of(tab.home.search)
    qtbot.wait(20)
    assert tab.rect().contains(rect_in(keyboard, tab)), f"the keyboard is off the {w}x{h} screen"

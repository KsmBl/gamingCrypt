"""The hint bar says "Ⓑ  Back" only where B goes back: not on the first page of a tab."""

import pytest

from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.hint_bar import can_go_back, hints_for
from gamingcrypt.ui.shell import Shell
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture
from tests.test_picture_shortcuts import games_tab, offline  # noqa: F401 - fixture
from tests.test_search_key import keyboard_of

BACK = "Ⓑ  Back"


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


def in_shell(qtbot, **pages):
    shell = Shell(pages)
    qtbot.addWidget(shell)
    shell.resize(1280, 800)
    shell.show()
    return shell


def test_games_first_page_and_a_games_page(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    in_shell(qtbot, Games=tab)
    card = tab.home.cards[5]
    assert BACK not in hints_for(card) and hints_for(card).startswith("Ⓐ  Open game     Ⓧ  Favorite     Ⓨ")
    assert BACK not in hints_for(tab.home.search)
    tab.open_game(5)
    assert BACK in hints_for(tab.currentWidget().main_button)
    tab.back()
    assert BACK not in hints_for(card)


def test_b_really_does_nothing_there(qtbot, tmp_path):
    from gamingcrypt.ui.navigator import GamepadNavigator

    tab = games_tab(qtbot, tmp_path)
    shell = in_shell(qtbot, Games=tab)
    nav = GamepadNavigator(shell)
    nav.focus(tab.home.cards[5])
    assert not nav._back()  # (what the hint now says)


def test_the_keyboard_of_a_first_page_search_says_back(qtbot, tmp_path):
    """B closes it there."""
    from gamingcrypt.input import evdev as e
    from gamingcrypt.ui.navigator import GamepadNavigator
    from tests.test_picture_shortcuts import press

    tab = games_tab(qtbot, tmp_path)
    shell = in_shell(qtbot, Games=tab)
    nav = GamepadNavigator(shell)
    nav.focus(tab.home.cards[5])
    press(nav, e.BTN_WEST)  # Y: the search keyboard
    key = shell.window().focusWidget()
    assert keyboard_of(tab.home.search).isAncestorOf(key) and BACK in hints_for(key)


def test_movies_first_page_and_a_movie(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    in_shell(qtbot, Movies=tab)
    card = next(iter(tab.home.cards.values()))
    assert BACK not in hints_for(card)
    tab.open_movie(card.movie)
    assert BACK in hints_for(tab.currentWidget().main_button)


def test_settings_overview_and_a_page_in_it(qtbot):
    from tests.test_rating_overview import config
    from gamingcrypt.system.controls import SystemControls
    from gamingcrypt.ui.settings_tab import SettingsTab
    from tests.test_users import verify

    tab = SettingsTab(config(), lambda c: None, system=SystemControls(), admin_check=verify)
    in_shell(qtbot, Settings=tab)
    tab.show_sub_tab("Security")
    add = tab.users_section.add_button
    assert not can_go_back(add) and BACK not in hints_for(add)
    add.click()  # the name of the new user: a page of its own
    assert can_go_back(tab.currentWidget().edit)


def test_a_tab_without_pages(qtbot):
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    music = QWidget()
    button = QPushButton("Play", music)
    QVBoxLayout(music).addWidget(button)
    in_shell(qtbot, Music=music)
    assert not can_go_back(button)


def test_outside_the_tabs_back_stays(qtbot):
    from PySide6.QtWidgets import QPushButton

    button = QPushButton("OK")
    qtbot.addWidget(button)
    assert can_go_back(button) and BACK in hints_for(button)
    assert can_go_back(None)

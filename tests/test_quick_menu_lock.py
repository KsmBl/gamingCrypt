"""The quick menu's "Lock now" closes the running game: asked first. The device's lock buttons stay
instant (test_panic_lock), and with no game (or a movie, whose place is kept) nothing is asked."""

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.ui.modal import open_modal
from tests.test_code_dialogs import rect_in
from tests.test_panic_lock import Unlocker, window  # noqa: F401 - fixture
from tests.test_quick_menu import menu  # noqa: F401 - fixture

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def locked(m):
    got = []
    m.lock_now.connect(lambda: got.append(1))
    return got


def test_no_game_no_question(qtbot, menu):  # noqa: F811
    m, *_ = menu
    got = locked(m)
    m.open_menu(None)
    m.lock_button.click()
    assert got == [1] and open_modal(m, on_screen=False) is None and not m.isVisible()


def test_a_movie_keeps_its_place_no_question(qtbot, menu):  # noqa: F811
    from gamingcrypt.movies.library import MOVIE_APPID_BASE

    m, *_ = menu
    got = locked(m)
    m.open_menu(MOVIE_APPID_BASE + 5, "The Matrix")
    m.lock_button.click()
    assert got == [1]


def test_a_game_asks(qtbot, menu):  # noqa: F811
    m, *_ = menu
    got = locked(m)
    m.open_menu(620, "Portal 2")
    m.lock_button.click()
    question = open_modal(m, on_screen=False)
    assert got == [] and m.isVisible()
    text = question.content.question.text()
    assert "Lock now?" in text and "Portal 2 is closed" in text and "wasn't saved" in text
    question.content.cancel_button.click()
    assert got == [] and m.isVisible() and open_modal(m, on_screen=False) is None
    m.lock_button.click()
    open_modal(m, on_screen=False).content.action_button.click()
    assert got == [1] and not m.isVisible()


def test_an_emulated_game_says_save_states(qtbot, menu):  # noqa: F811
    m, *_ = menu
    m.open_menu(620, "Super Mario World")
    m.set_emulated(True, 1.0, states=True)
    m.lock_button.click()
    assert "since your last save state" in open_modal(m, on_screen=False).content.question.text()
    open_modal(m, on_screen=False).content.cancel_button.click()
    m.set_emulated(True, 1.0, states=False)  # (a Wii U game: no states)
    m.lock_button.click()
    assert "wasn't saved" in open_modal(m, on_screen=False).content.question.text()


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_question_fits(qtbot, menu, w, h):  # noqa: F811
    m, *_ = menu
    m._test_host.resize(w, h)
    m.open_menu(620, "Ori and the Blind Forest: Definitive Edition")
    m.lock_button.click()
    box = open_modal(m, on_screen=False).content
    qtbot.waitUntil(box.isVisible)
    host = m._test_host
    for part in (box.question, box.cancel_button, box.action_button):
        assert host.rect().contains(rect_in(part, host)), f"{part} is off the {w}x{h} screen"


def test_in_the_window_the_drive_is_locked_after_yes_only(qtbot, window):  # noqa: F811
    window.toggle_quick_menu()
    window.quick_menu.open_menu(620, "Portal 2")
    window.quick_menu.lock_button.click()
    qtbot.wait(50)
    assert window.screen_name == "shell" and Unlocker.dismounted == []
    open_modal(window, on_screen=False).content.action_button.click()
    qtbot.waitUntil(lambda: Unlocker.dismounted == [1])
    assert window.screen_name == "lock"


def test_the_lock_buttons_stay_instant_mid_game(qtbot, window):  # noqa: F811
    window.toggle_quick_menu()
    window.quick_menu.open_menu(620, "Portal 2")
    window.hardware_key(e.PANIC_COMBO)
    qtbot.waitUntil(lambda: Unlocker.dismounted == [1])

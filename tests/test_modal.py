"""Every confirmation the same way: a box over the dimmed page, Cancel selected first."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from gamingcrypt.ui.modal import ConfirmBox, ask, open_modal
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture


def host(qtbot):
    page = QWidget()
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.show()
    qtbot.waitExposed(page)
    return page


def test_yes_no_and_a_tap_beside(qtbot):
    page = host(qtbot)
    said = []
    modal = ask(page, "Delete it?", "🗑  Delete", lambda: said.append("yes"))
    assert open_modal(page) is modal and modal.geometry() == page.rect()
    box = modal.content
    assert isinstance(box, ConfirmBox) and box.question.text() == "Delete it?"
    assert page.focusWidget() is box.cancel_button  # the safe choice first
    QTest.mouseClick(modal, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))  # beside it: no
    assert open_modal(page) is None and said == []
    ask(page, "Delete it?", "🗑  Delete", lambda: said.append("yes")).content.gamepad_back()  # B: no
    assert open_modal(page) is None and said == []
    ask(page, "Delete it?", "🗑  Delete", lambda: said.append("yes")).content.action_button.click()
    assert open_modal(page) is None and said == ["yes"]


def test_it_follows_the_page_size(qtbot):
    page = host(qtbot)
    modal = ask(page, "Sure?", "Yes", lambda: None)
    page.resize(800, 500)
    assert modal.geometry() == page.rect()


def test_removing_a_movie_asks_over_the_page(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    movie = next(m for m in tab.movies if m.title == "Alien")
    tab.open_movie(movie)
    page = tab.currentWidget()
    page.options_button.click()
    page.remove_button.click()
    modal = open_modal(page)
    assert modal is not None and "Really remove Alien?" in modal.content.question.text()
    assert page.remove_button.isVisibleTo(page.options_popup)  # (not swapped out of the options anymore)
    modal.content.cancel_button.click()
    assert open_modal(page) is None and movie.path.exists()


def test_dpad_in_the_force_quit_question_over_the_quick_menu(qtbot, monkeypatch):
    """In a game: the quick menu's own grid must not take the D-pad from the question on it."""
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.input import evdev as e
    from gamingcrypt.ui import navigator as nav_mod
    from gamingcrypt.ui.navigator import GamepadNavigator

    nav_mod.set_paused(False)
    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.resize(1280, 800)
    w.show()
    w.show_shell()
    w.game_watcher.appid, w.game_watcher.phase = 620, "playing"
    w.toggle_quick_menu()
    menu = w.quick_menu
    nav = GamepadNavigator(w)
    menu.quit_button.click()
    question = open_modal(w)
    box = question.content
    assert w.focusWidget() is box.cancel_button
    for code in (e.ABS_HAT0X,):
        nav.on_event(e.EV_ABS, code, 1)  # right
        nav.on_event(e.EV_ABS, code, 0)
    assert w.focusWidget() is box.action_button  # moved inside the question, not into the menu below
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, -1)  # left
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, 0)
    assert w.focusWidget() is box.cancel_button
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 1)  # down: nothing there - stays in it
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 0)
    assert question.isAncestorOf(w.focusWidget())
    quit_ = []
    menu.force_quit.connect(quit_.append)
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, 1)
    nav.on_event(e.EV_ABS, e.ABS_HAT0X, 0)
    nav.on_event(e.EV_KEY, e.BTN_SOUTH, 1)  # A on "Force quit"
    nav.on_event(e.EV_KEY, e.BTN_SOUTH, 0)
    assert quit_ == [620]
    w.game_watcher._stop()

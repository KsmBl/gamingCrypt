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

"""Drop-down lists open inside GamingCrypt's window, over everything in it - never as a window
of their own the compositor (gamescope) could put behind GamingCrypt's."""

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui.combo import ComboBox, ComboList, open_list
from gamingcrypt.ui.navigator import GamepadNavigator
from tests.test_navigation import dpad, press


@pytest.fixture
def window(qtbot):
    w = QWidget()
    w.resize(800, 600)
    layout = QVBoxLayout(w)
    combo = ComboBox()
    combo.addItems(["Automatic (Cemu)", "Cemu", "Other"])
    layout.addWidget(combo)
    layout.addStretch()
    below = QPushButton("further down")
    clicks = []
    below.clicked.connect(lambda: clicks.append(1))
    layout.addWidget(below)
    cover = QLabel("an overlay over the page (like Options)", w)  # raised over the drop-down
    cover.setGeometry(0, 0, 800, 600)
    cover.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    cover.raise_()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w._combo, w._below, w._clicks, w._cover = combo, below, clicks, cover
    yield w
    combo.hidePopup()


def tap(qtbot, widget: QWidget, at: QPoint | None = None) -> None:
    qtbot.mouseClick(widget, Qt.MouseButton.LeftButton, pos=at or widget.rect().center())


def test_the_list_is_part_of_the_window_and_on_top(qtbot, window):
    combo = window._combo
    combo.showPopup()
    listing = open_list()
    assert isinstance(listing, ComboList) and listing.isVisible() and combo.list_open()
    assert not listing.isWindow() and listing.parentWidget() is window
    assert QApplication.activePopupWidget() is None
    siblings = [c for c in window.children() if isinstance(c, QWidget)]
    assert siblings[-1] is listing  # over everything in the window - the overlay too
    assert listing.geometry().top() == combo.geometry().bottom() + 1  # right under the drop-down
    assert listing.height() >= 3 * listing.sizeHintForRow(0)  # every row
    assert QApplication.focusWidget() is listing and listing.currentIndex().row() == 0


def test_a_tapped_row_is_chosen(qtbot, window):
    combo = window._combo
    activated = []
    combo.activated.connect(activated.append)
    combo.showPopup()
    listing = open_list()
    tap(qtbot, listing.viewport(), listing.visualRect(listing.model().index(1, 0)).center())
    assert combo.currentIndex() == 1 and activated == [1]
    assert not listing.isVisible() and open_list() is None and QApplication.focusWidget() is combo


def test_a_tap_beside_it_closes_it_and_does_nothing_else(qtbot, window):
    combo = window._combo
    combo.showPopup()
    listing = open_list()
    assert not listing.geometry().intersects(window._below.geometry())
    tap(qtbot, window._below)
    assert not listing.isVisible() and combo.currentIndex() == 0
    assert window._clicks == []  # the tap only closed it
    combo.showPopup()
    tap(qtbot, combo)  # the drop-down itself: closed again
    assert not combo.list_open()


def test_keys_and_the_controller(qtbot, window):
    combo = window._combo
    combo.setFocus()
    nav = GamepadNavigator(window)
    press(nav, e.BTN_SOUTH)  # A opens it
    assert combo.list_open()
    dpad(nav, dy=1)
    dpad(nav, dy=1)
    press(nav, e.BTN_SOUTH)  # A picks
    assert combo.currentIndex() == 2 and not combo.list_open()
    press(nav, e.BTN_SOUTH)
    dpad(nav, dy=-1)
    press(nav, e.BTN_EAST)  # B: closed, nothing changed
    assert combo.currentIndex() == 2 and not combo.list_open() and QApplication.focusWidget() is combo


def test_room_above_when_there_is_none_below(qtbot):
    w = QWidget()
    w.resize(600, 400)
    combo = ComboBox(w)
    combo.addItems([f"Item {i}" for i in range(30)])
    combo.setGeometry(20, 340, 300, 50)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    combo.showPopup()
    listing = open_list()
    try:
        r = listing.geometry()
        assert r.bottom() < combo.geometry().top() and r.top() >= 0  # over it, inside the window
        assert r.height() <= 340 and r.width() >= combo.width()
    finally:
        combo.hidePopup()


def test_it_closes_with_its_drop_down(qtbot, window):
    combo = window._combo
    combo.showPopup()
    combo.hide()
    assert open_list() is None
    combo.show()
    combo.showPopup()
    window.resize(700, 500)  # (the window changed: where it was is gone)
    assert open_list() is None

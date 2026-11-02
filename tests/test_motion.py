"""Pages that move - only a picture does: the new page is there at once, and can be used."""

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui import motion
from gamingcrypt.ui.game_widgets import Cover, Tappable


@pytest.fixture
def moving():
    config = {"appearance": {}}
    motion.configure(config)
    yield config
    motion.configure(None)


def running(host):
    return [t for t in host.findChildren(motion.Transition) if not t.isHidden()]


@pytest.fixture
def host(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(640, 400)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_nothing_moves_unless_set_up_or_on_screen(qtbot, host):
    assert motion.before(host) is None and not motion.switched_off()  # not set up
    motion.configure({"appearance": {"motion": False}})
    try:
        assert motion.before(host) is None and motion.switched_off()
    finally:
        motion.configure(None)
    motion.slide(host, None, 1)
    assert running(host) == []


def test_not_on_screen_means_no_picture(qtbot, moving):
    hidden = QWidget()
    qtbot.addWidget(hidden)
    assert motion.before(hidden) is None


def test_a_transition_lets_everything_through_and_goes_away(qtbot, moving, host):
    old = motion.before(host)
    assert old.size() == host.size()
    motion.slide(host, old, 1)
    transition = running(host)[0]
    assert transition.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert transition.focusPolicy() == Qt.FocusPolicy.NoFocus and transition.geometry() == host.rect()
    qtbot.waitUntil(lambda: running(host) == [], timeout=2000)


def test_only_one_at_a_time(qtbot, moving, host):
    motion.slide(host, motion.before(host), 1)
    first = running(host)[0]
    motion.slide(host, motion.before(host), -1)  # (the first would be in the picture)
    assert running(host) != [first] and len(running(host)) == 1


def test_a_cover_flies_from_its_card_to_its_place(qtbot, moving, host):
    target = QLabel(host)
    target.setGeometry(300, 40, 200, 300)
    picture = QPixmap(100, 150)
    picture.fill(Qt.GlobalColor.red)
    motion.fly(host, motion.before(host), picture, QRect(10, 20, 100, 150), target)
    transition = running(host)[0]
    transition.animation.stop()
    transition.progress = 0.0
    assert transition.flight_rect().toRect() == QRect(10, 20, 100, 150)
    transition.progress = 0.5
    assert transition.flight_rect().toRect() == QRect(155, 30, 150, 225)
    transition.progress = 1.0
    assert transition.flight_rect().toRect() == target.geometry()
    transition.repaint()  # (paints at every stage)
    target.deleteLater()
    qtbot.waitUntil(lambda: not __import__("shiboken6").isValid(target))
    assert transition.flight_rect() is None
    transition.repaint()


def tab_with_card(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.resize(1000, 700)
    tab.show()
    qtbot.waitExposed(tab)
    card = Tappable(tab.home)
    card.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    card.cover = Cover(card)
    picture = QPixmap(60, 90)
    picture.fill(Qt.GlobalColor.blue)
    card.cover.setPixmap(picture)
    card.show()
    return tab, card


def game_page():
    page = QWidget()
    page.cover = Cover(page)
    page.cover.setFixedSize(300, 450)
    QVBoxLayout(page).addWidget(page.cover)
    return page


def test_opening_a_game_from_its_card_flies_and_the_page_is_there_at_once(qtbot, moving):
    tab, card = tab_with_card(qtbot)
    card.setFocus()
    page = game_page()
    tab.push(page)
    assert tab.currentWidget() is page  # not after the movement
    transition = running(tab)[0]
    assert transition.flight[2] is page.cover and transition.direction == 0
    qtbot.waitUntil(lambda: running(tab) == [], timeout=2000)


def test_going_back_slides_the_other_way(qtbot, moving):
    tab, _card = tab_with_card(qtbot)
    tab.push(QWidget())
    assert running(tab)[0].flight is None and running(tab)[0].direction == 1  # nothing to fly
    qtbot.waitUntil(lambda: running(tab) == [], timeout=2000)
    tab.back()
    assert tab.currentWidget() is tab.home and running(tab)[0].direction == -1


def test_switched_off_the_page_just_changes(qtbot, moving):
    moving["appearance"]["motion"] = False
    tab, card = tab_with_card(qtbot)
    card.setFocus()
    page = game_page()
    tab.push(page)
    assert tab.currentWidget() is page and running(tab) == []


def test_tabs_slide_towards_where_they_are(qtbot, moving):
    from gamingcrypt.ui.shell import Shell

    shell = Shell()
    qtbot.addWidget(shell)
    shell.resize(800, 500)
    shell.show()
    qtbot.waitExposed(shell)
    shell.show_tab("Movies")
    assert shell.current_tab == "Movies" and running(shell.stack)[0].direction == 1
    shell.show_tab("Games")
    assert shell.stack.currentWidget() is shell.pages["Games"] and running(shell.stack)[0].direction == -1
    qtbot.waitUntil(lambda: running(shell.stack) == [], timeout=2000)
    shell.show_tab("Games")  # already there
    assert running(shell.stack) == []


def test_starting_screen_fades_in_once_and_shows_the_game(qtbot, moving, host):
    from gamingcrypt.ui.launch_overlay import LaunchOverlay

    overlay = LaunchOverlay(host)
    overlay.show_for("Hollow Peaks")
    assert overlay.isVisible() and len(running(host)) == 1
    assert not overlay.backdrop.render().toImage().isNull()
    qtbot.waitUntil(lambda: running(host) == [], timeout=2000)
    overlay.show_for("Hollow Peaks")  # told again while it's up: no second fade
    assert running(host) == []


def test_the_controller_highlight_ignores_a_transition(qtbot, moving, host):
    from PySide6.QtWidgets import QPushButton

    from gamingcrypt.ui.navigator import GamepadNavigator

    layout = QVBoxLayout(host)
    first, second = QPushButton("1"), QPushButton("2")
    layout.addWidget(first)
    layout.addWidget(second)
    qtbot.wait(20)
    first.setFocus()
    motion.slide(host, motion.before(host), 1)
    nav = GamepadNavigator(host)
    assert running(host)[0] not in nav.candidates()
    nav.move(0, 1)
    assert host.focusWidget() is second


def test_settings_switch_the_animations(qtbot):
    from gamingcrypt.ui.system_settings import AppearanceSection

    config = {"appearance": {}}
    section = AppearanceSection(config, lambda c: None)
    qtbot.addWidget(section)
    section.switches["motion"][False].click()
    assert config["appearance"]["motion"] is False


def test_stacked_host_keeps_only_its_pages(qtbot, moving):
    stack = QStackedWidget()
    qtbot.addWidget(stack)
    stack.addWidget(QWidget())
    stack.resize(300, 200)
    stack.show()
    qtbot.waitExposed(stack)
    motion.slide(stack, motion.before(stack), 1)
    assert stack.count() == 1

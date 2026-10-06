import pytest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.navigator import GamepadNavigator
from gamingcrypt.ui.widgets import FlowLayout, FoldingHeader, big_button


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(nav_mod, "SCROLL_MS", 20)
    monkeypatch.setattr(FoldingHeader, "DURATION_MS", 10)
    monkeypatch.setattr(FoldingHeader, "SETTLE_MS", 0)
    nav_mod.set_paused(False)
    FoldingHeader.programmatic = False
    yield
    FoldingHeader.programmatic = False


def test_flow_layout_caches_height(qtbot, monkeypatch):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host)
    for i in range(30):
        b = QLabel(str(i))
        b.setFixedSize(100, 100)
        flow.addWidget(b)
    calls = []
    original = flow._do_layout
    monkeypatch.setattr(flow, "_do_layout", lambda rect, apply: calls.append(apply) or original(rect, apply))
    h = flow.heightForWidth(500)
    for _ in range(50):
        assert flow.heightForWidth(500) == h
    assert calls == [False]  # computed once, not on every resize / animation frame
    for _ in range(3):  # 30 cards = 8 rows of 4 (last one half full) -> 33 = 9 rows
        extra = QLabel("x")
        extra.setFixedSize(100, 100)
        flow.addWidget(extra)
    assert flow.heightForWidth(500) > h  # cache invalidated when cards change
    flow.take_all()
    assert flow.heightForWidth(500) < 100  # only the margins are left


def grid_page(qtbot, rows=30):
    root = QWidget()
    layout = QVBoxLayout(root)
    header = QLabel("Header")
    header.setFixedHeight(80)
    layout.addWidget(header)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    box = QVBoxLayout(content)
    buttons = []
    for i in range(rows):
        b = big_button(f"Game {i}")
        b.setFixedHeight(90)
        box.addWidget(b)
        buttons.append(b)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    qtbot.addWidget(root)
    root.resize(500, 600)
    root.show()
    qtbot.waitExposed(root)
    fold = FoldingHeader(scroll, header)
    return root, header, scroll, buttons, fold


def step(nav, dy):
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, dy)
    nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 0)


def test_navigation_glides_and_keeps_header_folded_until_the_top(qtbot):
    root, header, scroll, buttons, fold = grid_page(qtbot)
    nav = GamepadNavigator(root)
    bar = scroll.verticalScrollBar()
    buttons[0].setFocus()
    for _ in range(15):
        step(nav, 1)
    qtbot.waitUntil(lambda: not FoldingHeader.programmatic)
    focused = root.focusWidget()
    assert focused is buttons[15]
    # the focused item is fully visible after the glide
    top = focused.mapTo(scroll.widget(), focused.rect().topLeft()).y()
    assert bar.value() <= top and top + focused.height() <= bar.value() + scroll.viewport().height()
    qtbot.waitUntil(header.isHidden)
    for _ in range(8):  # stepping back up through the list ...
        step(nav, -1)
        qtbot.wait(5)
        assert fold.folded  # ... doesn't unfold (and re-layout) on every step
    for _ in range(10):
        step(nav, -1)
    qtbot.waitUntil(lambda: bar.value() == 0 and not FoldingHeader.programmatic)
    assert not fold.folded  # at the top it comes back


def test_touch_scrolling_up_still_unfolds(qtbot):
    root, header, scroll, buttons, fold = grid_page(qtbot)
    bar = scroll.verticalScrollBar()
    bar.setValue(900)
    assert fold.folded
    bar.setValue(850)
    assert not fold.folded


def test_focused_play_button_is_clearly_highlighted(qtbot):
    """Focus on a blue primary button: a ring in the text colour + brighter fill (not blue on blue);
    on any other button the accent ring - in both themes."""
    from gamingcrypt.ui import theme

    for name in theme.THEMES:
        theme.apply(name)
        css = theme.STYLESHEET
        assert (f"QPushButton#primary:focus {{ background: {theme.ACCENT_HI}; border-color: {theme.FOCUS}; }}"
                in css)
        assert f"QPushButton:focus {{ border-color: {theme.ACCENT}; }}" in css
        assert theme.FOCUS != theme.ACCENT_HI
    theme.apply(theme.DEFAULT)


def test_up_in_the_game_grid_goes_to_the_game_above_not_the_tabs(qtbot):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.steam_page import SteamLibraryPage
    from tests.fakes import FakeService

    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = FakeService(games=[SteamGame(i, f"Game {i:03}") for i in range(1, 41)])
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(service)})
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    window.show_shell()
    qtbot.waitExposed(window)
    games = window.shell.pages["Games"]
    games.open_steam()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    nav = GamepadNavigator(window)
    cards = [page.cards[a] for a in page.order]
    per_row = sum(1 for c in cards if c.y() == cards[0].y())
    start = cards[1]  # second column, first row
    nav.focus(start)
    for _ in range(4):
        step(nav, 1)
        qtbot.waitUntil(lambda: not FoldingHeader.programmatic)
    focused = window.focusWidget()
    assert focused is cards[1 + 4 * per_row]
    tabs = set(window.shell.tab_buttons.values())
    for row in range(3, -1, -1):  # back up, one game at a time
        step(nav, -1)
        qtbot.waitUntil(lambda: not FoldingHeader.programmatic)
        assert window.focusWidget() is cards[1 + row * per_row]
        assert window.focusWidget() not in tabs
    step(nav, -1)  # from the top row it may leave the grid
    qtbot.waitUntil(lambda: not FoldingHeader.programmatic)
    assert window.focusWidget() not in cards


def test_closing_a_page_while_it_glides_does_not_leave_the_controller_scrolling(qtbot):
    from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

    from gamingcrypt.ui.navigator import GamepadNavigator
    from gamingcrypt.ui.widgets import FoldingHeader

    window = QWidget()
    qtbot.addWidget(window)
    area = QScrollArea(window)
    content = QWidget()
    QVBoxLayout(content).addWidget(QWidget())
    content.setMinimumHeight(3000)
    area.setWidget(content)
    window.resize(400, 400)
    window.show()
    nav = GamepadNavigator(window)
    nav._glide(area.verticalScrollBar(), 1000)
    assert FoldingHeader.programmatic
    area.deleteLater()  # the page goes away mid-glide
    qtbot.waitUntil(lambda: not FoldingHeader.programmatic, timeout=2000)

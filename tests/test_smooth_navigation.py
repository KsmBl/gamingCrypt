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
    """Focus on a blue primary button: thick white ring + brighter fill (was blue on blue)."""
    from gamingcrypt.ui import theme

    css = theme.STYLESHEET
    assert f"QPushButton#primary:focus {{ background: {theme.ACCENT_HI}; border: 4px solid {theme.TEXT}; }}" in css
    assert f"QPushButton:focus {{ border: 4px solid {theme.TEXT}; }}" in css

import os
import time

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QGridLayout, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.navigator import GamepadNavigator
from gamingcrypt.ui.widgets import big_button


@pytest.fixture(autouse=True)
def fast_repeat(monkeypatch):
    monkeypatch.setattr(nav_mod, "REPEAT_DELAY_MS", 20)
    monkeypatch.setattr(nav_mod, "REPEAT_RATE_MS", 20)
    nav_mod.set_paused(False)
    yield
    nav_mod.set_paused(False)


def press(nav, code):
    nav.on_event(e.EV_KEY, code, 1)
    nav.on_event(e.EV_KEY, code, 0)


def dpad(nav, dx=0, dy=0):
    if dx:
        nav.on_event(e.EV_ABS, e.ABS_HAT0X, dx)
        nav.on_event(e.EV_ABS, e.ABS_HAT0X, 0)
    if dy:
        nav.on_event(e.EV_ABS, e.ABS_HAT0Y, dy)
        nav.on_event(e.EV_ABS, e.ABS_HAT0Y, 0)


def grid_window(qtbot):
    window = QWidget()
    layout = QGridLayout(window)
    buttons = {}
    clicks = []
    for row in range(3):
        for col in range(3):
            b = big_button(f"{row}{col}")
            b.clicked.connect(lambda _=False, n=f"{row}{col}": clicks.append(n))
            layout.addWidget(b, row, col)
            buttons[(row, col)] = b
    qtbot.addWidget(window)
    window.resize(600, 400)
    window.show()
    qtbot.waitExposed(window)
    return window, buttons, clicks


def focused():
    widget = QApplication.focusWidget()
    if widget is None:
        from PySide6.QtCore import Qt

        for top in QApplication.topLevelWidgets():
            if top.windowType() == Qt.WindowType.Popup:
                continue  # e.g. a dropdown list left over from another test
            if top.isVisible() and top.focusWidget() is not None:
                return top.focusWidget()
    return widget


def test_spatial_moves_and_select(qtbot):
    window, b, clicks = grid_window(qtbot)
    nav = GamepadNavigator(window)
    dpad(nav, dy=1)  # nothing focused yet -> top-left
    assert focused() is b[(0, 0)]
    dpad(nav, dx=1)
    dpad(nav, dy=1)
    assert focused() is b[(1, 1)]
    dpad(nav, dx=1)
    dpad(nav, dx=1)  # edge: stays
    assert focused() is b[(1, 2)]
    press(nav, e.BTN_SOUTH)
    assert clicks == ["12"]


def test_stick_with_threshold_and_repeat(qtbot):
    window, b, clicks = grid_window(qtbot)
    nav = GamepadNavigator(window)
    b[(0, 0)].setFocus()
    nav.on_event(e.EV_ABS, e.ABS_X, 8000)  # small tilt: nothing
    assert focused() is b[(0, 0)]
    nav.on_event(e.EV_ABS, e.ABS_X, 30000)
    assert focused() is b[(0, 1)]
    qtbot.waitUntil(lambda: focused() is b[(0, 2)])  # held -> repeats
    nav.on_event(e.EV_ABS, e.ABS_X, 0)
    assert nav.held is None and not nav.repeat.isActive()


def test_paused_and_hidden_window_ignore_input(qtbot):
    window, b, clicks = grid_window(qtbot)
    nav = GamepadNavigator(window)
    b[(0, 0)].setFocus()
    nav_mod.set_paused(True)
    press(nav, e.BTN_SOUTH)
    nav_mod.set_paused(False)
    window.hide()
    press(nav, e.BTN_SOUTH)
    assert clicks == []


def test_slider_and_combobox(qtbot):
    window = QWidget()
    layout = QVBoxLayout(window)
    slider = QSlider()
    slider.setOrientation(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    combo = QComboBox()
    combo.addItems(["one", "two", "three"])
    layout.addWidget(slider)
    layout.addWidget(combo)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    nav = GamepadNavigator(window)
    slider.setFocus()
    dpad(nav, dx=1)
    assert slider.value() == 55  # left/right change the value
    dpad(nav, dy=1)
    assert focused() is combo
    press(nav, e.BTN_SOUTH)
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is not None)
    dpad(nav, dy=1)
    press(nav, e.BTN_SOUTH)
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is None)
    assert combo.currentText() == "two"


def test_search_field_keyboard_and_back(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitExposed(tab)
    nav = GamepadNavigator(tab)
    tab.home.search.setFocus()
    press(nav, e.BTN_SOUTH)  # A on the search field opens the keyboard on its first key
    assert tab.home.keyboard.isVisible()
    assert tab.focusWidget().text() == "1"
    dpad(nav, dy=1)  # onto the q row
    press(nav, e.BTN_SOUTH)
    assert tab.home.search.text() == "q"
    press(nav, e.BTN_EAST)  # B: back to the field, pop-up keyboard closes
    assert tab.focusWidget() is tab.home.search and tab.home.keyboard.isHidden()


def test_back_in_games_and_tab_switching(qtbot):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(FakeService())})
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    window.show_shell()
    qtbot.waitExposed(window)
    nav = GamepadNavigator(window, tab_switch=window.switch_tab)
    games = window.shell.pages["Games"]
    qtbot.waitUntil(lambda: games.home.installed != [])
    games.open_game(620)
    games.currentWidget().main_button.setFocus()
    press(nav, e.BTN_EAST)
    assert games.currentWidget() is games.home
    press(nav, e.BTN_TR)
    assert window.shell.current_tab == "Downloads"
    press(nav, e.BTN_TL)
    press(nav, e.BTN_TL)
    assert window.shell.current_tab == "Settings"  # wraps around


def test_loading_screen_keeps_focus_inside(qtbot):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    window.show_shell()
    qtbot.waitExposed(window)
    window.game_watcher.processes = lambda appid: set()
    window.game_launched(1)
    nav = GamepadNavigator(window)
    assert nav.root() is window.launch_overlay
    dpad(nav, dy=1)
    assert focused() is window.launch_overlay.back_button
    press(nav, e.BTN_EAST)  # B = back to GamingCrypt
    assert not window.launch_overlay.isVisible()


def test_dot_grid_with_controller(qtbot):
    from gamingcrypt.ui.secret_input import DotGridPad

    pad = DotGridPad()
    qtbot.addWidget(pad)
    pad.resize(500, 650)
    pad.show()
    qtbot.waitExposed(pad)
    nav = GamepadNavigator(pad)
    pad.canvas.setFocus()
    press(nav, e.BTN_SOUTH)  # centre dot (13)
    dpad(nav, dx=-1)
    dpad(nav, dy=-1)
    press(nav, e.BTN_SOUTH)  # dot 7
    press(nav, e.BTN_SOUTH)  # again 7 (repeats allowed)
    assert pad.nodes == [12, 6, 6]
    for _ in range(4):
        dpad(nav, dy=1)  # from row 2 down to the last row (5), then out of the grid
    assert focused() in (pad.back_button, pad.ok_button)


def test_swipe_pattern_with_controller(qtbot):
    from gamingcrypt.ui.secret_input import PatternWidget

    w = PatternWidget()
    qtbot.addWidget(w)
    w.resize(400, 400)
    w.show()
    qtbot.waitExposed(w)
    nav = GamepadNavigator(w)
    w.setFocus()
    entered = []
    w.pattern_entered.connect(entered.append)
    dpad(nav, dx=-1)
    dpad(nav, dy=-1)  # top-left
    press(nav, e.BTN_SOUTH)
    dpad(nav, dy=1)
    press(nav, e.BTN_SOUTH)
    press(nav, e.BTN_EAST)  # B clears
    assert w.nodes == []
    for move in ((0, -1), (0, 1), (0, 1), (1, 0)):  # cursor is still on the left middle dot
        dpad(nav, *move)
        press(nav, e.BTN_SOUTH)
    press(nav, e.BTN_START)
    assert entered == [[0, 3, 6, 7]]


def test_controller_page_pauses_navigation_while_remapping(qtbot):
    from tests.test_controller_settings import make

    page, *_ = make(qtbot)
    page.show()
    page.rows["a"][1].click()
    assert nav_mod._paused
    page.on_event(e.EV_KEY, e.BTN_WEST, 1)
    page.on_event(e.EV_SYN, 0, 0)
    assert not nav_mod._paused
    page.calibrate_button.click()
    assert nav_mod._paused
    page.cancel_cal_button.click()
    assert not nav_mod._paused


# --- input source ---------------------------------------------------------------------

class Service:
    def __init__(self, info, running=False):
        self.info, self.running = info, running

    def device(self):
        return self.info

    def profile(self, info):
        from gamingcrypt.input.profile import default_profile

        return default_profile(info.keys, info.axes)


def test_nav_source_prefers_virtual_controller_when_mapping_is_on():
    from gamingcrypt.input.nav_source import NavSource

    physical = e.DeviceInfo("/dev/input/event5", "Pad", keys={e.BTN_SOUTH})
    virtual = e.DeviceInfo("/dev/input/event9", e.VIRTUAL_NAME, keys={e.BTN_SOUTH})
    src = NavSource(Service(physical, running=True), lambda *a: None, devices=lambda: [physical, virtual])
    assert src.choose() == (virtual, True)
    src = NavSource(Service(physical, running=False), lambda *a: None, devices=lambda: [physical, virtual])
    assert src.choose() == (physical, False)
    assert NavSource(Service(None), lambda *a: None, devices=list).choose() is None


@pytest.mark.skipif(not os.access("/dev/uinput", os.W_OK), reason="/dev/uinput not writable")
def test_nav_source_real_controller():
    from gamingcrypt.input.nav_source import NavSource
    from tests.test_input import wait_for_device

    name = f"GC Nav Pad {os.getpid()}"
    pad = e.UInput(name=name, keys=[e.BTN_SOUTH, e.BTN_EAST],
                   axes=[e.AxisSpec(e.ABS_X, -32768, 32767), e.AxisSpec(e.ABS_Y, -32768, 32767),
                         e.AxisSpec(e.ABS_HAT0X, -1, 1), e.AxisSpec(e.ABS_HAT0Y, -1, 1)])
    got = []
    src = None
    try:
        info = wait_for_device(name)
        src = NavSource(Service(info), lambda *ev: got.append(ev))
        src.start()
        time.sleep(0.3)
        pad.emit([(e.EV_KEY, e.BTN_SOUTH, 1), (e.EV_ABS, e.ABS_HAT0X, 1), (e.EV_SYN, 0, 0)])
        deadline = time.time() + 2
        while time.time() < deadline and (e.EV_KEY, e.BTN_SOUTH, 1) not in got:
            time.sleep(0.05)
        assert (e.EV_KEY, e.BTN_SOUTH, 1) in got and (e.EV_ABS, e.ABS_HAT0X, 1) in got
    finally:
        if src is not None:
            src.stop()
        pad.close()


def test_tab_switch_moves_highlight_along(qtbot):
    from gamingcrypt.ui.shell import Shell

    shell = Shell()
    qtbot.addWidget(shell)
    shell.resize(1280, 800)
    shell.show()
    qtbot.waitExposed(shell)
    nav = GamepadNavigator(shell, tab_switch=shell.cycle_tab)
    shell.tab_buttons["Games"].setFocus()  # highlight moved up into the tab bar with the stick
    press(nav, e.BTN_TR)
    press(nav, e.BTN_TR)
    assert shell.current_tab == "Movies"
    assert shell.focusWidget() is shell.tab_buttons["Movies"]  # only one tab is marked
    checked = [n for n, b in shell.tab_buttons.items() if b.isChecked()]
    assert checked == ["Movies"]


def test_tab_switch_leaves_page_highlight_alone(qtbot):
    from gamingcrypt.ui.shell import Shell

    page = QWidget()
    inner = big_button("on the page")
    QVBoxLayout(page).addWidget(inner)
    shell = Shell({"Games": page})
    qtbot.addWidget(shell)
    shell.show()
    inner.setFocus()
    shell.cycle_tab(1)
    assert shell.focusWidget() is not shell.tab_buttons["Downloads"]


def test_tab_highlight_looks_different_from_the_open_tab():
    from gamingcrypt.ui import theme

    css = theme.STYLESHEET
    focus_rule = next(line for line in css.splitlines() if line.startswith("QPushButton#tab:focus"))
    assert theme.ACCENT not in focus_rule and theme.ACCENT_HI not in focus_rule  # no blue underline
    assert "transparent" in focus_rule and theme.SURFACE_HI in focus_rule


# --- rows with a caption: wide controls must not be skipped ------------------------------

class LongNamesAudio:
    """Real device names are long - the drop-downs get as wide as the row allows."""

    def devices(self, kind):
        from gamingcrypt.system.audio import Device

        name = {"output": "Family 17h/19h HD Audio Controller Speaker + Headphones",
                "input": "Family 17h/19h HD Audio Controller Digital Microphone"}[kind]
        return [Device(kind, name, 50, False, True)]

    def set_default(self, kind, name):
        return True

    def set_volume(self, kind, name, percent):
        return True


def walk_down(nav, steps):
    seen = [nav.focused()]
    for _ in range(steps):
        nav.move(0, 1)
        if nav.focused() is not seen[-1]:
            seen.append(nav.focused())
    return seen


def test_down_reaches_every_control_of_the_device_settings(qtbot, monkeypatch):
    """Was: the output / input drop-downs (and resolution, refresh) were jumped over -
    their centre is far right of a narrow button or slider above them."""
    import copy

    from PySide6.QtWidgets import QMainWindow

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.session import mode
    from gamingcrypt.system.controls import SystemControls
    from gamingcrypt.ui.settings_tab import SettingsTab
    from tests.test_system_settings import FakeBrightness

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(mode, "panel_size", lambda *a: (1280, 800))
    from gamingcrypt.ui import theme

    window = QMainWindow()
    window.setStyleSheet(theme.STYLESHEET)  # real sizes
    qtbot.addWidget(window)
    window.resize(1280, 800)
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None,
                      system=SystemControls(audio=LongNamesAudio(), brightness=FakeBrightness()),
                      restart_gaming=lambda: None)
    window.setCentralWidget(tab)
    window.show()
    qtbot.waitExposed(window)
    qtbot.wait(50)  # let the layout settle (sizes from the stylesheet)
    nav = GamepadNavigator(window)
    nav.focus(tab.sub_buttons["Device"])
    d, a = tab.display_section, tab.audio_section
    expected = [tab.sub_buttons["Device"], d.gs_resolution, d.gs_refresh, d.gs_apply, d.brightness_slider,
                a.combos["output"], a.sliders["output"], a.combos["input"], a.sliders["input"], a.step_slider]
    assert walk_down(nav, 12) == expected


def test_down_reaches_every_control_of_the_quick_menu(qtbot):
    from PySide6.QtWidgets import QMainWindow

    from gamingcrypt.system.battery import BatteryState
    from gamingcrypt.system.controls import SystemControls
    from gamingcrypt.ui.quick_menu import QuickMenu
    from tests.test_quick_menu import Brightness

    from gamingcrypt.ui import theme

    window = QMainWindow()
    window.setStyleSheet(theme.STYLESHEET)  # real sizes
    qtbot.addWidget(window)
    window.resize(1280, 800)
    window.show()
    menu = QuickMenu(window, SystemControls(audio=LongNamesAudio(), brightness=Brightness()),
                     refresh_get=lambda: 0, refresh_set=lambda hz: True,
                     battery_reader=lambda: BatteryState(64, False, False))
    window.nav_root = lambda: menu
    menu.open_menu(620, "Portal 2")
    qtbot.waitExposed(window)
    qtbot.wait(50)
    nav = GamepadNavigator(window)
    assert walk_down(nav, 9) == [menu.back_button, menu.output, menu.input, menu.volume,
                                 menu.brightness, menu.refresh, menu.quit_button]


def test_highlighted_slider_is_clearly_visible(qtbot):
    """A focused slider gets a blue frame - grey on the grey card wasn't visible."""
    from PySide6.QtGui import QColor

    from gamingcrypt.ui import theme
    from gamingcrypt.ui.system_settings import _slider

    host = QWidget()
    host.setStyleSheet(theme.STYLESHEET)
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    first, second = _slider(0, 100, 0), _slider(0, 100, 0)  # value 0: the knob sits left
    layout.addWidget(first)
    layout.addWidget(second)
    host.resize(400, 200)
    host.show()
    qtbot.waitExposed(host)

    def right_edge(slider):
        image = slider.grab().toImage()
        return QColor(image.pixel(image.width() - 2, image.height() // 2))

    first.setFocus()
    qtbot.waitUntil(first.hasFocus)
    accent = QColor(theme.ACCENT)
    assert right_edge(first) == accent  # the frame
    assert right_edge(second) != accent

"""Settings -> Controller -> Controller test: live Xbox-style schematic with values."""

import copy

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import controller_test as ct
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.controller_test import ControllerState, ControllerTestPage


def test_state_from_standard_events():
    s = ControllerState()
    for ev in ((e.EV_KEY, e.BTN_SOUTH, 1), (e.EV_ABS, e.ABS_X, 32767), (e.EV_ABS, e.ABS_Y, -16384),
               (e.EV_ABS, e.ABS_Z, 255), (e.EV_ABS, e.ABS_HAT0Y, -1), (e.EV_ABS, e.ABS_HAT0X, 1)):
        s.feed(*ev)
    assert e.BTN_SOUTH in s.pressed and s.stick(e.ABS_X, e.ABS_Y) == (1.0, -0.5)
    assert s.trigger(e.ABS_Z) == 1.0 and s.dpad() == "Up + Right"
    s.feed(e.EV_KEY, e.BTN_SOUTH, 0)
    assert not s.pressed


def test_values_next_to_the_buttons(qtbot):
    page = ControllerTestPage()
    qtbot.addWidget(page)
    page.on_event(e.EV_KEY, e.BTN_SOUTH, 1)
    page.on_event(e.EV_ABS, e.ABS_RX, -32767)
    sch = page.schematic
    assert sch.value_text("a") == "A  BTN_SOUTH  ●" and sch.active("a")
    assert sch.value_text("b") == "B  BTN_EAST" and not sch.active("b")
    assert sch.value_text("rstick") == "Right stick  -1.00 +0.00" and sch.active("rstick")
    assert sch.value_text("lt") == "LT  ABS_Z 0.00"
    every = set(ct.LEFT_ROWS + ct.RIGHT_ROWS)
    assert every >= {b[0] for b in ct.BUTTONS} | {"lstick", "rstick", "dpad", "lt", "rt"}  # everything listed


def test_system_meanings(qtbot):
    page = ControllerTestPage(labels_for=lambda system: {"a": "N64: A", "rstick": "N64: C-buttons"},
                              systems=[("n64", "Nintendo 64")])
    qtbot.addWidget(page)
    assert page.system_combo.isVisibleTo(page)
    page.system_combo.setCurrentIndex(1)
    assert page.schematic.value_text("a").startswith("N64: A  ·  A")
    assert page.schematic.value_text("rstick").startswith("N64: C-buttons")


def test_testing_doesnt_navigate_and_holding_b_leaves(qtbot, monkeypatch):
    monkeypatch.setattr(ct, "EXIT_HOLD_S", 0.05)
    page = ControllerTestPage()
    qtbot.addWidget(page)
    page.show()
    assert page.on_event in nav_mod.LISTENERS
    closed = []
    page.closed.connect(lambda: closed.append(1))
    assert page.on_event(e.EV_KEY, e.BTN_EAST, 1) is True  # B: shown, not "back"
    page.on_event(e.EV_KEY, e.BTN_EAST, 0)  # released early: stays
    qtbot.wait(100)
    assert closed == []
    page.on_event(e.EV_KEY, e.BTN_EAST, 1)
    qtbot.waitUntil(lambda: closed == [1])
    assert page.on_event not in nav_mod.LISTENERS


def test_settings_opens_and_closes_it(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(tab)
    tab.show()
    tab.controller_test_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ControllerTestPage)
    page.done_button.click()
    assert tab.currentWidget() is tab.overview and page.on_event not in nav_mod.LISTENERS


def test_schematic_paints(qtbot):
    page = ControllerTestPage()
    qtbot.addWidget(page)
    page.resize(1280, 640)
    page.show()
    page.on_event(e.EV_ABS, e.ABS_HAT0X, -1)
    assert not page.grab().isNull()

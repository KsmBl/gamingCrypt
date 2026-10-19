"""The on-screen keyboard on a device button (Settings -> Controller -> Device buttons)."""

import copy

import pytest
from PySide6.QtWidgets import QLineEdit

from gamingcrypt.config import DEFAULTS
from gamingcrypt.input import evdev as e
from gamingcrypt.input import hotkeys
from gamingcrypt.input.hotkeys import KEY, PAD, Binding, Tracker

KEYBOARD = hotkeys.ACTION_CODES["keyboard"]


def test_defaults_and_names():
    assert hotkeys.defaults("AYANEO", "")["keyboard"].describe() == "Windows + Volume Up"
    assert hotkeys.defaults("Valve", "Jupiter")["keyboard"] == Binding(PAD, (e.BTN_MODE, e.BTN_NORTH))
    assert hotkeys.load_external({})["keyboard"].describe() == "Guide + X (controller)"
    assert KEYBOARD not in (hotkeys.ACTION_CODES["quick_menu"], hotkeys.ACTION_CODES["lock"])


def test_combination_fires_and_volume_up_alone_still_works():
    t = Tracker(dict(hotkeys.WINDOWS), KEY)
    t.feed(e.KEY_LEFTMETA, True)
    assert t.feed(e.KEY_VOLUMEUP, True) == (["keyboard"], True)
    t.feed(e.KEY_VOLUMEUP, False)
    t.feed(e.KEY_LEFTMETA, False)
    assert t.feed(e.KEY_VOLUMEUP, True) == ([], False)


@pytest.fixture
def window(qtbot):
    from gamingcrypt.app import MainWindow

    cfg = copy.deepcopy(DEFAULTS)
    cfg["input"]["hotkeys"] = {"quick_menu": {"source": "pad", "codes": [e.BTN_MODE]},
                               "keyboard": {"source": "pad", "codes": [e.BTN_MODE, e.BTN_NORTH]}}
    w = MainWindow(cfg, lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.resize(1280, 800)
    w.show()
    w.show_shell()
    return w


def field_on_page(window) -> QLineEdit:
    page = window.shell.stack.currentWidget() if hasattr(window.shell, "stack") else window.shell
    edit = QLineEdit(page)
    edit.move(40, 40)
    edit.show()
    return edit


def test_combination_opens_the_keyboard_for_the_field_and_types(qtbot, window):
    edit = field_on_page(window)
    edit.setFocus()
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 1)  # Guide …
    window.pad_hotkey(e.EV_KEY, e.BTN_NORTH, 1)  # … + X: the keyboard
    window.pad_hotkey(e.EV_KEY, e.BTN_NORTH, 0)
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 0)
    overlay = window.keyboard_overlay
    assert overlay.isVisible() and getattr(window, "quick_menu", None) is None  # no quick menu on the way
    assert overlay.target() is edit and window.nav_root() is overlay
    overlay.keys.type_text("h")
    overlay.keys.type_text("i")
    assert edit.text() == "hi"
    entered = []
    edit.returnPressed.connect(lambda: entered.append(edit.text()))
    overlay.keys.submitted.emit()
    assert entered == ["hi"] and not overlay.isVisible()


def test_button_again_or_back_closes_it(qtbot, window):
    field_on_page(window)
    window.hardware_key(KEYBOARD)
    overlay = window.keyboard_overlay
    assert overlay.isVisible()
    window.hardware_key(KEYBOARD)
    assert not overlay.isVisible()
    window.hardware_key(KEYBOARD)
    assert overlay.gamepad_back() and not overlay.isVisible()


def test_out_of_the_fields_way(qtbot, window):
    edit = field_on_page(window)
    edit.move(40, window.height() - 60)
    window.hardware_key(KEYBOARD)
    assert window.keyboard_overlay.y() < window.height() // 2  # docked at the top instead


def test_no_field_says_so(qtbot, window):
    from PySide6.QtWidgets import QLineEdit as Edit

    for edit in window.nav_root().findChildren(Edit):
        edit.setEnabled(False)
    window.hardware_key(KEYBOARD)
    assert getattr(window, "keyboard_overlay", None) is None
    assert any("No text field" in text for text in window.toasts.shown + [t for _i, t in window.toasts.queue])

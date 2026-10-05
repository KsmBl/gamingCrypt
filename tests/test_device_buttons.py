"""Device buttons: quick menu / lock now on any button (not every handheld has a Windows key)."""

import copy
import time

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.input import evdev as e
from gamingcrypt.input import hotkeys
from gamingcrypt.input.hotkeys import KEY, PAD, Binding, Tracker

QUICK = hotkeys.ACTION_CODES["quick_menu"]
LOCK = hotkeys.ACTION_CODES["lock"]


def test_defaults_by_handheld():
    assert hotkeys.defaults("AYANEO", "AYANEO 2021 Pro")["quick_menu"] == Binding(KEY, (e.KEY_LEFTMETA,))
    assert hotkeys.defaults("AYANEO", "")["lock"].describe() == "Windows + Volume Down"
    deck = hotkeys.defaults("Valve", "Jupiter")
    assert deck["quick_menu"] == Binding(PAD, (e.BTN_MODE,)) and deck["quick_menu"].describe() == "Guide (controller)"
    assert hotkeys.defaults("Unknown Inc", "x")["quick_menu"].codes == (e.KEY_LEFTMETA,)


def test_config_overrides_and_bad_entries():
    cfg = {"input": {"hotkeys": {"quick_menu": {"source": "key", "codes": [148], "device": "Asus WMI hotkeys"},
                                 "lock": {"source": "nope", "codes": [1]}}}}
    bindings = hotkeys.load(cfg, ("AYANEO", ""))
    assert bindings["quick_menu"] == Binding(KEY, (148,), "Asus WMI hotkeys")
    assert bindings["quick_menu"].describe() == "Prog1"
    assert bindings["lock"] == hotkeys.WINDOWS["lock"]  # broken entry: default
    hotkeys.save(cfg, "quick_menu", None)
    assert "quick_menu" not in cfg["input"]["hotkeys"]
    assert Binding.from_dict({"source": "pad", "codes": [1, 2, 3]}) is None  # at most two


def test_tracker_single_combo_and_consumed():
    t = Tracker(dict(hotkeys.WINDOWS), KEY)
    assert t.feed(e.KEY_RIGHTMETA, True) == (["quick_menu"], True)  # either Windows key
    assert t.feed(e.KEY_VOLUMEDOWN, True) == (["lock"], True)  # held Windows + Volume Down
    t.feed(e.KEY_VOLUMEDOWN, False)
    t.feed(e.KEY_RIGHTMETA, False)
    assert t.feed(e.KEY_VOLUMEDOWN, True) == ([], False)  # alone: just volume
    pad = Tracker({"quick_menu": Binding(PAD, (e.BTN_SELECT, e.BTN_START))}, PAD)
    assert pad.feed(e.BTN_START, True) == ([], False)
    pad.feed(e.BTN_START, False)
    pad.feed(e.BTN_SELECT, True)
    assert pad.feed(e.BTN_START, True) == (["quick_menu"], True)
    assert t.watched() == {e.KEY_LEFTMETA, e.KEY_VOLUMEDOWN}


def test_reader_uses_the_recorded_key():
    from gamingcrypt.input.volume_keys import VolumeKeys
    from tests.test_volume_keys import FakeDevice

    device = FakeDevice([[(e.EV_KEY, 148, 1), (e.EV_KEY, 148, 0)],
                         [(e.EV_KEY, e.KEY_LEFTMETA, 1), (e.EV_KEY, e.KEY_LEFTMETA, 0)],
                         [(e.EV_KEY, e.KEY_VOLUMEUP, 1)]])
    got = []
    bindings = {"quick_menu": Binding(KEY, (148,)), "lock": Binding(KEY, (148, e.KEY_VOLUMEDOWN))}
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/x", "kbd")], open_device=lambda p: device,
                      bindings=bindings)
    keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(got) < 2:
        time.sleep(0.01)
    keys.stop()
    assert got == [QUICK, e.KEY_VOLUMEUP]  # the Windows key does nothing now


def test_volume_repeat_after_a_combo_doesnt_change_the_volume():
    from gamingcrypt.input.volume_keys import VolumeKeys

    got = []
    keys = VolumeKeys(got.append, bindings=dict(hotkeys.WINDOWS))
    for code, value in ((e.KEY_LEFTMETA, 1), (e.KEY_VOLUMEDOWN, 1), (e.KEY_VOLUMEDOWN, 2), (e.KEY_VOLUMEDOWN, 2),
                        (e.KEY_VOLUMEDOWN, 0), (e.KEY_LEFTMETA, 0), (e.KEY_VOLUMEDOWN, 1)):
        keys._key(code, value)
    assert got == [QUICK, LOCK, e.KEY_VOLUMEDOWN]


# --- the window ---------------------------------------------------------------------------

@pytest.fixture
def window(qtbot):
    from gamingcrypt.app import MainWindow

    cfg = copy.deepcopy(DEFAULTS)
    cfg["input"]["hotkeys"] = {"quick_menu": {"source": "pad", "codes": [e.BTN_MODE]},
                               "lock": {"source": "pad", "codes": [e.BTN_MODE, e.BTN_SELECT]}}
    w = MainWindow(cfg, lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    return w


def test_guide_button_opens_the_quick_menu(qtbot, window):
    assert window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 1) is True  # used up: doesn't navigate
    assert window.quick_menu.isVisible()
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 0)
    assert window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 1) is False  # A still navigates
    window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 0)
    locked = []
    window.panic_lock = lambda: locked.append(1)
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 1)
    window.pad_hotkey(e.EV_KEY, e.BTN_SELECT, 1)
    assert locked == [1]


def test_navigator_lets_hotkeys_and_listeners_go_first(qtbot, window):
    from gamingcrypt.ui import navigator as nav_mod
    from gamingcrypt.ui.navigator import GamepadNavigator

    nav = GamepadNavigator(window)
    nav.hotkey_filter = window.pad_hotkey
    activated = []
    nav.activate = lambda: activated.append(1)
    nav.on_event(e.EV_KEY, e.BTN_MODE, 1)
    assert window.quick_menu.isVisible() and activated == []
    nav.on_event(e.EV_KEY, e.BTN_MODE, 0)
    seen = []
    listener = lambda *ev: seen.append(ev) or True  # noqa: E731
    nav_mod.LISTENERS.append(listener)
    try:
        nav.on_event(e.EV_KEY, e.BTN_SOUTH, 1)
    finally:
        nav_mod.LISTENERS.remove(listener)
    assert seen == [(e.EV_KEY, e.BTN_SOUTH, 1)] and activated == []


def test_recorded_device_gets_read_and_listed_for_install(monkeypatch, capsys, tmp_path):
    from gamingcrypt import app

    devices = [e.DeviceInfo("/dev/input/event3", "AT Translated Set 2 keyboard", keys={e.KEY_VOLUMEUP}),
               e.DeviceInfo("/dev/input/event9", "Asus WMI hotkeys", keys={148})]
    monkeypatch.setattr(e, "list_devices", lambda *a: devices)
    cfg = tmp_path / "config.json"
    cfg.write_text('{"input": {"hotkeys": {"quick_menu": {"source": "key", "codes": [148], '
                   '"device": "Asus WMI hotkeys"}}}}')
    assert app.main(["--config", str(cfg), "--volume-key-devices"]) == 0
    assert capsys.readouterr().out.splitlines() == ["AT Translated Set 2 keyboard", "Asus WMI hotkeys"]


# --- recording in Settings -------------------------------------------------------------------

class FakeCapture:
    made = []

    def __init__(self, on_event):
        self.on_event = on_event
        self.stopped = False
        FakeCapture.made.append(self)

    def start(self):
        return 1

    def stop(self):
        self.stopped = True


@pytest.fixture
def section(qtbot):
    from gamingcrypt.ui.device_buttons import DeviceButtonsSection

    FakeCapture.made = []
    cfg = copy.deepcopy(DEFAULTS)
    saved = []
    s = DeviceButtonsSection(cfg, saved.append, capture_factory=FakeCapture)
    qtbot.addWidget(s)
    s.show()
    s._saved, s._cfg = saved, cfg
    return s


def test_record_a_key_combination(qtbot, section):
    changed = []
    section.changed.connect(lambda: changed.append(1))
    section.change_buttons["lock"].click()
    assert "Press the button" in section.status.text()
    capture = FakeCapture.made[-1]
    for name, code, value in (("Buttons", 148, 1), ("Buttons", e.KEY_VOLUMEUP, 1),
                              ("Buttons", e.KEY_VOLUMEUP, 0), ("Buttons", 148, 0)):
        capture.on_event(name, code, value)
    qtbot.waitUntil(lambda: changed == [1])
    assert section._cfg["input"]["hotkeys"]["lock"] == {"source": "key", "codes": [148, e.KEY_VOLUMEUP],
                                                        "device": "Buttons"}
    assert section.labels["lock"].text() == "Prog1 + Volume Up" and capture.stopped


def test_record_a_controller_button_and_reserved_ones(qtbot, section):
    from gamingcrypt.ui import navigator as nav_mod

    section.change_buttons["quick_menu"].click()
    assert nav_mod.LISTENERS  # controller input goes to the recording, not to navigation
    listener = nav_mod.LISTENERS[-1]
    assert listener(e.EV_KEY, e.BTN_SOUTH, 1) is True
    listener(e.EV_KEY, e.BTN_SOUTH, 0)
    assert "A alone is needed" in section.status.text() and not nav_mod.LISTENERS
    section.change_buttons["quick_menu"].click()
    listener = nav_mod.LISTENERS[-1]
    listener(e.EV_KEY, e.BTN_MODE, 1)
    listener(e.EV_KEY, e.BTN_MODE, 0)
    assert section.labels["quick_menu"].text() == "Guide (controller)"
    section.default_buttons["quick_menu"].click()
    assert "(default)" in section.labels["quick_menu"].text()


def test_recording_times_out_and_stops_on_leaving(qtbot, section, monkeypatch):
    from gamingcrypt.ui import navigator as nav_mod

    section.change_buttons["quick_menu"].click()
    section._timed_out()
    assert "nothing changed" in section.status.text() and FakeCapture.made[-1].stopped and not nav_mod.LISTENERS
    section.change_buttons["quick_menu"].click()
    section.hide()  # left the page
    assert FakeCapture.made[-1].stopped and not nav_mod.LISTENERS


def test_settings_change_reaches_the_app(qtbot):
    from gamingcrypt.app import MainWindow

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.show_shell()
    settings = window.shell.pages["Settings"]
    from gamingcrypt.input import hotkeys as hk

    hk.save(settings.config, "quick_menu", Binding(PAD, (e.BTN_MODE,)))
    settings.device_buttons.changed.emit()
    assert window.hotkeys["quick_menu"] == Binding(PAD, (e.BTN_MODE,))

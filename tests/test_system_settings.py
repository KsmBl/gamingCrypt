import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.system import display
from gamingcrypt.system.audio import Device
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.system.power import PowerLimit
from gamingcrypt.ui import system_settings
from gamingcrypt.ui.settings_tab import SettingsTab

HD = display.Mode(1920, 1080, 60.0)
HD48 = display.Mode(1920, 1080, 48.0)
SD90 = display.Mode(1280, 800, 90.0)


class FakeDisplay:
    def __init__(self, ok=True):
        self.ok = ok
        self.output = display.Output("eDP-1", "Panel", [HD, HD48, SD90], HD)
        self.sets = []

    def outputs(self):
        return [self.output]

    def set_mode(self, output, mode):
        self.sets.append(mode)
        return (True, "ok") if self.ok else (False, "mode rejected")


class FakeBrightness:
    def __init__(self):
        self.values = []

    def get(self):
        return 70

    def set(self, p):
        self.values.append(p)
        return True


class FakePower:
    can_set = True

    def __init__(self):
        self.sets = []

    def read(self):
        return PowerLimit(15, 4, 30, "amdgpu")

    def set(self, w):
        self.sets.append(w)
        return True, f"Power limit set to {w} W"


class FakeAudio:
    def __init__(self):
        self.defaults = {"output": "speakers", "input": "mic"}
        self.calls = []

    def devices(self, kind):
        names = {"output": [("speakers", "Speakers", 50), ("headset", "USB Headset", 80)],
                 "input": [("mic", "Internal Mic", 100)]}[kind]
        return [Device(n, d, v, False, n == self.defaults[kind]) for n, d, v in names]

    def set_default(self, kind, name):
        self.calls.append(("default", kind, name))
        self.defaults[kind] = name
        return True

    def set_volume(self, kind, name, percent):
        self.calls.append(("volume", kind, name, percent))
        return True


def make(qtbot, **controls):
    cfg = copy.deepcopy(DEFAULTS)
    saved = []
    system = SystemControls(**controls)
    tab = SettingsTab(cfg, saved.append, system=system)
    qtbot.addWidget(tab)
    return tab, cfg, saved


def test_everything_unavailable_is_explained(qtbot):
    tab, *_ = make(qtbot)
    from PySide6.QtWidgets import QLabel

    texts = " ".join(l.text() for l in tab.findChildren(QLabel))
    assert "not supported on this desktop" in texts
    assert "Brightness: not available" in texts
    assert "no adjustable power limit" in texts
    assert "pactl not found" in texts


def test_display_shows_current_mode(qtbot):
    tab, *_ = make(qtbot, display=FakeDisplay())
    d = tab.display_section
    assert d.resolution.currentText() == "1920×1080"
    assert [d.refresh.itemText(i) for i in range(d.refresh.count())] == ["60 Hz", "48 Hz"]
    d.resolution.setCurrentIndex(d.resolution.findData("1280x800"))
    assert d.refresh.currentText() == "90 Hz"


def test_display_apply_then_keep_saves(qtbot):
    fake = FakeDisplay()
    tab, cfg, saved = make(qtbot, display=fake)
    d = tab.display_section
    d.resolution.setCurrentIndex(d.resolution.findData("1280x800"))
    d.apply_button.click()
    qtbot.waitUntil(lambda: not d.confirm.isHidden())
    assert fake.sets == [SD90] and "Reverting in 15 s" in d.confirm_label.text()
    d.keep_button.click()
    assert d.confirm.isHidden()
    assert saved[-1]["system"]["display"] == {"output": "eDP-1", "width": 1280, "height": 800, "refresh": 90.0}


def test_display_reverts_by_itself(qtbot, monkeypatch):
    monkeypatch.setattr(system_settings, "KEEP_SECONDS", 2)
    fake = FakeDisplay()
    tab, cfg, saved = make(qtbot, display=fake)
    d = tab.display_section
    d._countdown.setInterval(10)
    d.apply_mode(SD90)
    qtbot.waitUntil(lambda: not d.confirm.isHidden())
    d._countdown.setInterval(10)
    qtbot.waitUntil(lambda: fake.sets == [SD90, HD], timeout=3000)
    qtbot.waitUntil(lambda: "Back to 1920×1080" in d.status.text())
    assert saved == [] and d.resolution.currentText() == "1920×1080"


def test_display_revert_button_and_failure(qtbot):
    fake = FakeDisplay()
    tab, *_ = make(qtbot, display=fake)
    d = tab.display_section
    d.apply_mode(HD48)
    qtbot.waitUntil(lambda: not d.confirm.isHidden())
    d.revert_button.click()
    qtbot.waitUntil(lambda: fake.sets == [HD48, HD])
    bad = FakeDisplay(ok=False)
    tab2, *_ = make(qtbot, display=bad)
    tab2.display_section.apply_mode(SD90)
    qtbot.waitUntil(lambda: "mode rejected" in tab2.display_section.status.text())
    assert tab2.display_section.confirm.isHidden()


def test_same_mode_is_not_applied(qtbot):
    fake = FakeDisplay()
    tab, *_ = make(qtbot, display=fake)
    tab.display_section.apply_button.click()
    assert fake.sets == []


def test_brightness_slider(qtbot):
    b = FakeBrightness()
    tab, *_ = make(qtbot, brightness=b)
    d = tab.display_section
    assert d.brightness_value.text() == "70%"
    d.brightness_slider.setValue(40)
    assert b.values == [40] and d.brightness_value.text() == "40%"


def test_power_slider_sets_and_saves(qtbot):
    p = FakePower()
    tab, cfg, saved = make(qtbot, power=p)
    s = tab.power_section
    assert (s.slider.minimum(), s.slider.maximum(), s.value.text()) == (4, 30, "15 W")
    s.slider.setValue(10)
    qtbot.waitUntil(lambda: "10 W" in s.status.text() and bool(saved))
    assert p.sets == [10] and saved[-1]["system"]["power_limit_w"] == 10


def test_power_slider_disabled_without_helper(qtbot):
    p = FakePower()
    p.can_set = False
    tab, *_ = make(qtbot, power=p)
    assert not tab.power_section.slider.isEnabled()


def test_audio_switch_device_and_volume(qtbot):
    a = FakeAudio()
    tab, *_ = make(qtbot, audio=a)
    s = tab.audio_section
    assert a.calls == []  # opening settings changes nothing
    assert s.combos["output"].currentText() == "Speakers" and s.sliders["output"].value() == 50
    s.combos["output"].setCurrentIndex(s.combos["output"].findData("headset"))
    assert a.calls == [("default", "output", "headset")]
    assert s.sliders["output"].value() == 80 and "USB Headset" in s.status.text()
    s.sliders["input"].setValue(55)
    assert a.calls[-1] == ("volume", "input", "mic", 55)


def test_settings_sub_tabs(qtbot):
    tab, *_ = make(qtbot, display=FakeDisplay(), audio=FakeAudio())
    assert list(tab.sub_buttons) == ["Device", "Controller", "Steam", "Security"]
    assert tab.current_sub_tab == "Device"
    page = tab.sub_pages["Security"].widget()
    assert not tab.reset_button.isVisibleTo(tab.sub_stack)
    tab.sub_buttons["Security"].click()
    assert tab.sub_stack.currentWidget() is tab.sub_pages["Security"]
    assert tab.reset_button.isVisibleTo(page) and tab.sub_buttons["Security"].isChecked()
    tab.sub_buttons["Steam"].click()
    assert tab.api_key_button.isVisibleTo(tab.sub_pages["Steam"].widget())

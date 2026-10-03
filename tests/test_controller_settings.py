import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import AxisCal, Source
from gamingcrypt.input.service import InputService
from gamingcrypt.ui.controller_settings import ControllerPage
from gamingcrypt.ui.settings_tab import SettingsTab
from tests.test_input import ABSINFO, AXES, KEYS, PAD, FakeRemapper


class FakeReader:
    instances = []

    def __init__(self, info, emit):
        self.info, self.emit = info, emit
        self.running = False
        FakeReader.instances.append(self)

    def absinfo(self):
        return dict(ABSINFO)

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


def make(qtbot, pads=(PAD,), enabled=False):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["input"]["enabled"] = enabled
    saved = []
    remappers = []

    def factory(info, profile):
        remappers.append(FakeRemapper(info, profile))
        return remappers[-1]

    service = InputService(cfg, saved.append, finder=lambda: list(pads), remapper_factory=factory)
    page = ControllerPage(service, reader_factory=FakeReader)
    qtbot.addWidget(page)
    return page, service, cfg, saved, remappers


def push(page, *events):
    for event in events:
        page.on_event(*event)
    page.on_event(e.EV_SYN, 0, 0)


def test_no_controller(qtbot):
    page, *_ = make(qtbot, pads=())
    assert "No controller found" in page.device_label.text()
    assert page.sticks.isHidden() and page.buttons.isHidden()


def test_shows_mapping_and_pauses_remapper_while_open(qtbot):
    page, service, cfg, saved, remappers = make(qtbot, enabled=True)
    service.start()
    assert service.running
    assert "Handheld" in page.device_label.text()
    assert page.rows["a"][0].text() == "South (A)" and page.rows["dpad_up"][0].text() == "Axis Hat Y -"
    page.show()
    assert not service.running and FakeReader.instances[-1].running  # raw controller is read, not grabbed
    page.hide()
    assert service.running and not FakeReader.instances[-1].running


def test_live_stick_view(qtbot):
    page, *_ = make(qtbot)
    page.show()
    push(page, (e.EV_ABS, e.ABS_X, 32767), (e.EV_ABS, e.ABS_RY, -32768))
    assert page.left_view.raw[0] == 1.0 and page.left_view.out[0] == 1.0
    assert page.right_view.out[1] == -1.0


def test_remap_button(qtbot):
    page, service, cfg, saved, _ = make(qtbot)
    page.show()
    page.rows["a"][1].click()
    assert page.rows["a"][0].text() == "Press the button now…" and page.rows["a"][1].text() == "Cancel"
    push(page, (e.EV_KEY, e.BTN_WEST, 1))
    assert page.profile.buttons["a"] == Source("key", e.BTN_WEST)
    assert page.rows["a"][0].text() == "West (Y)"
    assert saved[-1]["input"]["profiles"][PAD.key]["buttons"]["a"] == {"type": "key", "code": e.BTN_WEST}
    assert "A → West (Y)" in page.buttons.status.text()


def test_remap_cancel_by_tapping_again(qtbot):
    page, *_ = make(qtbot)
    page.show()
    page.rows["b"][1].click()
    page.rows["b"][1].click()
    push(page, (e.EV_KEY, e.BTN_WEST, 1))
    assert page.profile.buttons["b"] == Source("key", e.BTN_EAST)


def test_trigger_mapped_to_button_and_back_to_axis(qtbot):
    page, *_ = make(qtbot)
    page.show()
    page.rows["lt"][1].click()
    push(page, (e.EV_KEY, e.BTN_TL, 1))
    assert page.profile.buttons["lt"] == Source("key", e.BTN_TL) and page.profile.axes["lt"] is None
    page.rows["lt"][1].click()
    push(page, (e.EV_ABS, e.ABS_Z, 250))
    assert page.profile.axes["lt"] == e.ABS_Z  # analog again


def test_calibration_flow(qtbot):
    page, service, cfg, saved, _ = make(qtbot)
    page.show()
    page.calibrate_button.click()
    assert page.next_button.isVisible() and "1/2" in page.calibration_text.text()
    push(page, (e.EV_ABS, e.ABS_X, 600), (e.EV_ABS, e.ABS_X, 400))
    page.next_button.click()
    assert page.next_button.text() == "Done"
    page.next_button.click()  # nothing moved yet
    assert "Move further" in page.sticks.status.text()
    for code in (e.ABS_X, e.ABS_Y, e.ABS_RX, e.ABS_RY):
        push(page, (e.EV_ABS, code, -31000), (e.EV_ABS, code, 30000))
    for code in (e.ABS_Z, e.ABS_RZ):
        push(page, (e.EV_ABS, code, 2), (e.EV_ABS, code, 251))
    page.next_button.click()
    assert "Calibration done" in page.sticks.status.text()
    assert page.calibrate_button.isVisible() and not page.next_button.isVisible()
    stored = saved[-1]["input"]["profiles"][PAD.key]["calibration"]
    # median of the rest samples incl. the start value: [0, 600, 400] -> 400
    assert stored[str(e.ABS_X)] == {"center": 400, "min": -31000, "max": 30000}
    assert page.calibration_text.text() == "Calibrated"


def test_calibration_cancel_and_deadzone(qtbot):
    page, service, cfg, saved, _ = make(qtbot)
    page.show()
    page.calibrate_button.click()
    page.cancel_cal_button.click()
    assert page.session is None and page.calibrate_button.isVisible()
    page.deadzone_slider.setValue(15)
    assert page.profile.deadzone == 0.15 and saved[-1]["input"]["profiles"][PAD.key]["deadzone"] == 0.15


def test_reset_to_defaults(qtbot):
    page, service, cfg, saved, _ = make(qtbot)
    page.show()
    page.profile.calibration[e.ABS_X] = AxisCal(1, 0, 2)
    page.save()
    page.reset()
    assert page.profile.calibration == {} and PAD.key not in cfg["input"]["profiles"]


def test_enable_toggle(qtbot):
    page, service, cfg, saved, remappers = make(qtbot)
    page.enable_button.click()
    assert cfg["input"]["enabled"] and service.running
    assert "on" in page.top.status.text()
    page.enable_button.click()
    assert not service.running


def test_enable_while_page_open_starts_on_leave(qtbot):
    page, service, *_ = make(qtbot)
    page.show()
    page.enable_button.click()
    assert not service.running  # we're reading the raw controller right now
    page.hide()
    assert service.running


def test_reader_error_is_shown(qtbot):
    def broken(info, emit):
        raise PermissionError(13, "Permission denied")

    cfg = copy.deepcopy(DEFAULTS)
    service = InputService(cfg, lambda c: None, finder=lambda: [PAD])
    page = ControllerPage(service, reader_factory=broken)
    qtbot.addWidget(page)
    page.show()
    assert "Permission denied" in page.top.status.text()


def test_settings_has_controller_tab(qtbot):
    cfg = copy.deepcopy(DEFAULTS)
    service = InputService(cfg, lambda c: None, finder=lambda: [PAD])
    tab = SettingsTab(cfg, lambda c: None, input_service=service)
    qtbot.addWidget(tab)
    assert tab.controller_page.service is service
    assert "Handheld" in tab.controller_page.device_label.text()

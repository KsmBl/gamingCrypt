import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.secret_input import PatternWidget, PinPad
from gamingcrypt.unlock.veracrypt import UnlockResult


class FakeUnlocker:
    def __init__(self, cfg, log, current="oldpass"):
        self.cfg = cfg
        self.log = log
        self.current = current

    def change_password(self, current, new):
        self.log.append((self.cfg["volume"], current, new))
        if current != self.current:
            return UnlockResult(False, "Wrong code - please try again")
        return UnlockResult(True, "Unlock method changed")


def make(qtbot, first_start=True, method="", current="oldpass"):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"]["method"] = method
    if method:
        cfg["unlock"]["volume"] = "/dev/sdb1"
    saved, log = [], []
    wizard = AuthSetupWizard(
        cfg, lambda c: saved.append(copy.deepcopy(c)),
        lambda ucfg: FakeUnlocker(ucfg, log, current), first_start=first_start,
    )
    qtbot.addWidget(wizard)
    return wizard, cfg, saved, log


def test_first_start_full_flow_sets_pin(qtbot):
    wizard, cfg, saved, log = make(qtbot)
    assert wizard.step == "volume"
    wizard.submit_volume("  /dev/sdb1 ", "/mnt/games")
    assert wizard.step == "current"
    assert wizard.input_page.method == "password"
    wizard.input_page.widget.edit.setText("oldpass")
    wizard.input_page.widget.keyboard.submitted.emit()
    assert wizard.step == "method"
    wizard.method_buttons["pin"].click()
    assert isinstance(wizard.input_page.widget, PinPad)
    for key in "2468✓":
        wizard.input_page.widget.press(key)
    assert wizard.step == "confirm"
    with qtbot.waitSignal(wizard.completed, timeout=3000):
        for key in "2468✓":
            wizard.input_page.widget.press(key)
    assert log == [("/dev/sdb1", "oldpass", "2468")]
    assert saved[-1]["unlock"]["method"] == "pin"
    assert saved[-1]["unlock"]["volume"] == "/dev/sdb1"
    assert saved[-1]["unlock"]["mount_point"] == "/mnt/games"


def test_empty_volume_is_rejected(qtbot):
    wizard, *_ = make(qtbot)
    wizard.submit_volume("", "")
    assert wizard.step == "volume"
    assert "path" in wizard.status.text()


def test_confirmation_mismatch_restarts_new_secret(qtbot):
    wizard, cfg, saved, log = make(qtbot)
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("oldpass")
    wizard.choose_method("pattern")
    assert isinstance(wizard.input_page.widget, PatternWidget)
    wizard.input_page.widget.pattern_entered.emit([0, 1, 2, 5])
    wizard.input_page.widget.pattern_entered.emit([0, 1, 2, 4])
    assert wizard.step == "new"
    assert "match" in wizard.status.text()
    assert log == [] and saved == []


def test_too_short_new_pin_is_rejected(qtbot):
    wizard, *_ = make(qtbot)
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("oldpass")
    wizard.choose_method("pin")
    for key in "12✓":
        wizard.input_page.widget.press(key)
    assert wizard.step == "new"
    assert "at least" in wizard.status.text()


def test_wrong_current_secret_goes_back(qtbot):
    wizard, cfg, saved, log = make(qtbot)
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("bad")
    wizard.choose_method("password")
    wizard.submit_new("newpass")
    wizard.submit_confirm("newpass")
    qtbot.waitUntil(lambda: not wizard.busy)
    assert wizard.step == "current"
    assert "Wrong code" in wizard.status.text()
    assert saved == []


def test_reset_uses_configured_method_for_current_secret(qtbot):
    wizard, cfg, saved, log = make(qtbot, first_start=False, method="pin", current="1234")
    assert wizard.step == "current"
    assert wizard.input_page.method == "pin"
    assert wizard.cancel_button.text() == "Cancel"
    wizard.submit_current("1234")
    wizard.choose_method("password")
    wizard.submit_new("correct horse")
    with qtbot.waitSignal(wizard.completed, timeout=3000):
        wizard.submit_confirm("correct horse")
    assert log == [("/dev/sdb1", "1234", "correct horse")]
    assert saved[-1]["unlock"]["method"] == "password"


def test_cancel(qtbot):
    wizard, *_ = make(qtbot, first_start=False, method="pin")
    with qtbot.waitSignal(wizard.cancelled):
        wizard.cancel_button.click()

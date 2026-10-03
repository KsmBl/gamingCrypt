import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.secret_input import PatternWidget, PinPad
from gamingcrypt.unlock.veracrypt import UnlockResult


class FakeUnlocker:
    kdf_log = []

    def __init__(self, cfg, log, current="oldpass"):
        self.cfg = cfg
        self.log = log
        self.current = current

    def create_volume(self, path, size_gb, secret, quick=True, progress=None, cancel=None):
        self.log.append(("create", path, size_gb, secret, quick, self.cfg.get("kdf")))
        if self.current != "fail-create":
            open(path, "w").close()
        if progress:
            progress(50.0)
        if self.current == "slow-create":
            cancel.wait(5)
            return UnlockResult(False, "Creation cancelled", cancelled=True)
        if self.current == "fail-create":
            return UnlockResult(False, "Not enough free disk space")
        return UnlockResult(True, "Container created")

    def change_password(self, current, new, new_kdf=None):
        self.log.append((self.cfg["volume"], current, new))
        self.kdf_log.append((self.cfg.get("kdf"), new_kdf))
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
    assert wizard.step == "source"
    wizard.existing_button.click()
    assert wizard.step == "volume"
    assert wizard._keyboard.target() is wizard.volume_edit
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
    wizard.choose_existing()
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


def test_setup_with_dot_grid(qtbot):
    from gamingcrypt.ui.secret_input import DotGridPad

    wizard, cfg, saved, log = make(qtbot)
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("oldpass")
    assert set(wizard.method_buttons) == {"pin", "password", "pattern", "grid5"}
    wizard.method_buttons["grid5"].click()
    for _ in range(2):
        pad = wizard.input_page.widget
        assert isinstance(pad, DotGridPad)
        for index in (24, 0, 0, 12):
            pad.press(index)
        if wizard.step == "new":
            pad.ok_button.click()
        else:
            with qtbot.waitSignal(wizard.completed, timeout=3000):
                pad.ok_button.click()
    assert log == [("/v.vc", "oldpass", "25-1-1-13")]
    assert saved[-1]["unlock"]["method"] == "grid5"


def test_first_start_uses_plain_current_password_and_saves_new_kdf(qtbot):
    FakeUnlocker.kdf_log.clear()
    wizard, cfg, saved, log = make(qtbot)
    wizard.new_kdf_params = lambda: {"algorithm": "scrypt", "salt": "aa" * 16, "n": 2, "r": 1, "p": 1}
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("oldpass")
    wizard.choose_method("pin")
    wizard.submit_new("1234")
    with qtbot.waitSignal(wizard.completed, timeout=3000):
        wizard.submit_confirm("1234")
    current_kdf, new_kdf = FakeUnlocker.kdf_log[-1]
    assert current_kdf is None
    assert new_kdf["salt"] == "aa" * 16
    assert saved[-1]["unlock"]["kdf"] == new_kdf


def test_reset_derives_current_with_stored_kdf_and_rotates_salt(qtbot):
    FakeUnlocker.kdf_log.clear()
    wizard, cfg, saved, log = make(qtbot, first_start=False, method="pin", current="1234")
    old = {"algorithm": "scrypt", "salt": "bb" * 16, "n": 2, "r": 1, "p": 1}
    cfg["unlock"]["kdf"] = old
    wizard.submit_current("1234")
    wizard.choose_method("pin")
    wizard.submit_new("9876")
    with qtbot.waitSignal(wizard.completed, timeout=3000):
        wizard.submit_confirm("9876")
    current_kdf, new_kdf = FakeUnlocker.kdf_log[-1]
    assert current_kdf == old
    assert new_kdf["salt"] != old["salt"]
    assert saved[-1]["unlock"]["kdf"] == new_kdf


def test_failed_change_keeps_old_kdf(qtbot):
    wizard, cfg, saved, log = make(qtbot, first_start=False, method="pin", current="1234")
    old = {"algorithm": "scrypt", "salt": "cc" * 16, "n": 2, "r": 1, "p": 1}
    cfg["unlock"]["kdf"] = old
    wizard.submit_current("0000")
    wizard.choose_method("pin")
    wizard.submit_new("9876")
    wizard.submit_confirm("9876")
    qtbot.waitUntil(lambda: not wizard.busy)
    assert cfg["unlock"]["kdf"] == old and saved == []


# --- create a new container ----------------------------------------------------

from gamingcrypt.ui.auth_setup import validate_new_container  # noqa: E402

PLENTY = lambda d: 10**15  # noqa: E731


def test_validate_new_container(tmp_path):
    (tmp_path / "taken.vc").write_text("")
    assert validate_new_container("", "64", PLENTY)[0]
    assert "exists" in validate_new_container(str(tmp_path / "taken.vc"), "64", PLENTY)[0]
    assert "does not exist" in validate_new_container(str(tmp_path / "no" / "x.vc"), "64", PLENTY)[0]
    assert "whole number" in validate_new_container(str(tmp_path / "x.vc"), "lots", PLENTY)[0]
    assert "at least" in validate_new_container(str(tmp_path / "x.vc"), "0", PLENTY)[0]
    assert "free space" in validate_new_container(str(tmp_path / "x.vc"), "64", lambda d: 10 * 1024**3)[0]
    assert validate_new_container(str(tmp_path / "x.vc"), " 64 ", PLENTY) == (None, str(tmp_path / "x.vc"), 64)


def test_create_container_flow(qtbot, tmp_path):
    wizard, cfg, saved, log = make(qtbot)
    params = {"algorithm": "scrypt", "salt": "dd" * 16, "n": 2, "r": 1, "p": 1}
    wizard.new_kdf_params = lambda: params
    wizard.create_button.click()
    assert wizard.step == "create"
    assert wizard.path_edit.text().endswith("GamingCrypt.vc")
    assert wizard._keyboard.target() is wizard.path_edit
    wizard.submit_create(str(tmp_path / "games.vc"), "32", str(tmp_path / "Games"), quick=False, free_bytes=PLENTY)
    # a new container has no current password -> straight to the method choice
    assert wizard.step == "method"
    wizard.choose_method("grid5")
    wizard.submit_new("1-2-3-4")
    wizard.submit_confirm("1-2-3-4")
    qtbot.waitUntil(lambda: wizard.step == "done")
    assert log == [("create", str(tmp_path / "games.vc"), 32, "1-2-3-4", False, params)]
    assert "Steam" in wizard.done_label.text() and str(tmp_path / "Games") in wizard.done_label.text()
    unlock = saved[-1]["unlock"]
    assert unlock["volume"] == str(tmp_path / "games.vc")
    assert unlock["mount_point"] == str(tmp_path / "Games")
    assert unlock["method"] == "grid5" and unlock["kdf"] == params
    with qtbot.waitSignal(wizard.completed):
        wizard.done_page.findChildren(type(wizard.cancel_button))[0].click()


def test_create_shows_progress(qtbot, tmp_path):
    wizard, *_ = make(qtbot)
    wizard.busy = True
    wizard._show_progress(42.4)
    assert wizard.progress_label.text() == "42%"


def test_create_failure_returns_to_form(qtbot, tmp_path):
    wizard, cfg, saved, log = make(qtbot, current="fail-create")
    wizard.choose_create()
    wizard.submit_create(str(tmp_path / "g.vc"), "8", "", free_bytes=PLENTY)
    wizard.choose_method("pin")
    wizard.submit_new("1234")
    wizard.submit_confirm("1234")
    qtbot.waitUntil(lambda: not wizard.busy)
    assert wizard.step == "create"
    assert "free disk space" in wizard.status.text()
    assert saved == [] and wizard.cancel_button.isEnabled()


def test_create_form_validation_error(qtbot, tmp_path):
    wizard, *_ = make(qtbot)
    wizard.choose_create()
    wizard.size_edit.setText("abc")
    wizard.path_edit.setText(str(tmp_path / "g.vc"))
    wizard._keyboard.submitted.emit()
    assert wizard.step == "create" and "whole number" in wizard.status.text()


def test_back_from_create_to_source(qtbot):
    wizard, *_ = make(qtbot)
    wizard.choose_create()
    wizard.show_volume_step()
    assert wizard.step == "source" and not wizard.creating


def start_create(qtbot, wizard, tmp_path):
    wizard.choose_create()
    wizard.submit_create(str(tmp_path / "g.vc"), "8", "", free_bytes=PLENTY)
    wizard.choose_method("pin")
    wizard.submit_new("1234")
    wizard.submit_confirm("1234")


def test_no_continue_while_creating_only_cancel(qtbot, tmp_path):
    wizard, cfg, saved, log = make(qtbot, current="slow-create")
    wizard.show()
    start_create(qtbot, wizard, tmp_path)
    assert wizard.step == "creating"
    assert wizard.stack.currentWidget() is wizard.creating_page
    assert wizard.next_button.isHidden() and wizard.back_button.isHidden()
    assert wizard.done_page.isHidden()  # no Continue reachable
    assert wizard.cancel_button.text() == "Cancel creation" and wizard.cancel_button.isEnabled()
    qtbot.waitUntil(lambda: wizard.progress_label.text() == "50%")
    cancelled = []
    wizard.cancelled.connect(lambda: cancelled.append(1))
    wizard.cancel_button.click()
    assert "Cancelling" in wizard.status.text() and not wizard.cancel_button.isEnabled()
    qtbot.waitUntil(lambda: not wizard.busy, timeout=6000)
    # back on the form, setup not left, nothing saved
    assert wizard.step == "create"
    assert "cancelled" in wizard.status.text()
    assert wizard.cancel_button.text() == "Skip setup" and wizard.cancel_button.isEnabled()
    assert cancelled == [] and saved == []


def test_continue_only_after_creation_finished(qtbot, tmp_path):
    wizard, cfg, saved, log = make(qtbot)
    wizard.show()
    start_create(qtbot, wizard, tmp_path)
    qtbot.waitUntil(lambda: wizard.step == "done")
    assert wizard.cancel_button.isHidden()
    assert wizard.stack.currentWidget() is wizard.done_page


# --- existing containers ---------------------------------------------------------

import json  # noqa: E402

from gamingcrypt.unlock import sidecar  # noqa: E402


def test_create_writes_sidecar(qtbot, tmp_path):
    wizard, cfg, saved, log = make(qtbot)
    params = {"algorithm": "scrypt", "salt": "ee" * 16, "n": 2, "r": 1, "p": 1}
    wizard.new_kdf_params = lambda: params
    start_create(qtbot, wizard, tmp_path)
    qtbot.waitUntil(lambda: wizard.step == "done")
    data = json.loads(sidecar.sidecar_path(str(tmp_path / "g.vc")).read_text())
    assert data["method"] == "pin" and data["kdf"] == params


def test_existing_default_container_hides_create_and_asks_for_password(qtbot, isolated_home):
    (isolated_home / "GamingCrypt.vc").write_text("")
    wizard, *_ = make(qtbot)
    assert wizard.step == "current"
    assert str(isolated_home / "GamingCrypt.vc") in wizard.hint.text()
    assert wizard.volume == str(isolated_home / "GamingCrypt.vc")
    assert not wizard.create_button.isVisibleTo(wizard)
    wizard.show_volume_step()  # even on the choice page, creating isn't offered
    assert not wizard.create_button.isVisibleTo(wizard) and "existing container" in wizard.hint.text()


def test_reset_rekey_updates_sidecar(qtbot, tmp_path):
    volume = tmp_path / "v.vc"
    volume.write_text("")
    wizard, cfg, saved, log = make(qtbot, first_start=False, method="pin", current="1234")
    cfg["unlock"]["volume"] = wizard.volume = str(volume)
    wizard.submit_current("1234")
    wizard.choose_method("password")
    wizard.submit_new("abc")
    with qtbot.waitSignal(wizard.completed, timeout=3000):
        wizard.submit_confirm("abc")
    assert sidecar.read_sidecar(str(volume))["method"] == "password"


def test_closing_window_during_creation_cancels_it(qtbot, tmp_path):
    from gamingcrypt.app import MainWindow

    cfg = copy.deepcopy(DEFAULTS)
    log = []
    window = MainWindow(cfg, lambda c: None, lambda ucfg: FakeUnlocker(ucfg, log, "slow-create"))
    qtbot.addWidget(window)
    wizard = window.stack.currentWidget()
    wizard.new_kdf_params = lambda: None
    start_create(qtbot, wizard, tmp_path)
    assert wizard.step == "creating"
    window.close()
    assert wizard._cancel_event.is_set()
    qtbot.waitUntil(lambda: not wizard.busy, timeout=6000)

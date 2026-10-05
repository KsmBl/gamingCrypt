"""Gaming mode: the power button puts the device to sleep; after waking up the power
limit is applied again and - if wanted - the code is asked for again."""

import copy
import stat
import subprocess
import time

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.system import sleep
from gamingcrypt.unlock import verifier


# --- system side ------------------------------------------------------------------------

def test_sleep_clock_counts_only_real_sleep():
    offsets = [100.0, 100.5, 160.5, 160.6]
    clock = sleep.SleepClock(offset=lambda: offsets.pop(0))
    assert clock.slept() == 0.0  # timer jitter
    assert clock.slept() == 60.0  # boottime ran 60 s ahead of monotonic: asleep
    assert clock.slept() == 0.0


def test_real_clocks_awake():
    clock = sleep.SleepClock()
    time.sleep(0.01)
    assert clock.slept() == 0.0


def test_power_key_inhibitor_dies_with_gamingcrypt():
    seen = {}

    def popen(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return "proc"

    assert sleep.inhibit_power_key(popen) == "proc"
    assert seen["cmd"][:3] == ["systemd-inhibit", "--what=handle-power-key", "--mode=block"]
    assert seen["preexec_fn"] is sleep._die_with_parent  # no dead power button after a crash
    assert sleep.inhibit_power_key(lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())) is None


def test_suspend_command():
    calls = []
    ok = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    assert sleep.suspend(ok) == (True, "Going to sleep…") and calls == [["systemctl", "suspend"]]
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Access denied")  # noqa: E731
    assert sleep.suspend(bad) == (False, "Access denied")


def test_reader_reports_power_button_once():
    from gamingcrypt.input.volume_keys import VolumeKeys
    from tests.test_volume_keys import FakeDevice

    device = FakeDevice([[(e.EV_KEY, e.KEY_POWER, 1), (e.EV_KEY, e.KEY_POWER, 0)]])
    got = []
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/x", "Power Button")], open_device=lambda p: device)
    keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and not got:
        time.sleep(0.01)
    keys.stop()
    assert got == [e.KEY_POWER]


def test_power_button_devices_get_read_access(monkeypatch, capsys):
    """install.sh's udev rule comes from this list - power buttons included, names once."""
    from gamingcrypt import app

    monkeypatch.setattr(e, "list_devices", lambda *a: [
        e.DeviceInfo("/dev/input/event1", "Power Button", keys={e.KEY_POWER}),
        e.DeviceInfo("/dev/input/event2", "Power Button", keys={e.KEY_POWER}),
        e.DeviceInfo("/dev/input/event3", "AT Translated Set 2 keyboard", keys={e.KEY_VOLUMEUP, 30})])
    assert app.main(["--volume-key-devices"]) == 0
    assert capsys.readouterr().out.splitlines() == ["Power Button", "AT Translated Set 2 keyboard"]


# --- code check after sleep -------------------------------------------------------------

def test_verifier_checks_without_storing_the_code(tmp_path):
    v = verifier.make("1234")
    assert verifier.check(v, "1234") and not verifier.check(v, "1235")
    assert "1234" not in str(v)
    path = tmp_path / "run" / "verifier"
    verifier.save(v, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert verifier.load(path) == v and verifier.load(tmp_path / "missing") is None
    assert not verifier.check({"key": "zz"}, "1234")
    assert verifier.VerifyUnlocker(v).unlock("1234").success
    assert verifier.VerifyUnlocker(v).unlock("0000").message == "Wrong code"


# --- the window -------------------------------------------------------------------------

class Power:
    can_set = True

    def __init__(self):
        self.sets = []

    def read(self):
        from gamingcrypt.system.power import PowerLimit

        return PowerLimit(15, 5, 28, "test")

    def set(self, watts):
        self.sets.append(watts)
        return True, f"{watts} W"


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system.controls import SystemControls
    from tests.test_shell import FakeUnlocker

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    from gamingcrypt.system import gamescope_ctl as gs

    monkeypatch.setattr(gs, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gs, "set_window_appid", lambda wid: True)
    cfg = copy.deepcopy(DEFAULTS)
    volume = tmp_path / "games.vc"
    volume.write_text("")
    cfg["unlock"].update(method="pin", volume=str(volume))
    cfg["system"]["power_limit_w"] = 12
    system = SystemControls()
    system.power = Power()
    w = MainWindow(cfg, lambda c: None, FakeUnlocker, system=system)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    suspends = []
    monkeypatch.setattr(sleep, "suspend", lambda: suspends.append(1) or (True, ""))
    w._suspends = suspends
    return w


def unlock(qtbot, w, code="1234"):
    lock = w.stack.currentWidget()
    for key in code + "✓":
        lock.input.widget.press(key)
    qtbot.waitUntil(lambda: w.screen_name == "shell")


def test_power_button_sleeps_but_the_wake_press_does_not(qtbot, window):
    window.power_button()
    qtbot.waitUntil(lambda: window._suspends == [1])
    window.sleep_clock.offset = lambda: window.sleep_clock.last + 120  # ... asleep for 2 min
    window.power_button()  # the press that woke it up
    qtbot.wait(50)
    assert window._suspends == [1]
    qtbot.waitUntil(lambda: window.system.power.sets == [12])  # power limit back after waking


def test_power_menu_sleep(qtbot, window):
    unlock(qtbot, window)
    window.shell.open_power_menu()
    window.shell.power_menu.sleep_button.click()
    qtbot.waitUntil(lambda: window._suspends == [1])
    assert not window.shell.power_menu.isVisible()


def test_lock_after_sleep_asks_for_the_code_again(qtbot, window):
    unlock(qtbot, window)
    assert window.verifier is not None and window.verifier_path.exists()
    window.woke_up(600)
    assert window.sleep_lock is None  # "Never" is the default
    window.config["system"]["lock_after_sleep_min"] = 5
    window.woke_up(120)
    assert window.sleep_lock is None  # slept only 2 minutes
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    asides = []
    window.step_aside = lambda front="steam": asides.append(front)
    window.woke_up(400)
    lock = window.sleep_lock
    assert lock is not None and lock.isVisible() and window.nav_root() is lock
    for key in "0000✓":
        lock.input.widget.press(key)
    qtbot.waitUntil(lambda: "Wrong code" in lock.status.text())
    assert window.sleep_lock is lock
    for key in "1234✓":
        lock.input.widget.press(key)
    qtbot.waitUntil(lambda: window.sleep_lock is None)
    assert asides == ["game"] and window.screen_name == "shell"  # straight back into the game
    window.game_watcher._stop()


def test_per_game_power_limit_wins_after_waking(qtbot, window):
    window.game_profiles.set(620, "power_w", 8)
    window.game_watcher.appid = 620
    window.woke_up(30)
    qtbot.waitUntil(lambda: window.system.power.sets == [8])
    window.game_watcher._stop()


def test_lock_after_sleep_setting(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab
    from tests.test_shell import FakeUnlocker, configured

    saved = []
    tab = SettingsTab(configured(), saved.append, FakeUnlocker)
    qtbot.addWidget(tab)
    assert tab.sleep_lock.currentText() == "Never"
    tab.sleep_lock.setCurrentIndex(tab.sleep_lock.findData(15))
    assert saved[-1]["system"]["lock_after_sleep_min"] == 15
    tab.sleep_lock.setCurrentIndex(tab.sleep_lock.findData(0))
    assert saved[-1]["system"]["lock_after_sleep_min"] == 0  # "Right away" is not "Never"
    del DEFAULTS

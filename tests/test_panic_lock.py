"""Lock now: game closed, Steam closed, drive unmounted, lock screen - by menu or by
holding the Windows button and pressing Volume Down."""

import copy
import subprocess
import time

import pytest

from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.input import evdev as e
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker


def test_helper_allows_dismount_only_as_its_own_operation():
    assert helper.validate(["--text", "--non-interactive", "-d", "/home/u/games.vc"], "/home/u") is None
    assert helper.validate(["--text", "--non-interactive", "--force", "-d", "/home/u/games.vc"], "/home/u") is None
    assert "--force only" in helper.validate(["--force", "--fs-options=nosuid,nodev", "--mount", "/v", "/mnt/x"],
                                             "/home/u")
    assert helper.validate(["-d", "/v", "/mnt/extra"], "/home/u") is not None  # only the volume


def test_dismount_tries_normal_then_forced(tmp_path):
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        busy = "--force" not in cmd
        return subprocess.CompletedProcess(cmd, 1 if busy else 0, "", "Error: device busy" if busy else "")

    unlocker = VeraCryptUnlocker(volume="/home/u/games.vc", use_sudo=False, runner=runner)
    assert unlocker.dismount().success
    assert calls[0][-2:] == ["-d", "/home/u/games.vc"] and "--force" in calls[1]
    never = VeraCryptUnlocker(volume="/v", use_sudo=False,
                              runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Error: no"))
    assert not never.dismount().success


def test_reader_reports_the_combo_only_while_windows_is_held():
    from gamingcrypt.input.volume_keys import VolumeKeys
    from tests.test_volume_keys import FakeDevice

    device = FakeDevice([
        [(e.EV_KEY, e.KEY_LEFTMETA, 1)],
        [(e.EV_KEY, e.KEY_VOLUMEDOWN, 1)],   # held Windows + Volume Down: lock
        [(e.EV_KEY, e.KEY_VOLUMEDOWN, 0)],
        [(e.EV_KEY, e.KEY_LEFTMETA, 0)],
        [(e.EV_KEY, e.KEY_VOLUMEDOWN, 1)],   # Windows released: just quieter
    ])
    got = []
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/x", "kbd")], open_device=lambda p: device)
    keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(got) < 3:
        time.sleep(0.01)
    keys.stop()
    assert got == [e.KEY_LEFTMETA, e.PANIC_COMBO, e.KEY_VOLUMEDOWN]


class Unlocker:
    configured = True
    dismounted = []

    def __init__(self, cfg=None):
        pass

    def unlock(self, secret):
        return UnlockResult(secret == "1234", "")

    def is_mounted(self):
        return True

    def dismount(self):
        Unlocker.dismounted.append(1)
        return UnlockResult(True, "Drive locked")


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.steam import library_setup, running
    from gamingcrypt.system import gamescope_ctl

    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda wid: True)
    quit_apps, closed = [], []
    monkeypatch.setattr(running, "running_appids", lambda: {620})
    monkeypatch.setattr(running, "force_quit", lambda appid, **kw: quit_apps.append(appid))
    monkeypatch.setattr(library_setup, "close_steam", lambda client, **kw: closed.append(1) or True)
    cfg = copy.deepcopy(DEFAULTS)
    volume = tmp_path / "games.vc"
    volume.write_text("")
    cfg["unlock"].update(method="pin", volume=str(volume))
    Unlocker.dismounted = []
    w = MainWindow(cfg, lambda c: None, Unlocker)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    lock = w.stack.currentWidget()
    for key in "1234✓":
        lock.input.widget.press(key)
    qtbot.waitUntil(lambda: w.screen_name == "shell")
    w._quit, w._closed = quit_apps, closed
    return w


def test_lock_now_from_the_power_menu(qtbot, window):
    window.shell.open_power_menu()
    window.shell.power_menu.lock_button.click()
    assert window.screen_name == "lock"  # right away, before the drive is even unmounted
    lock = window.stack.currentWidget()
    qtbot.waitUntil(lambda: lock.status.text() == "Locked")
    assert window._quit == [620] and Unlocker.dismounted == [1]


def test_lock_now_from_the_combo_and_quick_menu(qtbot, window):
    window.hardware_key(e.PANIC_COMBO)
    qtbot.waitUntil(lambda: Unlocker.dismounted == [1])
    assert window.screen_name == "lock"
    window.hardware_key(e.PANIC_COMBO)  # already locked: nothing happens
    qtbot.wait(50)
    assert Unlocker.dismounted == [1]


def test_quick_menu_lock_button(qtbot, window):
    window.toggle_quick_menu()
    window.quick_menu.lock_button.click()
    qtbot.waitUntil(lambda: Unlocker.dismounted == [1])
    assert window.screen_name == "lock" and not window.quick_menu.isVisible()

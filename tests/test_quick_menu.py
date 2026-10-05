import copy
import signal
import subprocess
import time

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.system import gamescope_ctl
from gamingcrypt.system.audio import Device
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui import quick_menu as qm
from gamingcrypt.ui.quick_menu import QuickMenu


def test_gamescope_dynamic_refresh_commands():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        out = "GAMESCOPE_DYNAMIC_REFRESH(CARDINAL) = 50\n" if cmd[-1] == "GAMESCOPE_DYNAMIC_REFRESH" else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")

    assert gamescope_ctl.dynamic_refresh(run) == 50
    assert gamescope_ctl.set_dynamic_refresh(45, run)
    assert calls[-1] == ["xprop", "-root", "-f", "GAMESCOPE_DYNAMIC_REFRESH", "32c", "-set",
                         "GAMESCOPE_DYNAMIC_REFRESH", "45"]
    assert gamescope_ctl.set_dynamic_refresh(0, run)
    assert calls[-1] == ["xprop", "-root", "-remove", "GAMESCOPE_DYNAMIC_REFRESH"]
    unset = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "GAMESCOPE_DYNAMIC_REFRESH:  not found.\n", "")  # noqa
    assert gamescope_ctl.dynamic_refresh(unset) == 0


def test_force_quit_terminates_then_kills(tmp_path):
    from gamingcrypt.steam import running
    from tests.test_launch_phase import proc_tree

    proc = proc_tree(tmp_path, {1: (0, "steam", ["steam"]),
                                10: (1, "reaper", ["reaper", "SteamLaunch", "AppId=42"]),
                                11: (10, "Game.exe", ["Game.exe"]),
                                12: (11, "stubborn", ["stubborn"])})
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGTERM and pid != 12:
            import shutil
            shutil.rmtree(proc / str(pid))  # these exit politely

    assert running.force_quit(42, proc, kill=kill, sleep=lambda s: None, grace_s=1) == 3
    assert {(p, s) for p, s in sent if s == signal.SIGTERM} == {(10, signal.SIGTERM), (11, signal.SIGTERM),
                                                                (12, signal.SIGTERM)}
    assert (12, signal.SIGKILL) in sent and (10, signal.SIGKILL) not in sent  # only the stubborn one
    assert 1 not in [p for p, _ in sent]  # Steam itself is never touched


def test_real_force_quit():
    from gamingcrypt.steam.running import force_quit, game_processes

    game = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 30; true", "SteamLaunch", "AppId=909090"])
    try:
        deadline = time.time() + 3
        while time.time() < deadline and len(game_processes(909090)) < 2:
            time.sleep(0.05)
        assert force_quit(909090, grace_s=0.5) >= 2  # sh ignores TERM -> gets killed
        game.wait(timeout=3)
        deadline = time.time() + 3
        while time.time() < deadline and game_processes(909090):
            time.sleep(0.05)
        assert game_processes(909090) == set()
    finally:
        if game.poll() is None:
            game.kill()


def test_reader_reports_windows_button_once_per_press():
    from gamingcrypt.input.volume_keys import VolumeKeys
    from tests.test_volume_keys import FakeDevice

    device = FakeDevice([[(e.EV_KEY, e.KEY_LEFTMETA, 1), (e.EV_KEY, e.KEY_LEFTMETA, 2),
                          (e.EV_KEY, e.KEY_LEFTMETA, 0)], [(e.EV_KEY, e.KEY_RIGHTMETA, 1)]])
    got = []
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/x", "Buttons")], open_device=lambda p: device)
    keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(got) < 2:
        time.sleep(0.01)
    keys.stop()
    assert got == [e.KEY_LEFTMETA, e.KEY_RIGHTMETA]


# --- menu ----------------------------------------------------------------------------------

class Audio:
    def __init__(self):
        self.defaults = {"output": "speakers", "input": "mic"}
        self.calls = []

    def devices(self, kind):
        names = {"output": [("speakers", "Speakers", 40), ("hdmi", "HDMI", 80)], "input": [("mic", "Mic", 100)]}
        return [Device(n, d, v, False, n == self.defaults[kind]) for n, d, v in names[kind]]

    def set_default(self, kind, name):
        self.calls.append(("default", kind, name))
        return True

    def set_volume(self, kind, name, percent):
        self.calls.append(("volume", name, percent))
        return True


class Brightness:
    def __init__(self):
        self.values = []

    def get(self):
        return 70

    def set(self, p):
        self.values.append(p)
        return True


@pytest.fixture
def menu(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    monkeypatch.setattr(qm, "KEEP_SECONDS", 2)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1280, 800)
    host.show()
    refresh = {"hz": 0, "sets": []}
    audio, brightness = Audio(), Brightness()
    m = QuickMenu(host, SystemControls(audio=audio, brightness=brightness),
                  refresh_get=lambda: refresh["hz"],
                  refresh_set=lambda hz: refresh["sets"].append(hz) or refresh.update(hz=hz) or True)
    m._test_host = host  # keep the parent window alive for the whole test
    return m, audio, brightness, refresh


def test_menu_shows_current_values(menu):
    m, audio, brightness, refresh = menu
    m.open_menu(620, "Portal 2")
    assert m.isVisible() and m.title.text() == "Portal 2" and not m.quit_button.isHidden()
    assert m.output.currentText() == "Speakers" and m.input.currentText() == "Mic"
    assert m.volume.value() == 40 and m.brightness.value() == 70 and m.refresh.currentText() == "Default"
    assert audio.calls == [] and brightness.values == []  # opening changes nothing
    assert m.parentWidget().focusWidget() is m.back_button


def test_menu_without_game_has_no_force_quit(menu):
    m, *_ = menu
    m.open_menu(None)
    assert m.quit_button.isHidden() and m.back_button.text() == "▶  Back"


def test_menu_changes(menu):
    m, audio, brightness, refresh = menu
    m.open_menu(620, "Portal 2")
    m.output.setCurrentIndex(m.output.findData("hdmi"))
    m.volume.setValue(55)
    m.brightness.setValue(30)
    assert ("default", "output", "hdmi") in audio.calls and ("volume", "hdmi", 55) in audio.calls
    assert brightness.values == [30]


def test_refresh_reverts_by_itself(qtbot, menu):
    m, audio, brightness, refresh = menu
    m.open_menu(620)
    m.refresh.setCurrentIndex(m.refresh.findData(40))
    assert refresh["hz"] == 40 and not m.confirm.isHidden()
    qtbot.waitUntil(lambda: refresh["hz"] == 0, timeout=4000)  # nobody pressed Keep
    assert m.confirm.isHidden() and m.refresh.currentText() == "Default"


def test_refresh_keep_and_leaving_unconfirmed(qtbot, menu):
    m, audio, brightness, refresh = menu
    m.open_menu(620)
    m.refresh.setCurrentIndex(m.refresh.findData(50))
    m.keep_button.click()
    assert refresh["hz"] == 50 and "50 Hz" in m.status.text()
    m.refresh.setCurrentIndex(m.refresh.findData(40))
    m.close_menu()  # leaving with an unconfirmed rate -> back to the kept one
    assert refresh["hz"] == 50


def test_force_quit_needs_two_taps(qtbot, menu):
    m, *_ = menu
    m.open_menu(620, "Portal 2")
    quit_ = []
    m.force_quit.connect(quit_.append)
    m.quit_button.click()
    assert quit_ == [] and "again" in m.quit_button.text()
    m.quit_button.click()
    assert quit_ == [620] and "Quitting" in m.status.text()


def test_back_closes(menu):
    m, *_ = menu
    closed = []
    m.closed.connect(lambda: closed.append(1))
    m.open_menu(620)
    assert m.gamepad_back() and closed == [1] and not m.isVisible()


# --- main window ---------------------------------------------------------------------------

def test_windows_button_mid_game(qtbot, monkeypatch):
    from tests.test_game_running import Clock, Game, make_window

    window, service, calls = make_window(qtbot, monkeypatch)
    window.system = SystemControls(audio=Audio(), brightness=Brightness())
    game, clock = Game(), Clock()
    w = window.game_watcher
    window.game_launched(620)
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    game.pids, game.drawing = {1}, True
    w.poll()
    clock.now += 2
    w.poll()
    assert w.phase == "playing" and calls == ["aside"]
    monkeypatch.setattr(window, "isVisible", lambda: False)  # hidden: the game is in front
    window.hardware_key(e.KEY_LEFTMETA)
    assert calls == ["aside", "back"]  # GamingCrypt came to the front ...
    menu = window.quick_menu
    assert menu.title.text() == "Portal 2" and not menu.quit_button.isHidden()
    assert window.nav_root() is menu
    quit_ = []
    monkeypatch.setattr("gamingcrypt.steam.running.force_quit", lambda appid: quit_.append(appid))
    menu.quit_button.click()
    menu.quit_button.click()
    qtbot.waitUntil(lambda: quit_ == [620])
    window.hardware_key(e.KEY_LEFTMETA)  # Windows button again: back to the game
    assert calls == ["aside", "back", "aside"] and not menu.isVisible()


def test_menu_closes_when_the_game_ends(qtbot, monkeypatch):
    from tests.test_game_running import make_window

    window, service, calls = make_window(qtbot, monkeypatch)
    window.system = SystemControls(audio=Audio(), brightness=Brightness())
    window.toggle_quick_menu()
    assert window.quick_menu.isVisible() and window.quick_menu.quit_button.isHidden()  # no game
    window.game_over(620)
    assert not window.quick_menu.isVisible()


def test_tap_outside_closes_and_long_names_fit(qtbot, menu):
    from PySide6.QtCore import QPoint, Qt

    m, audio, *_ = menu
    audio.devices = lambda kind: [Device("x", "Family 17h/19h HD Audio Controller Speaker + Headphones",
                                         40, False, True)]
    m.open_menu(620, "ROUNDS")
    qtbot.waitUntil(m.isVisible)
    card = m.box.parentWidget()
    assert card.minimumSizeHint().width() <= m.panel.viewport().width()  # nothing cut off on the right
    closed = []
    m.closed.connect(lambda: closed.append(1))
    qtbot.mouseClick(m, Qt.MouseButton.LeftButton, pos=m.panel.geometry().center())
    assert m.isVisible() and closed == []  # inside the panel: stays
    qtbot.mouseClick(m, Qt.MouseButton.LeftButton, pos=QPoint(50, 400))
    assert not m.isVisible() and closed == [1]


def test_battery_in_menu_refreshes_while_open(qtbot, menu):
    from gamingcrypt.system.battery import BatteryState

    m, *_ = menu
    states = [BatteryState(64, False, False)]
    m.battery_reader = lambda: states[-1]
    m.open_menu()
    assert m.battery_row.isVisible() and m.battery.text() == "🔋 64%  ·  On battery"
    states.append(BatteryState(65, True, True))
    qtbot.waitUntil(lambda: m.battery.text() == "⚡ 65%  ·  Charging", timeout=2500)
    assert m.battery.property("charging") is True
    m.close_menu()
    assert not m.battery_timer.isActive()
    m.battery_reader = lambda: None  # no battery (desktop PC): no row
    m.open_menu()
    assert not m.battery_row.isVisible()
    m.hide()
    assert not m.battery_timer.isActive()


def test_top_bar_battery_refreshes_every_second():
    from gamingcrypt.ui import shell

    assert shell.BATTERY_REFRESH_MS == 1000

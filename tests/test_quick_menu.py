import copy
import signal
import subprocess
import time

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.input import hotkeys
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


def test_refresh_rate_goes_through_gamescopes_control_protocol():
    """gamescope overwrites what the properties say on every frame - by them alone the screen's
    rate never changed. Its one number is for the refresh rate and the FPS limit together."""
    props, calls = {}, []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "xprop":
            if "-set" in cmd:
                props[cmd[-2]] = cmd[-1]
            elif "-remove" in cmd:
                props.pop(cmd[-1], None)
            else:
                value = props.get(cmd[-1])
                return subprocess.CompletedProcess(cmd, 0, f"{cmd[-1]}(CARDINAL) = {value}\n" if value else "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ctl = lambda: [c[-1] for c in calls if c[0] == "gamescopectl"]  # noqa: E731
    assert gamescope_ctl.set_dynamic_refresh(50, run)
    assert calls[0][0] == "xprop" and ["gamescopectl", "debug_set_fps_limit", "50"] in calls
    assert gamescope_ctl.dynamic_refresh(run) == 50  # remembered
    assert gamescope_ctl.set_fps_limit(30, run) and ctl() == ["50", "30"]  # the limit wins
    assert gamescope_ctl.set_dynamic_refresh(40, run) and ctl()[-1] == "30"  # ... also over a new rate
    assert gamescope_ctl.set_fps_limit(0, run) and ctl()[-1] == "40"  # no limit: the rate again
    assert gamescope_ctl.set_dynamic_refresh(0, run) and ctl()[-1] == "0" and props == {}

    def no_gamescopectl(cmd, **kw):
        if cmd[0] == "gamescopectl":
            raise FileNotFoundError(cmd[0])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert gamescope_ctl.set_dynamic_refresh(45, no_gamescopectl)  # an older gamescope: the property


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
                          (e.EV_KEY, e.KEY_LEFTMETA, 0)], [(e.EV_KEY, e.KEY_RIGHTMETA, 1), (e.EV_KEY, e.KEY_RIGHTMETA, 0)]])
    got = []
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/x", "Buttons")], open_device=lambda p: device)
    keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(got) < 2:
        time.sleep(0.01)
    keys.stop()
    assert got == [hotkeys.ACTION_CODES["quick_menu"]] * 2  # either Windows key, once per press (when let go)


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


def test_the_volume_slider_follows_the_output(menu):
    """Speakers at 40 %, HDMI at 80 %: switched to HDMI, the slider shows HDMI's 80 % - it kept
    showing 40 %, and the first touch set HDMI to about that."""
    m, audio, *_ = menu
    m.open_menu(620, "Portal 2")
    assert m.volume.value() == 40
    m.output.setCurrentIndex(m.output.findData("hdmi"))
    assert m.volume.value() == 80 and m.volume_value.text() == "80%"
    assert not any(call[0] == "volume" for call in audio.calls)  # shown, nothing set


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


def test_force_quit_asks_first(qtbot, menu):
    from gamingcrypt.ui.modal import open_modal

    m, *_ = menu
    m.open_menu(620, "Portal 2")
    quit_ = []
    m.force_quit.connect(quit_.append)
    m.quit_button.click()
    question = open_modal(m, on_screen=False)
    assert quit_ == [] and "Force quit Portal 2?" in question.content.question.text()
    question.content.action_button.click()
    assert quit_ == [620] and "Quitting" in m.status.text() and open_modal(m, on_screen=False) is None


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
    window.hardware_key(hotkeys.ACTION_CODES["quick_menu"])  # Windows button (see input/hotkeys)
    assert calls == ["aside", "back"]  # GamingCrypt came to the front ...
    menu = window.quick_menu
    assert menu.title.text() == "Portal 2" and not menu.quit_button.isHidden()
    assert window.nav_root() is menu
    quit_ = []
    monkeypatch.setattr("gamingcrypt.steam.running.force_quit", lambda appid: quit_.append(appid))
    from gamingcrypt.ui.modal import open_modal

    menu.quit_button.click()
    open_modal(window, on_screen=False).content.action_button.click()
    qtbot.waitUntil(lambda: quit_ == [620])
    assert w.quitting  # gone = over, without the wait for a game that restarts itself
    window.hardware_key(hotkeys.ACTION_CODES["quick_menu"])  # Windows button again: back to the game
    assert calls == ["aside", "back", "aside"] and not menu.isVisible()


def test_force_quit_ends_the_game_right_away(qtbot, monkeypatch):
    """The watcher is asked as soon as the processes are gone - not at its next look, plus a wait."""
    from tests.test_game_running import Clock, Game, make_window

    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    window.game_launched(620)
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    game.pids, game.drawing = {1}, True
    w.poll()
    clock.now += 2
    w.poll()
    w.timer.stop()  # no look by itself in this test
    over = []
    w.finished.connect(over.append)
    monkeypatch.setattr("gamingcrypt.steam.running.force_quit", lambda appid: game.pids.clear())
    window._force_quit(620)
    qtbot.waitUntil(lambda: over == [620])
    assert clock.now == 2 and not w.active  # no time passed


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


def test_emulator_row_fits_the_panel(menu):
    """Save / Load state next to each other, Controls below - three buttons don't fit in one line."""
    m, *_ = menu
    m.set_emulated(True)
    m.open_menu(0x70000001, "Super Mario World")
    m._test_host.grab()  # layout done
    panel = m.panel.viewport().rect()
    for button in (m.save_state_button, m.load_state_button, m.controls_button):
        r = button.rect().translated(button.mapTo(m.panel.viewport(), button.rect().topLeft()))
        assert panel.left() <= r.left() and r.right() <= panel.right(), button.text()
        assert button.width() >= button.sizeHint().width(), button.text()  # the text isn't cut
    y = lambda w: w.mapTo(m, w.rect().topLeft()).y()  # noqa: E731
    assert y(m.controls_button) > y(m.save_state_button) and y(m.save_state_button) == y(m.load_state_button)


def test_everything_fits_without_scrolling(menu):
    """1280 x 800 with an emulated game on several discs and a long name: no scrolling, all reachable by touch."""
    from PySide6.QtWidgets import QScroller

    m, *_ = menu

    class Limit:
        min_w, max_w, watts = 5, 28, 15

    m.set_performance(limit=Limit(), watts=15, fps=0, overlay=False, in_game=True)
    m.set_emulated(True, 1.0)
    m.set_discs(3, 0)
    m.open_menu(0x70000001, "Final Fantasy VII - German Retranslation")
    m._test_host.grab()
    assert m.panel.verticalScrollBar().maximum() == 0
    assert not QScroller.hasScroller(m.panel.viewport())  # flick-scrolling would swallow taps
    viewport = m.panel.viewport().rect()
    for button in [m.back_button, m.speed, m.disc_next, m.lock_button, m.quit_button, m.bluetooth_button]:
        r = button.rect().translated(button.mapTo(m.panel.viewport(), button.rect().topLeft()))
        assert viewport.contains(r), button


@pytest.mark.parametrize("size", ["normal", "large", "larger"])
def test_nothing_is_cut_off_at_the_right_with_every_text_size(menu, size):
    """Real sizes (the theme), a running emulated game with every button: nothing past the panel's
    right edge, no caption cut short - and room left of the panel to tap the menu shut."""
    from PySide6.QtWidgets import QLabel, QWidget

    from gamingcrypt.ui import theme

    m, *_ = menu

    class Limit:
        min_w, max_w, watts = 5, 28, 15

    try:
        theme.apply("dark", size=size)
        m._test_host.setStyleSheet(theme.STYLESHEET)
        m.set_performance(limit=Limit(), watts=15, fps=0, overlay=False, in_game=True)
        m.set_emulated(True, 1.0)
        m.set_in_step(True)
        from gamingcrypt.emulation import retroarch

        m.set_pads(retroarch.pad_choices("wiiu"))
        m.set_discs(3, 0)
        m.open_menu(0x70000001, "The Legend of Zelda: Ocarina of Time")
        m._test_host.grab()
        viewport = m.panel.viewport().rect()
        for widget in m.panel.widget().findChildren(QWidget):
            if widget.isVisibleTo(m) and not isinstance(widget, QLabel):
                r = widget.rect().translated(widget.mapTo(m.panel.viewport(), widget.rect().topLeft()))
                assert r.right() <= viewport.right(), (size, widget, getattr(widget, "text", str)())
        for caption in m.captions:
            assert caption.width() >= caption.sizeHint().width(), (size, caption.text())
        assert m.panel.geometry().left() >= qm.TAP_ROOM
    finally:
        theme.apply("dark", size="normal")


def test_opens_at_the_top(qtbot, menu):
    m, *_ = menu
    m.open_menu(620, "Portal 2")
    bar = m.panel.verticalScrollBar()
    bar.setRange(0, 300)  # as on a small screen
    bar.setValue(300)
    m.close_menu()
    m.open_menu(620, "Portal 2")
    assert bar.value() == 0


def test_the_speed_slider(qtbot, menu):
    """One slider from 0.1x to 10x: it tells the app what's chosen (applied when the menu closes)."""
    from gamingcrypt.emulation.retroarch import SPEEDS

    m, *_ = menu
    m.set_emulated(True, 1.0)
    m.open_menu(0x70000001, "Mario")
    assert m.speed_row.isVisibleTo(m) and m.speed_value.text() == "1x"
    assert (m.speed.minimum(), m.speed.maximum()) == (0, len(SPEEDS) - 1)
    chosen = []
    m.speed_chosen.connect(chosen.append)
    for step in (1, 2, 3):
        m.speed.setValue(SPEEDS.index(1.0) + step)
    assert m.speed_value.text() == "2x" and chosen[-1] == 2.0 and m.isVisible()
    m.set_emulated(True, 3.0)  # the next time: what the app says
    assert m.speed_value.text() == "3x" and chosen[-1] == 2.0
    m.set_speed_busy(True, "Changing the speed to 4x…")
    assert not m.speed.isEnabled() and "4x" in m.status.text()
    m.set_speed_busy(False)
    assert m.speed.isEnabled() and m.status.text() == ""


def test_a_new_speed_says_the_game_starts_again(qtbot, menu):
    """The new speed is applied by starting the game again after the menu is closed - said while
    the menu is still open, not a surprise; back at the old speed: nothing to say."""
    from gamingcrypt.emulation.retroarch import SPEEDS

    m, *_ = menu
    m.set_emulated(True, 1.0)
    m.set_in_step(True, False)
    m.open_menu(0x70000001, "Mario")
    m.speed.setValue(SPEEDS.index(2.0))
    assert m.status.text() == "When you go back, the game starts again at 2x - where you are is kept"
    m.in_step_button.click()
    assert "at 2x and 60 FPS" in m.status.text()
    m.in_step_button.click()
    m.speed.setValue(SPEEDS.index(1.0))
    assert m.status.text() == ""  # as it runs: nothing changes
    m.set_emulated(True, 1.0, states=False)  # a core without save states
    m.open_menu(0x70000001, "Doom")
    m.speed.setValue(SPEEDS.index(0.5))
    assert m.status.text() == "0.5x from the next start - this game can't be saved while it runs"


def test_the_wii_u_controller_is_switched_in_the_menu(menu):
    """Wii U: each tap the next controller (Pro Controller, GamePad) - applied once the menu is
    closed; a game that can't be saved gets it from its next start, said while the menu is open."""
    from gamingcrypt.emulation import retroarch

    m, *_ = menu
    chosen = []
    m.pad_chosen.connect(chosen.append)
    m.set_emulated(True, 1.0, states=False)
    m.set_pads([])
    m.open_menu(0x70000001, "Mario")
    assert not m.pad_button.isVisibleTo(m)  # a console with one controller
    m.set_pads(retroarch.pad_choices("wiiu"))
    assert m.pad_button.isVisibleTo(m) and m.pad_button.text() == "🎮  Wii U Pro Controller"
    m.pad_button.click()
    assert chosen == ["gamepad"] and m.pad_button.text() == "🎮  Wii U GamePad"
    assert m.status.text() == "The Wii U GamePad from the next start - this game can't be saved while it runs"
    m.pad_button.click()
    assert chosen == ["gamepad", None] and m.status.text() == ""  # as it runs
    m.set_pads(retroarch.pad_choices("wiiu"), running="gamepad")
    assert m.pad_button.text() == "🎮  Wii U GamePad"
    m.set_pads(retroarch.pad_choices("wiiu"), running="gamepad", chosen=(None,))  # (chosen, not applied yet)
    assert m.pad_button.text() == "🎮  Wii U Pro Controller"
    m.set_pads(retroarch.pad_choices("wiiu"), running="gamepad")
    m.set_emulated(True, 1.0)  # one that can be saved: started again right away
    m.pad_button.click()
    assert m.status.text() == "When you go back, the game starts again with the Wii U Pro Controller - where you are is kept"


def test_state_and_bluetooth_buttons_ask_for_their_pages(menu):
    m, *_ = menu
    asked, closed = [], []
    m.states_requested.connect(asked.append)
    m.bluetooth_requested.connect(lambda: asked.append("bluetooth"))
    m.closed.connect(lambda: closed.append(True))
    for button in (m.save_state_button, m.load_state_button, m.bluetooth_button):
        m.set_emulated(True, 1.0)
        m.open_menu(0x70000001, "Mario")
        button.click()
        assert not m.isVisible()
    assert asked == ["save", "load", "bluetooth"] and closed == []  # GamingCrypt stays in front
    m.set_emulated(False)
    m.open_menu(620, "Portal 2")
    assert m.bluetooth_button.isVisibleTo(m) and not m.save_state_button.isVisibleTo(m)  # any game, and none


def test_the_60_fps_box(qtbot, menu):
    """Next to Controls, for 50 Hz games: ticking it tells the app, the menu stays open."""
    m, *_ = menu
    m.set_emulated(True, 1.0)
    m.set_in_step(False)
    m.open_menu(0x70000001, "Mario")
    assert not m.in_step_button.isVisibleTo(m)
    m.set_in_step(True, False)
    m._test_host.grab()
    assert m.in_step_button.isVisibleTo(m) and not m.in_step_button.isChecked()
    y = lambda w: w.mapTo(m, w.rect().topLeft()).y()  # noqa: E731
    assert y(m.in_step_button) == y(m.controls_button)
    panel = m.panel.viewport().rect()
    for button in (m.controls_button, m.in_step_button):
        r = button.rect().translated(button.mapTo(m.panel.viewport(), button.rect().topLeft()))
        assert panel.contains(r) and button.width() >= button.sizeHint().width(), button.text()  # not cut
    chosen = []
    m.in_step_chosen.connect(chosen.append)
    m.in_step_button.click()
    assert chosen == [True] and m.isVisible() and m.in_step_button.text().startswith("☑")
    m.set_in_step(True, False)  # shown as it is, nothing asked
    assert chosen == [True] and m.in_step_button.text().startswith("☐")
    m.set_speed_busy(True, "Changing to 60 FPS…")
    assert not m.in_step_button.isEnabled()
    m.set_speed_busy(False)
    assert m.in_step_button.isEnabled()
    assert m._rows()[1][3] == [m.controls_button, m.in_step_button]  # the controller reaches it

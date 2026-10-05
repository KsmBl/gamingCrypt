"""Quick menu: power limit + FPS limit for the running game, performance overlay, screenshot."""

import copy
import os
import subprocess
import time
from pathlib import Path

import pytest

from gamingcrypt.system import gamescope_ctl as gs
from gamingcrypt.system.power import PowerLimit


def test_screenshot_and_overlay_commands(tmp_path):
    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    assert gs.request_screenshot(run)
    assert calls[-1] == ["xprop", "-root", "-f", gs.SCREENSHOT, "32c", "-set", gs.SCREENSHOT, "2"]
    pending = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, f"{gs.SCREENSHOT}(CARDINAL) = 2\n", "")  # noqa
    done = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, f"{gs.SCREENSHOT}:  not found.\n", "")  # noqa
    assert gs.screenshot_pending(pending) and not gs.screenshot_pending(done)
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert not gs.overlay_shown(env)  # no config yet: off
    assert gs.set_overlay(True, env) and gs.overlay_shown(env) and "fps" in gs.overlay_config(env).read_text()
    assert gs.set_overlay(False, env) and not gs.overlay_shown(env)


def test_session_starts_the_overlay_hidden(tmp_path):
    from tests.test_session import run_session

    code, calls = run_session(tmp_path, "exit0", {"GC_MANGOAPP": "sh"})
    assert " --mangoapp -- " in calls[0]
    assert (tmp_path / "config/gamingcrypt/mangohud.conf").read_text().strip() == "no_display"


@pytest.fixture
def window(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system.controls import SystemControls
    from tests.test_quick_menu import Audio, Brightness

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(gs, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gs, "set_window_appid", lambda wid: True)
    monkeypatch.setattr(gs, "overlay_available", lambda which=None: True)
    fps = []
    monkeypatch.setattr(gs, "set_fps_limit", lambda value: fps.append(value) or True)

    class Power:
        sets = []

        def read(self):
            return PowerLimit(15, 5, 28, "test")

        def set(self, watts):
            Power.sets.append(watts)
            return True, ""

    system = SystemControls(audio=Audio(), brightness=Brightness())
    system.power = Power()
    Power.sets = []
    saved = []
    w = MainWindow(copy.deepcopy(DEFAULTS), saved.append, system=system)
    qtbot.addWidget(w)
    w.windowed = True
    w.resize(1280, 800)
    w.show()
    w._fps, w._power, w._saved = fps, Power, saved
    return w


def test_in_game_settings_go_to_the_game_profile(qtbot, window):
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    window.game_profiles.set(620, "fps", 40)
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.power_row.isVisible() and menu.power.minimum() == 5 and menu.power.maximum() == 28
    assert menu.fps_row.isVisible() and menu.fps.currentData() == 40
    assert menu.overlay_button.isVisible() and menu.screenshot_button.isVisible()
    menu.power.setValue(9)
    qtbot.waitUntil(lambda: window._power.sets == [9])
    assert window.game_profiles.get(620)["power_w"] == 9 and window.config["system"]["power_limit_w"] is None
    menu.fps.setCurrentIndex(menu.fps.findData(30))
    assert window.game_profiles.get(620)["fps"] == 30
    qtbot.waitUntil(lambda: window._fps == [30])
    window.game_watcher._stop()


def test_without_a_game_the_power_limit_is_the_settings_one(qtbot, window):
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert not menu.fps_row.isVisible() and not menu.screenshot_button.isVisible()
    menu.power.setValue(18)
    qtbot.waitUntil(lambda: window._power.sets == [18])
    assert window._saved[-1]["system"]["power_limit_w"] == 18


def test_overlay_button(qtbot, window, monkeypatch):
    switched = []
    monkeypatch.setattr(gs, "set_overlay_wanted", lambda on: switched.append(on) or True)
    window.toggle_quick_menu()
    window.quick_menu.overlay_button.click()
    assert switched == [True]


def test_overlay_only_over_games(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert not gs.overlay_wanted(env)
    gs.set_overlay(True, env)  # from an older version: it was on
    assert gs.overlay_wanted(env)
    gs.set_overlay_wanted(True, env)
    assert gs.apply_overlay(False, env) and not gs.overlay_shown(env)  # GamingCrypt in front: hidden
    assert gs.apply_overlay(True, env) and gs.overlay_shown(env)  # the game: shown
    gs.set_overlay_wanted(False, env)
    assert gs.apply_overlay(True, env) and not gs.overlay_shown(env)


def test_app_shows_the_overlay_only_with_the_game_in_front(qtbot, window, monkeypatch):
    from gamingcrypt.session import mode

    monkeypatch.setattr(mode, "in_gaming_session", lambda: True)
    monkeypatch.setattr(gs, "set_focus_order", lambda order, runner=None: True)
    monkeypatch.setattr(gs, "set_window_appid", lambda w, appid=None, runner=None: True)
    applied = []
    monkeypatch.setattr(gs, "apply_overlay", lambda in_front, env=None: applied.append(in_front) or True)
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    monkeypatch.setattr(type(window.game_watcher), "active", property(lambda self: True))
    window.gamescope_focus("game")
    window.gamescope_focus("launcher")
    window.gamescope_focus("steam")
    assert applied == [True, False, False]


def test_screenshot_of_the_game(qtbot, window, monkeypatch, tmp_path):
    shot = tmp_path / "gamescope.png"
    monkeypatch.setattr(gs, "SCREENSHOT_FILE", str(shot))
    monkeypatch.setenv("HOME", str(tmp_path))
    state = {"pending": False}

    def request():
        state["pending"] = True
        shot.write_bytes(b"png")
        os.utime(shot, (time.time() + 5, time.time() + 5))
        state["pending"] = False
        return True

    monkeypatch.setattr(gs, "request_screenshot", request)
    monkeypatch.setattr(gs, "screenshot_pending", lambda: state["pending"])
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    asides = []
    window.step_aside = lambda front="steam": asides.append(front)
    window.toggle_quick_menu()
    window.quick_menu.screenshot_button.click()
    assert not window.quick_menu.isVisible() and asides == ["game"]  # the game in front for the picture
    qtbot.waitUntil(lambda: any("Screenshot saved" in t for t in window.toasts.shown)
                    or any("Screenshot saved" in t for _i, t in window.toasts.queue), timeout=5000)
    saved = list((Path(tmp_path) / "Pictures" / "GamingCrypt").glob("*.png"))
    assert len(saved) == 1 and saved[0].read_bytes() == b"png"
    window.game_watcher._stop()


def test_no_overlay_without_mangoapp(qtbot, window, monkeypatch):
    monkeypatch.setattr(gs, "overlay_available", lambda which=None: False)
    window.toggle_quick_menu()
    assert not window.quick_menu.overlay_button.isVisible()

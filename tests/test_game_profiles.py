"""Per-game power limit and FPS limit (game page -> Options), applied while the game runs."""

import pytest

from gamingcrypt.game_profiles import GameProfiles
from gamingcrypt.system import gamescope_ctl
from gamingcrypt.system.power import PowerLimit


def test_profiles_store(tmp_path):
    profiles = GameProfiles(tmp_path / "p.json")
    assert profiles.get(620) == {}
    profiles.set(620, "power_w", 10)
    profiles.set(620, "fps", 40)
    assert GameProfiles(tmp_path / "p.json").get(620) == {"power_w": 10, "fps": 40}
    profiles.set(620, "power_w", 0)  # default again
    profiles.set(620, "fps", 0)
    assert profiles.get(620) == {} and "620" not in (tmp_path / "p.json").read_text()
    (tmp_path / "p.json").write_text("broken")
    assert profiles.get(620) == {}


def test_fps_limit_command():
    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or __import__("subprocess").CompletedProcess(cmd, 0, "", "")  # noqa
    assert gamescope_ctl.set_fps_limit(40, run)
    # gamescope's control protocol, as Steam does it (a limit set by the property alone was reset
    # every frame - games ran on at 60 on the handheld); the property for older gamescopes
    assert calls[-2] == ["gamescopectl", "debug_set_fps_limit", "40"]
    assert calls[-1] == ["xprop", "-root", "-f", "GAMESCOPE_FPS_LIMIT", "32c", "-set", "GAMESCOPE_FPS_LIMIT", "40"]
    assert gamescope_ctl.set_fps_limit(0, run)
    assert calls[-2] == ["gamescopectl", "debug_set_fps_limit", "0"] and calls[-1][-2:] == ["-remove", "GAMESCOPE_FPS_LIMIT"]

    def no_gamescopectl(cmd, **kw):
        if cmd[0] == "gamescopectl":
            raise FileNotFoundError(cmd[0])
        return __import__("subprocess").CompletedProcess(cmd, 0, "", "")

    assert gamescope_ctl.set_fps_limit(30, no_gamescopectl)  # the property alone still counts


def test_game_page_options(qtbot, monkeypatch):
    from gamingcrypt.system import power
    from tests.test_proton import proton_page

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(power, "read_limit", lambda *a, **k: PowerLimit(15, 5, 28, "AMD Renoir SMU"))
    page, service = proton_page(qtbot)
    combo = page.power_combo
    assert combo.itemText(0) == "Default (Settings)" and combo.itemText(1) == "5 W" and combo.itemText(24) == "28 W"
    combo.setCurrentIndex(combo.findData(9))
    page.fps_combo.setCurrentIndex(page.fps_combo.findData(40))
    assert page.profiles.get(620) == {"power_w": 9, "fps": 40}
    assert "40 FPS while" in page.status.text()
    page.options_button.click()
    page.options_button.click()  # reopened: shows what's saved
    assert combo.currentData() == 9 and page.fps_combo.currentData() == 40


def test_fps_needs_gaming_mode_and_power_needs_hardware(qtbot, monkeypatch):
    from gamingcrypt.system import power
    from tests.test_proton import proton_page

    monkeypatch.setattr(power, "read_limit", lambda *a, **k: None)
    page, _ = proton_page(qtbot)
    assert not page.power_combo.isEnabled() and not page.fps_combo.isEnabled()


class Power:
    def __init__(self, current=15):
        self.sets, self.current = [], current

    def read(self):
        return PowerLimit(self.current, 5, 28, "test")

    def set(self, watts):
        self.sets.append(watts)
        return True, ""


@pytest.fixture
def window(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system.controls import SystemControls

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda wid: True)
    fps = []
    monkeypatch.setattr(gamescope_ctl, "set_fps_limit", lambda value: fps.append(value) or True)
    system = SystemControls()
    system.power = Power()
    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, system=system)
    qtbot.addWidget(w)
    w._fps = fps
    return w


def test_profile_applied_while_the_game_runs(qtbot, window):
    window.game_profiles.set(620, "power_w", 8)
    window.game_profiles.set(620, "fps", 40)
    window.game_watcher.appid = 620
    window.game_watcher.started.emit(620)
    qtbot.waitUntil(lambda: window.system.power.sets == [8] and window._fps == [40])
    window.game_watcher._stop()
    window.game_watcher.finished.emit(620)
    # no limit chosen in Settings: back to what it was before the game
    qtbot.waitUntil(lambda: window.system.power.sets == [8, 15] and window._fps == [40, 0])


def test_settings_limit_wins_after_the_game(qtbot, window):
    window.config["system"]["power_limit_w"] = 20
    window.game_profiles.set(620, "power_w", 8)
    window.game_watcher.appid = 620
    window.game_watcher.started.emit(620)
    window.game_watcher._stop()
    window.game_watcher.finished.emit(620)
    qtbot.waitUntil(lambda: window.system.power.sets == [8, 20])


def test_game_without_profile_changes_nothing(qtbot, window):
    window.game_watcher.appid = 1
    window.game_watcher.started.emit(1)
    window.game_watcher._stop()
    window.game_watcher.finished.emit(1)
    qtbot.wait(50)
    assert window.system.power.sets == [] and window._fps == []

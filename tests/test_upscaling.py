"""Upscaling: games rendered smaller on gamescope's second X server, scaled up with FSR."""

import copy

import pytest

from gamingcrypt.linux import runners as linux_runners
from gamingcrypt.system import upscaling
from gamingcrypt.wine import covers as covers_mod
from gamingcrypt.wine import runners as wine_runners

SCREEN = (1280, 800)


def test_render_sizes_and_names():
    assert upscaling.render_size(SCREEN, 75) == (960, 600)
    assert upscaling.render_size(SCREEN, 50) == (640, 400)
    assert upscaling.render_size(SCREEN, 85) == (1088, 680)
    assert all(n % 2 == 0 for p in upscaling.LEVELS for n in upscaling.render_size((1366, 767), p))  # even
    assert upscaling.describe(None, SCREEN) == "Off - full resolution"
    assert upscaling.describe(75, SCREEN) == "Medium - 75% (960×600)"
    assert list(upscaling.LEVELS) == sorted(upscaling.LEVELS, reverse=True)  # light to strong


def test_start_and_stop_the_second_x_server(tmp_path):
    import subprocess

    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    assert upscaling.start(75, SCREEN, run, x11_dir=tmp_path) == {}  # no second X server: as it is
    (tmp_path / "X1").touch()
    assert upscaling.start(None, SCREEN, run, x11_dir=tmp_path) == {} and calls == []  # off
    assert upscaling.start(33, SCREEN, run, x11_dir=tmp_path) == {}  # not one of the levels
    assert upscaling.start(60, SCREEN, run, x11_dir=tmp_path) == {"DISPLAY": ":1"}  # the game goes there
    assert calls == [
        ["xprop", "-root", "-f", "GAMESCOPE_XWAYLAND_MODE_CONTROL", "32c", "-set", "GAMESCOPE_XWAYLAND_MODE_CONTROL",
         "1,768,480,0"],
        ["xprop", "-root", "-f", "GAMESCOPE_NEW_SCALING_FILTER", "32c", "-set", "GAMESCOPE_NEW_SCALING_FILTER", "2"]]
    upscaling.stop(SCREEN, run)
    assert calls[-2][-1] == "1,1280,800,0" and calls[-1][-1] == "0"  # full size, the usual scaling
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "no gamescope")  # noqa: E731
    assert upscaling.start(60, SCREEN, failing, x11_dir=tmp_path) == {}


def test_runners_pass_the_display_on(tmp_path):
    from gamingcrypt.linux.library import LinuxGame
    from gamingcrypt.wine.library import WindowsGame

    folder = tmp_path / "Game"
    folder.mkdir()
    (folder / "game.exe").write_bytes(b"MZ")
    (folder / "game.sh").write_bytes(b"#!/bin/sh\n")
    started = []
    popen = lambda args, **kw: started.append(kw["env"])  # noqa: E731
    wine = wine_runners.Runner("wine:system", "Wine", "wine", tmp_path / "wine")
    assert wine_runners.launch(WindowsGame(folder, "Game"), "game.exe", wine, tmp_path / "d", tmp_path / "l",
                               popen=popen, home=tmp_path, which=lambda n: None, more_env={"DISPLAY": ":1"})[0]
    assert started[-1]["DISPLAY"] == ":1"
    assert linux_runners.launch(LinuxGame(folder, "Game"), "game.sh", linux_runners.DIRECT, tmp_path / "d",
                                tmp_path / "l", popen=popen, more_env={"DISPLAY": ":1"})[0]
    assert started[-1]["DISPLAY"] == ":1"


def gamescope(monkeypatch) -> list:
    """In the gaming session, with a second X server; what's asked of gamescope."""
    from gamingcrypt.session import mode
    from gamingcrypt.system import gamescope_ctl

    asked = []
    monkeypatch.setattr(mode, "in_gaming_session", lambda *a, **k: True)
    monkeypatch.setattr(upscaling, "available", lambda *a, **k: True)
    monkeypatch.setattr(gamescope_ctl, "set_xwayland_mode", lambda *a, **k: asked.append(("mode", *a[:3])) or True)
    monkeypatch.setattr(gamescope_ctl, "set_scaling_filter", lambda *a, **k: asked.append(("filter", a[0])) or True)
    monkeypatch.setattr(gamescope_ctl, "set_fps_limit", lambda *a, **k: True)
    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda *a, **k: True)
    monkeypatch.setattr(gamescope_ctl, "set_touch_mode", lambda *a, **k: True)
    return asked


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(covers_mod.Covers, "fetch", lambda self, game: None)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    launched = []
    monkeypatch.setattr(linux_runners, "launch", lambda game, exe, runner, *a, **k: launched.append(
        k.get("more_env")) or (True, "Starting"))
    monkeypatch.setattr(wine_runners, "launch", lambda game, exe, runner, *a, **k: launched.append(
        k.get("more_env")) or (True, "Starting"))
    gamescope(monkeypatch)
    linux_root, windows_root = tmp_path / "Linux Games", tmp_path / "Windows Games"
    (linux_root / "Celeste").mkdir(parents=True)
    (linux_root / "Celeste" / "Celeste.sh").write_bytes(b"#!/bin/sh\n")
    (windows_root / "Hollow Knight").mkdir(parents=True)
    (windows_root / "Hollow Knight" / "hollow_knight.exe").write_bytes(b"MZ")
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], windows_root=str(windows_root),
                                  linux_root=str(linux_root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show()
    w.show_shell()
    games = pages["Games"]
    games._runners = [wine_runners.Runner("wine:system", "Wine (system)", "wine", tmp_path)]
    qtbot.waitUntil(lambda: bool(games.linux_games and games.windows_games))
    w._games, w._launched = games, launched
    monkeypatch.setattr(w, "screen_size", lambda: SCREEN)
    return w


@pytest.mark.parametrize("kind", ["linux", "windows"])
def test_option_on_the_games_page_and_launch(qtbot, window, monkeypatch, kind):
    games = window._games
    game = getattr(games, f"{kind}_games")[0]
    getattr(games, f"open_{kind}_game")(game)
    page = games.currentWidget()
    monkeypatch.setattr(page, "screen_size", lambda: SCREEN)
    page._fill_upscaling()
    combo = page.upscale_combo
    assert combo.isEnabled()
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Off - full resolution", "Light - 85% (1088×680)", "Medium - 75% (960×600)", "Strong - 60% (768×480)",
        "Maximum - 50% (640×400)"]
    assert "FSR" in page.upscale_note.text()
    combo.setCurrentIndex(combo.findData(75))
    assert window.game_profiles.get(game.appid)["upscale"] == 75
    assert "Renders at 960×600, upscaled with FSR" in page.facts.text()
    getattr(window, f"launch_{kind}")(game)
    assert window._launched[-1]["DISPLAY"] == ":1"  # on the second X server, at 960×600
    window.game_ended(game.appid)
    assert not window._upscaled  # the second server at full size again (in the background)
    combo.setCurrentIndex(0)
    assert "upscale" not in window.game_profiles.get(game.appid)
    assert "Renders at" not in page.facts.text()
    getattr(window, f"launch_{kind}")(game)
    assert "DISPLAY" not in window._launched[-1]


def test_the_second_server_is_set_and_put_back(qtbot, window, monkeypatch):
    from gamingcrypt.system import gamescope_ctl

    asked = []
    monkeypatch.setattr(gamescope_ctl, "set_xwayland_mode", lambda *a, **k: asked.append(("mode", *a[:3])) or True)
    monkeypatch.setattr(gamescope_ctl, "set_scaling_filter", lambda *a, **k: asked.append(("filter", a[0])) or True)
    games = window._games
    game = games.linux_games[0]
    window.game_profiles.set(game.appid, "upscale", 50)
    window.launch_linux(game)
    assert asked == [("mode", 1, 640, 400), ("filter", gamescope_ctl.FILTER_FSR)]
    window.game_ended(game.appid)
    qtbot.waitUntil(lambda: len(asked) == 4)
    assert asked[2:] == [("mode", 1, 1280, 800), ("filter", gamescope_ctl.FILTER_LINEAR)]
    monkeypatch.setattr(linux_runners, "launch", lambda *a, **k: (False, "It didn't start"))
    window.launch_linux(game)
    qtbot.waitUntil(lambda: len(asked) == 8)  # it didn't start: put back at once
    assert asked[-2:] == [("mode", 1, 1280, 800), ("filter", gamescope_ctl.FILTER_LINEAR)]


def test_without_gamescope_the_choice_is_off(qtbot, window, monkeypatch):
    games = window._games
    monkeypatch.setattr("shutil.which", lambda name: None)
    games.open_linux_game(games.linux_games[0])
    page = games.currentWidget()
    assert not page.upscale_combo.isEnabled() and "isn't installed" in page.upscale_note.text()


def test_emulated_games_have_no_upscaling(qtbot, tmp_path):
    """Their work is the emulator's internal resolution (Options -> Resolution), not the picture's size."""
    import copy as _copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    emu = tmp_path / "Emulation"
    (emu / "roms" / "ps2").mkdir(parents=True)
    (emu / "roms" / "ps2" / "Need for Speed Underground 2.iso").write_bytes(b"x")
    tab = GamesTab(FakeService(), library_settings=_copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(emu))
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: "ps2" in tab.roms)
    tab.open_rom(tab.roms["ps2"][0])
    page = tab.currentWidget()
    assert not hasattr(page, "upscale_combo") and page.resolution_combo is not None

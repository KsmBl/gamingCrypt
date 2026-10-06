"""Upscaling: Windows / Linux games rendered smaller, scaled up by a nested gamescope (FSR)."""

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


def test_nested_gamescope_command():
    which = lambda name: f"/usr/bin/{name}"  # noqa: E731
    assert upscaling.command(None, SCREEN, which=which) == []
    assert upscaling.command(33, SCREEN, which=which) == []  # not one of the levels
    assert upscaling.command(75, SCREEN, which=lambda n: None) == []  # no gamescope: as it is
    cmd = upscaling.command(60, SCREEN, which=which)
    assert cmd[:4] == ["env", "-u", "GAMESCOPE_WAYLAND_DISPLAY", "ENABLE_GAMESCOPE_WSI=0"]  # no WSI-layer error
    assert cmd[4:] == ["/usr/bin/gamescope", "-w", "768", "-h", "480", "-W", "1280", "-H", "800", "-F", "fsr", "-f",
                       "--"]
    assert upscaling.command(50, SCREEN, fps=30, which=which)[-3:] == ["-r", "30", "--"]  # the limit inside too


def test_runners_put_it_before_the_game(tmp_path):
    from gamingcrypt.linux.library import LinuxGame
    from gamingcrypt.wine.library import WindowsGame

    folder = tmp_path / "Game"
    folder.mkdir()
    (folder / "game.exe").write_bytes(b"MZ")
    (folder / "game.sh").write_bytes(b"#!/bin/sh\n")
    wrapper = ["gamescope", "-w", "960", "--"]
    started = []
    popen = lambda args, **kw: started.append(args)  # noqa: E731
    wine = wine_runners.Runner("wine:system", "Wine", "wine", tmp_path / "wine")
    assert wine_runners.launch(WindowsGame(folder, "Game"), "game.exe", wine, tmp_path / "d", tmp_path / "l",
                               popen=popen, home=tmp_path, which=lambda n: None, wrapper=wrapper)[0]
    assert started[-1][4:9] == [*wrapper, str(tmp_path / "wine")]  # reaper ... -- gamescope … -- wine game.exe
    assert linux_runners.launch(LinuxGame(folder, "Game"), "game.sh", linux_runners.DIRECT, tmp_path / "d",
                                tmp_path / "l", popen=popen, wrapper=wrapper)[0]
    assert started[-1][4:] == [*wrapper, str(folder / "game.sh")]
    linux_runners.launch(LinuxGame(folder, "Game"), "game.sh", linux_runners.DIRECT, tmp_path / "d", tmp_path / "l",
                         popen=popen)
    assert started[-1][4:] == [str(folder / "game.sh")]  # off: nothing in between


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
        k.get("wrapper")) or (True, "Starting"))
    monkeypatch.setattr(wine_runners, "launch", lambda game, exe, runner, *a, **k: launched.append(
        k.get("wrapper")) or (True, "Starting"))
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
    window.game_profiles.set(game.appid, "fps", 40)
    getattr(window, f"launch_{kind}")(game)
    wrapper = window._launched[-1]
    assert wrapper[4:] == ["/usr/bin/gamescope", "-w", "960", "-h", "600", "-W", "1280", "-H", "800", "-F", "fsr",
                           "-f", "-r", "40", "--"]
    combo.setCurrentIndex(0)
    assert "upscale" not in window.game_profiles.get(game.appid)
    assert "Renders at" not in page.facts.text()
    getattr(window, f"launch_{kind}")(game)
    assert window._launched[-1] == []


def test_without_gamescope_the_choice_is_off(qtbot, window, monkeypatch):
    games = window._games
    monkeypatch.setattr("shutil.which", lambda name: None)
    games.open_linux_game(games.linux_games[0])
    page = games.currentWidget()
    assert not page.upscale_combo.isEnabled() and "isn't installed" in page.upscale_note.text()

"""Running speed of RetroArch games (0.1x - 10x) from the quick menu."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


def test_speed_settings():
    assert retroarch.SLOW_SPEEDS[0] == 0.1 and retroarch.FAST_SPEEDS[-1] == 10.0
    assert retroarch.speed_settings(3.0, 0.25) == {"fastforward_ratio": "3", "slowmotion_ratio": "4"}
    assert retroarch.speed_settings(10.0, 0.1) == {"fastforward_ratio": "10", "slowmotion_ratio": "10"}


def test_mode_commands():
    assert retroarch.mode_commands("normal", "fast") == ["FAST_FORWARD"]
    assert retroarch.mode_commands("fast", "normal") == ["FAST_FORWARD"]
    assert retroarch.mode_commands("normal", "slow") == ["SLOWMOTION"]
    assert retroarch.mode_commands("slow", "fast") == ["SLOWMOTION", "FAST_FORWARD"]
    assert retroarch.mode_commands("fast", "fast") == []


def test_launch_writes_the_rates(tmp_path):
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.cores / "snes9x_libretro.so").write_text("x")
    (paths.roms / "snes" / "Mario.sfc").write_text("x")
    game = scan(paths, BY_ID["snes"])[0]
    ok, _ = retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", popen=lambda cmd, **k: None,
                             which=lambda n: "/usr/bin/retroarch", fast=4.0, slow=0.25)
    config = (paths.config / "gamingcrypt.cfg").read_text()
    assert ok and 'fastforward_ratio = "4"' in config and 'slowmotion_ratio = "4"' in config


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Super Mario World.sfc").write_text("x")
    launches, sent = [], []
    monkeypatch.setattr(retroarch, "launch", lambda game, *a, **k: launches.append(
        (game.name, k.get("fast"), k.get("slow"))) or (True, "Starting"))
    monkeypatch.setattr(retroarch, "send", lambda text, port=None: sent.append(text) or True)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(paths.root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    games = pages["Games"]
    qtbot.waitUntil(lambda: "snes" in games.home.system_cards)
    w._launches, w._sent, w._game = launches, sent, scan(paths, BY_ID["snes"])[0]
    return w


def test_quick_menu_switches_speed_instantly(qtbot, window):
    game = window._game
    window.launch_rom(game)
    assert window._launches == [("Super Mario World", 2.0, 0.5)]  # the defaults
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    buttons = menu.speed_buttons
    assert menu.speed_row.isVisibleTo(menu) and buttons["normal"].isChecked()
    assert buttons["fast"].text() == "Fast 2x" and buttons["slow"].text() == "Slow 0.5x"
    buttons["fast"].click()
    assert window._sent == ["FAST_FORWARD"] and menu.isVisible()  # right away, no restart
    assert buttons["fast"].isChecked() and not buttons["normal"].isChecked()
    buttons["slow"].click()
    assert window._sent == ["FAST_FORWARD", "FAST_FORWARD", "SLOWMOTION"]
    menu.close_menu()
    window.toggle_quick_menu()
    assert buttons["slow"].isChecked()  # still slow
    buttons["normal"].click()
    assert window._sent[-1] == "SLOWMOTION" and "QUIT" not in window._sent


def test_rates_from_the_game_page(qtbot, window):
    from gamingcrypt.ui.emulation_pages import RomGamePage

    games = window.shell.pages["Games"]
    page = RomGamePage(games, window._game)
    qtbot.addWidget(page)
    fast = page.speed_combos["fast_speed"]
    fast.setCurrentIndex(fast.findData(5.0))
    page.speed_combos["slow_speed"].setCurrentIndex(0)
    assert window.speed_rates(window._game) == (5.0, 0.1)
    window.launch_rom(window._game)
    assert window._launches[-1] == ("Super Mario World", 5.0, 0.1)
    fast.setCurrentIndex(fast.findData(2.0))  # the default: not stored
    assert "fast_speed" not in window.game_profiles.get(window._game.appid)

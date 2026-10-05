"""The screen follows a game's frame rate: 50 Hz PAL games on a 60 Hz screen stuttered
(every fifth frame twice - NFSU2 PAL on the AYANEO)."""

import copy
import shutil
import subprocess
from pathlib import Path

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID

ROOT = Path(__file__).resolve().parent.parent
LUA = ROOT / "gamingcrypt" / "session" / "gamescope" / "gamingcrypt-displays.lua"

# as RetroArch writes it (NFSU2 PAL on the handheld)
PAL_LOG = """[INFO] [Core] Geometry: 640x448, Aspect: 1.333, FPS: 59.94, Sample rate: 48000.00 Hz.
[INFO] [Environ] SET_SYSTEM_AV_INFO: 640x448, Aspect: 1.333, FPS: 59.94, Sample rate: 48000.00 Hz.
[libretro INFO] [GameDB] No CRC-specific patch or default patch found
[INFO] [Environ] SET_SYSTEM_AV_INFO: 640x512, Aspect: 1.333, FPS: 50.00, Sample rate: 48000.00 Hz.
[INFO] [Video] Timings deviate too much. Will not adjust. (Target = 60.00 Hz, Game = 50.00 Hz)
"""


def test_content_fps_from_the_log(tmp_path):
    log = tmp_path / "retroarch.log"
    assert retroarch.content_fps(log) is None
    log.write_text("[INFO] [Core] Geometry: 256x224, Aspect: 1.143, FPS: 60.10, Sample rate: 32040.50 Hz.\n")
    assert retroarch.content_fps(log) == 60.10
    log.write_text(PAL_LOG)
    assert retroarch.content_fps(log) == 50.0  # the last one: the game switched to PAL
    assert retroarch.refresh_for(50.0) == 50 and retroarch.refresh_for(49.9) == 50
    assert retroarch.refresh_for(59.94) == 0 and retroarch.refresh_for(None) == 0


def test_launch_logs_verbosely_into_a_fresh_file(tmp_path):
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.cores / "snes9x_libretro.so").write_text("x")
    (paths.roms / "snes" / "Mario.sfc").write_text("x")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / retroarch.LOG_NAME).write_text(PAL_LOG)  # the last game's
    started = []
    retroarch.launch(scan(paths, BY_ID["snes"])[0], paths, tmp_path / "d", logs,
                     popen=lambda cmd, **k: started.append(cmd), which=lambda n: "/usr/bin/retroarch")
    assert "--verbose" in started[0] and (logs / retroarch.LOG_NAME).read_text() == ""


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from gamingcrypt import config as config_mod
    from gamingcrypt.app import MainWindow
    from gamingcrypt.session import mode
    from gamingcrypt.system import gamescope_ctl
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "ps2").mkdir(exist_ok=True)
    (paths.roms / "ps2" / "NFSU2.iso").write_text("x")
    monkeypatch.setattr(mode, "in_gaming_session", lambda env=None: True)
    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order, runner=None: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda *a, **k: True)
    refresh = {"hz": 0, "sets": []}
    monkeypatch.setattr(gamescope_ctl, "dynamic_refresh", lambda runner=None: refresh["hz"])
    monkeypatch.setattr(gamescope_ctl, "set_dynamic_refresh",
                        lambda hz, runner=None: refresh["sets"].append(hz) or refresh.update(hz=hz) or True)
    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: (True, "Starting"))
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(paths.root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show_shell()
    w._log = config_mod.cache_dir() / "logs" / retroarch.LOG_NAME
    w._log.parent.mkdir(parents=True, exist_ok=True)
    w._log.write_text("")
    w._refresh, w._game = refresh, scan(paths, BY_ID["ps2"])[0]
    return w


def test_screen_follows_a_pal_game_and_comes_back(qtbot, window):
    window.launch_rom(window._game)
    window._log.write_text(PAL_LOG)
    qtbot.waitUntil(lambda: window._refresh["sets"] == [50], timeout=5000)
    window.game_watcher._stop()
    window.game_watcher.finished.emit(window._game.appid)
    qtbot.waitUntil(lambda: window._refresh["sets"] == [50, 0], timeout=3000)


def test_a_60_hz_game_leaves_the_screen_alone(qtbot, window):
    window.launch_rom(window._game)
    window._log.write_text("[INFO] [Core] Geometry: 640x448, Aspect: 1.333, FPS: 59.94, Sample rate: 48000.00 Hz.\n")
    qtbot.wait(2500)
    window.game_watcher._stop()
    window.game_watcher.finished.emit(window._game.appid)
    qtbot.wait(300)
    assert window._refresh["sets"] == []


def test_the_quick_menus_choice_wins(qtbot, window):
    window.launch_rom(window._game)
    window._log.write_text(PAL_LOG)
    qtbot.waitUntil(lambda: window._refresh["sets"] == [50], timeout=5000)
    window._refresh["hz"] = 40  # chosen in the quick menu
    qtbot.waitUntil(lambda: not window._refresh_timer.isActive(), timeout=3000)
    assert window._refresh["sets"] == [50]


@pytest.mark.skipif(shutil.which("lua") is None, reason="needs lua")
def test_display_profile_for_the_ayaneo_panel(tmp_path):
    """gamescope's Lua profile: matches the AYANEO 2021 panel (EDID UGD 0x1003), 40-60 Hz."""
    script = tmp_path / "check.lua"
    script.write_text(f"""
gamescope = {{ config = {{ known_displays = {{}} }},
  modegen = {{ calc_max_clock = function(mode, hz) return hz * 1000 end,
              calc_vrefresh = function(mode) return mode.clock / 1000 end }} }}
function debug(text) end
dofile("{LUA}")
local panel = gamescope.config.known_displays.gamingcrypt_ayaneo_2021_lcd
print(panel.matches({{ vendor = "UGD", product = 0x1003, model = "" }}))
print(panel.matches({{ vendor = "VLV", product = 0x3003, model = "" }}))
print(panel.dynamic_refresh_rates[1], panel.dynamic_refresh_rates[#panel.dynamic_refresh_rates])
print(panel.dynamic_modegen({{ clock = 1 }}, 50).vrefresh)
""")
    out = subprocess.run(["lua", str(script)], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["4000", "-1", "40", "60", "50"] or out == ["4000", "-1", "40", "60", "50.0"]


def test_install_script_copies_the_profile(tmp_path):
    function = subprocess.run(["sed", "-n", "/^install_gamescope_displays()/,/^}/p", str(ROOT / "install.sh")],
                              capture_output=True, text=True).stdout
    subprocess.run(["bash", "-c", f'set -euo pipefail\n{function}\nSRC_DIR="{ROOT}" XDG_CONFIG_HOME="{tmp_path}" '
                    "install_gamescope_displays"], check=True)
    assert (tmp_path / "gamescope" / "gamingcrypt-displays.lua").read_text() == LUA.read_text()

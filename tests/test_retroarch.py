"""Starting emulated games with RetroArch."""

import copy
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


@pytest.fixture
def emu(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", (tmp_path / "system-cores",))
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Super Mario World.sfc").write_text("rom")
    return paths


def test_cores_on_the_drive_win(emu, tmp_path):
    system_cores = tmp_path / "system-cores"
    system_cores.mkdir()
    (system_cores / "snes9x_libretro.so").write_text("system")
    (system_cores / "bsnes_libretro.so").write_text("system")
    (emu.cores / "snes9x_libretro.so").write_text("drive")
    cores = retroarch.installed_cores(emu)
    assert cores["snes9x"] == emu.cores / "snes9x_libretro.so" and cores["bsnes"].parent == system_cores
    snes = BY_ID["snes"]
    assert retroarch.find_core(emu, snes) == emu.cores / "snes9x_libretro.so"  # preferred first
    assert retroarch.find_core(emu, snes, wanted="bsnes").name == "bsnes_libretro.so"
    assert retroarch.find_core(emu, BY_ID["psx"]) is None


def test_config_points_at_the_drive(emu):
    text = retroarch.write_config(emu).read_text()
    for key, folder in (("libretro_directory", emu.cores), ("system_directory", emu.bios),
                        ("savefile_directory", emu.saves), ("savestate_directory", emu.states)):
        assert f'{key} = "{folder}"' in text
    assert 'network_cmd_enable = "true"' in text and 'video_fullscreen = "true"' in text


def test_launch(emu, tmp_path):
    game = scan(emu, BY_ID["snes"])[0]
    started = []
    popen = lambda cmd, **kw: started.append((cmd, kw))  # noqa: E731
    ok, message = retroarch.launch(game, emu, tmp_path / "data", tmp_path / "logs",
                                   popen=popen, which=lambda t: None)
    assert not ok and "isn't installed" in message
    ok, message = retroarch.launch(game, emu, tmp_path / "data", tmp_path / "logs",
                                   popen=popen, which=lambda t: "/usr/bin/retroarch")
    assert not ok and "snes9x_libretro.so" in message and "Add games" in message  # no core yet
    (emu.cores / "snes9x_libretro.so").write_text("core")
    ok, message = retroarch.launch(game, emu, tmp_path / "data", tmp_path / "logs",
                                   popen=popen, which=lambda t: "/usr/bin/retroarch")
    cmd, kw = started[-1]
    assert ok and message == "Starting Super Mario World…"
    assert cmd[1:4] == ["SteamLaunch", f"AppId={game.appid}", "--"] and cmd[4] == "retroarch"
    assert cmd[-3:] == ["-L", str(emu.cores / "snes9x_libretro.so"), str(game.path)]
    assert kw["start_new_session"] and Path(cmd[0]).name == "reaper"


def test_reaper_is_seen_as_a_game(tmp_path):
    """gamescope and GamingCrypt find the emulator by 'reaper ... SteamLaunch AppId=<id>'."""
    from gamingcrypt.steam.running import game_processes

    script = retroarch.reaper(tmp_path)
    appid = 0x7ABCDEF1
    proc = subprocess.Popen([str(script), "SteamLaunch", f"AppId={appid}", "--", sys.executable, "-c",
                             "import time; time.sleep(3)"])
    try:
        deadline = time.time() + 3
        while time.time() < deadline and len(game_processes(appid)) < 2:
            time.sleep(0.05)
        pids = game_processes(appid)
        assert proc.pid in pids and len(pids) == 2  # the script stays the parent of the emulator
        assert Path(f"/proc/{proc.pid}/comm").read_text().strip() == "reaper"  # what gamescope checks
    finally:
        import os
        import signal

        for pid in game_processes(appid):  # only what this test started
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        proc.wait(5)


def test_network_command():
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(2)
    try:
        assert retroarch.send("SAVE_STATE", port=listener.getsockname()[1])
        assert listener.recvfrom(64)[0] == b"SAVE_STATE"
    finally:
        listener.close()


# --- the app -----------------------------------------------------------------------------

def test_play_and_quick_menu_states(qtbot, emu, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    cfg = copy.deepcopy(DEFAULTS)
    pages = {}

    def factory(config):
        pages["Games"] = GamesTab(FakeService(), library_settings=config["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    launched = []
    monkeypatch.setattr(retroarch, "launch", lambda game, paths, data, logs, core=None:
                        launched.append((game.name, core)) or (True, f"Starting {game.name}…"))
    sent = []
    monkeypatch.setattr(retroarch, "send", lambda text: sent.append(text) or True)
    window = MainWindow(cfg, lambda c: None, page_factory=factory)
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    window.show_shell()
    games = pages["Games"]
    games.reload_roms()
    qtbot.waitUntil(lambda: "snes" in games.home.system_cards)
    games.open_system("snes")
    card = next(iter(games.currentWidget().cards.values()))
    card.clicked.emit(card.game)
    rom_page = games.currentWidget()
    rom_page.main_button.click()
    assert launched == [("Super Mario World", None)] and "Starting Super Mario World" in rom_page.status.text()
    assert window.game_watcher.appid == card.game.appid and window.launch_overlay.isVisible()
    assert window.game_name(card.game.appid) == "Super Mario World"
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.state_row.isVisibleTo(menu)
    menu.save_state_button.click()
    assert sent == ["SAVE_STATE"] and any("State saved" in t for t in window.toasts.shown + [x[1] for x in window.toasts.queue])
    window.game_watcher._stop()
    window.toggle_quick_menu()
    window.toggle_quick_menu()
    assert not menu.state_row.isVisibleTo(menu)  # Steam game / nothing running: no states

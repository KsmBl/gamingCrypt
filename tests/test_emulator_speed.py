"""Running speed of RetroArch games (0.1x - 10x) from the quick menu."""

import copy
import socket
import threading

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


def test_speed_settings():
    assert retroarch.SPEEDS[0] == 0.1 and retroarch.SPEEDS[-1] == 10.0 and 1.0 in retroarch.SPEEDS
    assert retroarch.speed_settings(3.0) == {"fastforward_ratio": "3"}
    assert retroarch.speed_settings(0.25) == {"slowmotion_ratio": "4"}
    assert retroarch.speed_settings(0.1) == {"slowmotion_ratio": "10"} and retroarch.speed_settings(1.0) == {}
    assert retroarch.speed_toggle(2) == "FAST_FORWARD" and retroarch.speed_toggle(0.5) == "SLOWMOTION"
    assert retroarch.speed_toggle(1) is None


def test_launch_with_speed_and_entry_state(tmp_path):
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.cores / "snes9x_libretro.so").write_text("x")
    (paths.roms / "snes" / "Mario.sfc").write_text("x")
    game = scan(paths, BY_ID["snes"])[0]
    started = []
    ok, _ = retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", popen=lambda cmd, **k: started.append(cmd),
                             which=lambda n: "/usr/bin/retroarch", speed=2.0, entry_slot=9)
    assert ok and started[0][started[0].index("-e") + 1] == "9"
    config = (paths.config / "gamingcrypt.cfg").read_text()
    assert 'fastforward_ratio = "2"' in config and 'quit_press_twice = "false"' in config
    assert 'state_slot = "0"' in config  # the quick menu's Save / Load state


def test_status_query():
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def answer():
        data, address = server.recvfrom(64)
        assert data == b"GET_STATUS"
        server.sendto(b"GET_STATUS PLAYING super_nes,Mario,crc32=1", address)

    thread = threading.Thread(target=answer)
    thread.start()
    try:
        assert retroarch.playing(port)
    finally:
        thread.join()
        server.close()
    assert retroarch.query("GET_STATUS", port, timeout=0.2) is None  # nobody listening


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
        (game.name, k.get("speed"), k.get("entry_slot"))) or (True, "Starting"))
    monkeypatch.setattr(retroarch, "send", lambda text, port=None: sent.append(text) or True)
    monkeypatch.setattr(retroarch, "playing", lambda port=None: True)
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


def test_quick_menu_speed_restarts_the_game_from_a_state(qtbot, window, monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)
    game = window._game
    window.launch_rom(game)
    assert window._launches == [("Super Mario World", 1.0, None)]
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.speed_row.isVisibleTo(menu) and menu.speed_value.text() == "1x"
    menu.speed.setValue(retroarch.SPEEDS.index(3.0))
    assert menu.speed_value.text() == "3x" and window._sent == []  # nothing until the menu closes
    menu.close_menu()
    qtbot.waitUntil(lambda: window._sent[-1:] == ["QUIT"], timeout=3000)
    assert window._sent == ["STATE_SLOT_PLUS"] * retroarch.RESTART_SLOT + ["SAVE_STATE", "QUIT"]
    assert window.game_profiles.get(game.appid)["speed"] == 3.0 and window.launch_overlay.isVisible()
    window.game_watcher._stop()
    window.game_watcher.finished.emit(game.appid)  # RetroArch quit
    assert window._launches[-1] == ("Super Mario World", 3.0, retroarch.RESTART_SLOT)
    qtbot.waitUntil(lambda: "FAST_FORWARD" in window._sent, timeout=3000)  # switched on once playing
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    assert menu.speed_value.text() == "3x"  # remembered for the game
    menu.close_menu()  # unchanged: no restart
    assert window._sent.count("QUIT") == 1


def test_normal_speed_needs_no_toggle(qtbot, window):
    window.launch_rom(window._game)
    qtbot.wait(300)
    assert window._sent == []

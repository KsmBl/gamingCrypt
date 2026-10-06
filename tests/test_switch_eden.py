"""Nintendo Switch games with Eden: downloaded on first use, data on the drive, the controller set up."""

import copy
import io
import subprocess

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import eden, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


@pytest.fixture
def emu(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    (p.roms / "switch").mkdir(exist_ok=True)
    (p.roms / "switch" / "Mario Kart 8 Deluxe.nsp").write_text("x")
    return p


def test_switch_is_a_system(emu):
    games = scan(emu, BY_ID["switch"])
    assert [g.name for g in games] == ["Mario Kart 8 Deluxe"] and BY_ID["switch"].emulator == "eden"
    assert BY_ID["ps2"].cores == ("pcsx2",) and BY_ID["psx"].name == "PlayStation (PS1)"


def test_sdl_guid_of_the_virtual_controller():
    # what SDL reported on the handheld for GamingCrypt's virtual controller and the Xbox pad
    assert eden.sdl_guid() == "0300e5c95e0400008f02000010010000"
    assert eden.sdl_guid("Microsoft X-Box 360 pad", product=0x028E) == "030081b85e0400008e02000010010000"


def test_controls_switch_layout():
    values = eden.controls("abc")
    assert values["player_0_button_a"] == '"button:1,guid:abc,port:0,engine:sdl"'  # A on the right (Xbox B)
    assert values["player_0_button_b"] == '"button:0,guid:abc,port:0,engine:sdl"'
    assert values["player_0_button_dup"] == '"hat:0,direction:up,guid:abc,port:0,engine:sdl"'
    assert values["player_0_button_zr"].startswith('"axis:5,threshold:0.500000')
    assert values["player_0_lstick"].startswith('"axis_x:0,axis_y:1') and values["player_0_connected"] == "true"


def test_merge_ini_keeps_the_rest():
    text = "[Controls]\nplayer_0_button_a\\default=true\nplayer_0_button_a=\"keyboard\"\nother=1\n[UI]\nx=2\n"
    merged = eden.merge_ini(text, "Controls", {"player_0_button_a": '"sdl"', "new": "3"})
    lines = merged.splitlines()
    assert 'player_0_button_a="sdl"' in lines and "player_0_button_a\\default=false" in lines
    assert "other=1" in lines and "x=2" in lines and lines.index("new=3") < lines.index("[UI]")
    assert eden.merge_ini("", "UI", {"a": "1"}).splitlines() == ["[UI]", "a\\default=false", "a=1"]


def test_prepare_puts_everything_on_the_drive(emu):
    (emu.bios / "switch" / "firmware").mkdir(parents=True)
    (emu.bios / "switch" / "prod.keys").write_text("keys")
    (emu.bios / "switch" / "firmware" / "abc.nca").write_text("nca")
    env = eden.prepare(emu)
    assert env["XDG_DATA_HOME"] == str(emu.saves / "switch") and env["XDG_CONFIG_HOME"] == str(emu.config / "switch")
    assert (emu.saves / "switch" / "eden" / "keys" / "prod.keys").read_text() == "keys"
    link = emu.saves / "switch" / "eden" / "nand" / "system" / "Contents" / "registered" / "abc.nca"
    assert link.is_symlink() and link.read_text() == "nca"
    ini = (emu.config / "switch" / "eden" / "qt-config.ini").read_text()
    assert f"guid:{eden.sdl_guid()}" in ini and "firstStart=false" in ini and "fullscreen=true" in ini
    eden.prepare(emu)  # again: no duplicate keys
    ini = (emu.config / "switch" / "eden" / "qt-config.ini").read_text()
    assert ini.count("\nfirstStart=false") == 1


class Response:
    def __init__(self, status=200, content=b"", data=None):
        self.status_code, self.content, self._data = status, content, data

    def json(self):
        return self._data


RELEASE = [{"assets": [{"name": "Eden-Linux-v9-aarch64-clang-pgo.AppImage", "browser_download_url": "arm"},
                       {"name": "Eden-Linux-v9-amd64-clang-pgo.AppImage", "browser_download_url": "x86"}]}]


def test_download_url():
    assert eden.download_url(lambda u: Response(data=RELEASE), "x86_64") == "x86"
    assert eden.download_url(lambda u: Response(data=RELEASE), "aarch64") == "arm"
    assert eden.download_url(lambda u: Response(data=[]), "x86_64").startswith("https://stable.eden-emu.dev/")
    assert eden.download_url(lambda u: Response(), "riscv64") is None


def test_install_unpacks_the_appimage(tmp_path):
    def get(url):
        return Response(data=RELEASE) if "api" in url else Response(200, b"\x7fELF image")

    def runner(cmd, cwd=None, **kw):
        assert cmd[1] == "--appimage-extract" and (tmp_path / "eden" / "Eden.AppImage").exists()
        (tmp_path / "eden" / "squashfs-root").mkdir()
        (tmp_path / "eden" / "squashfs-root" / "AppRun").write_text("#!/bin/sh\n")
        return subprocess.CompletedProcess(cmd, 0)

    folder = tmp_path / "eden"
    assert not eden.available(folder)
    assert eden.install(folder, get, runner, "x86_64") == folder / "app" / "AppRun"
    assert eden.available(folder) and not (folder / "Eden.AppImage").exists()
    assert eden.install(folder, lambda u: 1 / 0, runner, "x86_64") == folder / "app" / "AppRun"  # already there


def test_install_failures(tmp_path):
    folder = tmp_path / "eden"
    assert eden.install(folder, lambda u: Response(404) if "AppImage" in u else Response(data=RELEASE),
                        machine="x86_64") is None
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1)  # noqa: E731 - extracts nothing
    assert eden.install(folder, lambda u: Response(data=RELEASE) if "api" in u else Response(200, b"\x7fELF"),
                        bad, "x86_64") is None
    assert not eden.available(folder) and not (folder / "squashfs-root").exists()


def test_launch_command(tmp_path, emu):
    folder = tmp_path / "eden"
    (folder / "app").mkdir(parents=True)
    (folder / "app" / "AppRun").write_text("x")
    started = []
    game = scan(emu, BY_ID["switch"])[0]
    ok, _ = eden.launch(game, emu, tmp_path / "data", tmp_path / "logs",
                        popen=lambda cmd, **kw: started.append((cmd, kw["env"])), folder=folder)
    cmd, env = started[0]
    assert ok and cmd[1:4] == ["SteamLaunch", f"AppId={game.appid}", "--"]
    assert cmd[4:] == [str(folder / "app" / "AppRun"), "-f", "-g", str(game.path)]
    assert env["XDG_DATA_HOME"] == str(emu.saves / "switch")
    assert eden.launch(game, emu, tmp_path, tmp_path, folder=tmp_path / "none")[0] is False


def test_app_downloads_eden_then_starts_the_game(qtbot, emu, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    folder = tmp_path / "eden"
    monkeypatch.setattr(eden, "install_dir", lambda: folder)
    started = []
    monkeypatch.setattr(eden, "launch", lambda game, *a, **k: (started.append(game.name), (True, "Starting"))[1])
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    window.show_shell()

    def installer():
        (folder / "app").mkdir(parents=True)
        (folder / "app" / "AppRun").write_text("x")
        return folder / "app" / "AppRun"

    pages["Games"].eden_installer = installer
    game = scan(emu, BY_ID["switch"])[0]
    ok, message = window.launch_rom(game)
    assert ok and message == "Downloading the Switch emulator (Eden)…" and window.launch_overlay.isVisible()
    qtbot.waitUntil(lambda: started == ["Mario Kart 8 Deluxe"], timeout=5000)
    assert window.game_watcher.appid == game.appid
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert not menu.state_row.isVisibleTo(menu) and not menu.speed_row.isVisibleTo(menu)  # RetroArch only

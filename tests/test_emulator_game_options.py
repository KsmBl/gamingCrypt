"""Emulated games: several discs as one game (switchable in the quick menu), core and memory card per game."""

import copy
import json

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths, disc_number, scan
from gamingcrypt.emulation.systems import BY_ID

FF7 = "Final Fantasy VII - German Retranslation (v1.0)(Disc {n})"


@pytest.fixture
def emu(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    for n in (1, 2, 3):  # as on the handheld: .cue + .bin per disc
        stem = FF7.format(n=n)
        (p.roms / "psx" / f"{stem}.bin").write_bytes(b"x" * 100)
        (p.roms / "psx" / f"{stem}.cue").write_text(f'FILE "{stem}.bin" BINARY\n')
    (p.roms / "psx" / "Crash Bandicoot (USA).chd").write_bytes(b"x")
    return p


def test_disc_numbers():
    assert disc_number("Game (Disc 2).cue") == 2 and disc_number("Game [CD3].chd") == 3
    assert disc_number("Game (Disk 1 of 2).iso") == 1 and disc_number("Game(Disc 1).cue") == 1
    assert disc_number("Discworld (USA).cue") is None


def test_discs_are_one_game(emu):
    games = scan(emu, BY_ID["psx"])
    assert [g.name for g in games] == ["Crash Bandicoot", "Final Fantasy VII - German Retranslation"]
    ff7 = games[1]
    assert [d.name for d in ff7.discs] == [f"{FF7.format(n=n)}.cue" for n in (1, 2, 3)]
    assert ff7.path.suffix == ".m3u" and ff7.path.read_text().splitlines() == [str(d) for d in ff7.discs]
    assert ff7.size == 3 * (100 + len(f'FILE "{FF7.format(n=1)}.bin" BINARY\n'))
    assert scan(emu, BY_ID["psx"])[1].appid == ff7.appid  # stable: favorites, play time
    assert games[0].discs == ()


def test_a_single_disc_stays_a_game(emu):
    (emu.roms / "psx" / "Other (Disc 1).chd").write_bytes(b"x")
    assert "Other" in [g.name for g in scan(emu, BY_ID["psx"])]


def test_disc_commands():
    assert retroarch.disc_commands(0, 2) == ["DISK_EJECT_TOGGLE", "DISK_NEXT", "DISK_NEXT", "DISK_EJECT_TOGGLE"]
    assert retroarch.disc_commands(2, 1) == ["DISK_EJECT_TOGGLE", "DISK_PREV", "DISK_EJECT_TOGGLE"]
    assert retroarch.disc_commands(1, 1) == []


def test_current_disc_from_retroarchs_memory(emu, tmp_path):
    ff7 = scan(emu, BY_ID["psx"])[1]
    core = emu.cores / "swanstation_libretro.so"
    assert retroarch.current_disc(emu, ff7, core) == 0
    folder = emu.saves / "SwanStation"
    folder.mkdir()
    (folder / f"{ff7.path.stem}.ldci").write_text(json.dumps({"image_index": 1, "image_path": str(ff7.discs[1])}))
    assert retroarch.current_disc(emu, ff7, core) == 1


def test_memory_card_option_file(emu, tmp_path):
    (emu.cores / "swanstation_libretro.so").write_text("x")
    crash = scan(emu, BY_ID["psx"])[0]
    run = dict(popen=lambda cmd, **k: None, which=lambda n: "/usr/bin/retroarch")
    retroarch.launch(crash, emu, tmp_path / "d", tmp_path / "l", memory_card="shared", **run)
    options = retroarch.core_options_file(emu, crash)
    config = (emu.config / "gamingcrypt.cfg").read_text()
    assert f'core_options_path = "{options}"' in config and 'global_core_options = "true"' in config
    assert 'swanstation_MemoryCards_Card1Type = "Shared"' in options.read_text()
    options.write_text(options.read_text() + 'swanstation_GPU_Renderer = "Software"\n')  # RetroArch's own
    retroarch.launch(crash, emu, tmp_path / "d", tmp_path / "l", memory_card="own", **run)
    text = options.read_text()
    assert 'Card1Type = "Libretro"' in text and "Shared" not in text and "GPU_Renderer" in text
    retroarch.launch(crash, emu, tmp_path / "d", tmp_path / "l", **run)  # no choice: the core's default
    assert "core_options_path" not in (emu.config / "gamingcrypt.cfg").read_text()


def test_pcsx2_memory_cards():
    assert retroarch.MEMORY_CARDS["pcsx2"]["shared"] == {"pcsx2_shared_memory_cards": "enabled"}


@pytest.fixture
def window(qtbot, emu, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    launches, sent = [], []
    monkeypatch.setattr(retroarch, "launch", lambda game, paths, d, l, core=None, **k: launches.append(
        (game.name, core, k.get("memory_card"))) or (True, "Starting"))
    monkeypatch.setattr(retroarch, "send", lambda text, port=None: sent.append(text) or True)
    monkeypatch.setattr("time.sleep", lambda s: None)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    qtbot.waitUntil(lambda: "psx" in pages["Games"].home.system_cards)
    w._launches, w._sent, w._games = launches, sent, pages["Games"]
    w._ff7 = scan(emu, BY_ID["psx"])[1]
    return w


def test_game_page_options(qtbot, window):
    from gamingcrypt.ui.emulation_pages import RomGamePage

    page = RomGamePage(window._games, window._ff7)
    qtbot.addWidget(page)
    page.show()
    assert not page.options_panel.isVisible()
    page.options_button.click()  # as on a Steam game's page
    assert page.options_panel.isVisible() and not page.screen_combo.isVisible()  # widescreen: PS2 only
    assert page.core_combo.currentText() == "Automatic (SwanStation)" and "3 discs" in page.facts.text()
    assert page.card_combo.isVisible()  # SwanStation has memory card options
    page.card_combo.setCurrentIndex(1)
    page.core_combo.setCurrentIndex(page.core_combo.findData("pcsx_rearmed"))
    assert not page.card_combo.isVisible()  # PCSX ReARMed: none here
    profile = window.game_profiles.get(window._ff7.appid)
    assert profile["core"] == "pcsx_rearmed" and profile["memory_card"] == "shared"
    window.launch_rom(window._ff7)
    assert window._launches[-1] == ("Final Fantasy VII - German Retranslation", "pcsx_rearmed", "shared")
    page.core_combo.setCurrentIndex(0)
    assert "core" not in window.game_profiles.get(window._ff7.appid)


def test_disc_switching_in_the_quick_menu(qtbot, window):
    window.launch_rom(window._ff7)
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.disc_row.isVisibleTo(menu) and menu.disc_label.text() == "💿  Disc 1 of 3"
    assert not menu.disc_prev.isEnabled()
    menu.disc_next.click()
    qtbot.waitUntil(lambda: len(window._sent) == 3)
    assert window._sent == ["DISK_EJECT_TOGGLE", "DISK_NEXT", "DISK_EJECT_TOGGLE"] and menu.isVisible()
    assert menu.disc_label.text() == "💿  Disc 2 of 3" and window.disc_index == 1
    menu.close_menu()
    window.toggle_quick_menu()
    assert menu.disc_label.text() == "💿  Disc 2 of 3"


def test_no_disc_row_for_one_disc(qtbot, window, emu):
    window.launch_rom(scan(emu, BY_ID["psx"])[0])
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    assert not window.quick_menu.disc_row.isVisibleTo(window.quick_menu)


def test_input_lag_settings():
    snes = retroarch.lag_settings("snes")
    assert snes["preemptive_frames_enable"] == "true" and snes["run_ahead_frames"] == "1"
    assert snes["video_max_swapchain_images"] == "2" and snes["input_poll_type_behavior"] == "2"
    assert retroarch.lag_settings("snes", "normal")["preemptive_frames_enable"] == "false"
    ps2 = retroarch.lag_settings("ps2")  # heavy: no extra work, but late input
    assert ps2["preemptive_frames_enable"] == "false" and ps2["input_poll_type_behavior"] == "2"


def test_launch_writes_the_lag_settings(emu, tmp_path):
    (emu.cores / "snes9x_libretro.so").write_text("x")
    (emu.roms / "snes" / "Mario.sfc").write_text("x")
    mario = scan(emu, BY_ID["snes"])[0]
    run = dict(popen=lambda cmd, **k: None, which=lambda n: "/usr/bin/retroarch")
    retroarch.launch(mario, emu, tmp_path / "d", tmp_path / "l", **run)
    assert 'preemptive_frames_enable = "true"' in (emu.config / "gamingcrypt.cfg").read_text()
    retroarch.launch(mario, emu, tmp_path / "d", tmp_path / "l", input_lag="normal", **run)
    assert 'preemptive_frames_enable = "false"' in (emu.config / "gamingcrypt.cfg").read_text()


def test_input_lag_option_on_the_game_page(qtbot, window, emu):
    from gamingcrypt.ui.emulation_pages import RomGamePage

    page = RomGamePage(window._games, window._ff7)
    qtbot.addWidget(page)
    assert page.lag_combo is None  # PS1: heavy - not offered
    (emu.roms / "snes" / "Mario.sfc").write_text("x")
    mario = scan(emu, BY_ID["snes"])[0]
    page = RomGamePage(window._games, mario)
    qtbot.addWidget(page)
    page.lag_combo.setCurrentIndex(1)
    assert window.game_profiles.get(mario.appid)["input_lag"] == "normal"

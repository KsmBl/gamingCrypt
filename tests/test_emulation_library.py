"""Emulation basics: folders on the encrypted drive, scanning, one library per system."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation.library import EMU_APPID_BASE, EmulationPaths, clean_name, scan, scan_all
from gamingcrypt.emulation.systems import BY_ID, SYSTEMS


def put(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def emu(tmp_path):
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    snes = paths.roms_for(BY_ID["snes"])
    put(snes / "Super Mario World (USA).sfc")
    put(snes / "Chrono_Trigger [!].smc")
    put(snes / "readme.txt")
    psx = paths.roms_for(BY_ID["psx"])
    put(psx / "Final Fantasy VII (Disc 1).cue", 'FILE "Final Fantasy VII (Disc 1).bin" BINARY')
    put(psx / "Final Fantasy VII (Disc 2).cue", 'FILE "Final Fantasy VII (Disc 2).bin" BINARY')
    put(psx / "Final Fantasy VII.m3u", "Final Fantasy VII (Disc 1).cue\nFinal Fantasy VII (Disc 2).cue\n")
    put(psx / "Crash Bandicoot (USA).chd")
    return paths


def test_folders(emu):
    for folder in ("roms", "bios", "cores", "saves", "states", "screenshots", "config"):
        assert (emu.root / folder).is_dir()
    assert all(emu.roms_for(s).is_dir() for s in SYSTEMS)


def test_scan_names_types_and_multi_disc(emu):
    snes = scan(emu, BY_ID["snes"])
    assert [g.name for g in snes] == ["Chrono Trigger", "Super Mario World"]  # tags gone, txt ignored
    psx = scan(emu, BY_ID["psx"])
    assert [g.name for g in psx] == ["Crash Bandicoot", "Final Fantasy VII"]  # the discs are one game
    assert psx[1].path.suffix == ".m3u"
    assert set(scan_all(emu)) == {"snes", "psx"}  # only systems with games
    assert clean_name("Zelda (USA) (Rev 1) [!].zip") == "Zelda"


def test_stable_ids_far_from_steam(emu):
    game = scan(emu, BY_ID["snes"])[0]
    again = scan(emu, BY_ID["snes"])[0]
    assert game.appid == again.appid and game.appid >= EMU_APPID_BASE and game.appid < 2**32
    assert len({g.appid for games in scan_all(emu).values() for g in games}) == 4


def test_unmounted_drive_has_no_games(tmp_path):
    assert scan_all(EmulationPaths(tmp_path / "nowhere")) == {}


# --- UI ---------------------------------------------------------------------------------

@pytest.fixture
def tab(qtbot, emu):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    cfg = copy.deepcopy(DEFAULTS)
    t = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
    qtbot.addWidget(t)
    t.show()
    t.reload_installed()
    qtbot.waitUntil(lambda: set(t.home.system_cards) == {"snes", "psx"})
    t._cfg = cfg
    return t


def test_one_library_card_per_system(qtbot, tab):
    snes = tab.home.system_cards["snes"]
    assert snes.isVisible() and snes.subtitle.text() == "2 games"
    snes.tapped.emit()
    page = tab.currentWidget()
    assert page.system.id == "snes" and len(page.cards) == 2
    page.search.setText("mario")
    assert len(page.shown) == 1
    card = page.cards[page.shown[0]]
    card.clicked.emit(card.game)
    rom_page = tab.currentWidget()
    assert rom_page.title.text() == "Super Mario World" and "Super Nintendo" in rom_page.facts.text()
    rom_page.favorite_button.click()
    assert tab.profiles.is_favorite(card.game.appid)
    rom_page.main_button.click()
    assert "isn't set up" in rom_page.status.text()  # until RetroArch is wired in


def test_settings_hides_a_system(qtbot, tab):
    from gamingcrypt.ui.settings_tab import SettingsTab

    settings = SettingsTab(tab._cfg, lambda c: None)
    qtbot.addWidget(settings)
    settings.libraries_changed.connect(tab.home.apply_libraries)
    settings.library_buttons["emu:psx"].click()
    assert tab._cfg["libraries"]["hidden"] == ["emu:psx"]
    assert not tab.home.system_cards["psx"].isVisible() and tab.home.system_cards["snes"].isVisible()


def test_default_pages_know_where_emulation_lives():
    from gamingcrypt import app

    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"]["mount_point"] = "/home/u/GamingCrypt"
    pages = app.default_pages(cfg)
    assert str(pages["Games"].emulation.root) == "/home/u/GamingCrypt/Emulation"
    cfg["unlock"]["mount_point"] = ""
    assert app.default_pages(cfg)["Games"].emulation is None

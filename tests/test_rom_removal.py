"""Removing an emulated game: asked twice, saves only when wanted - on its page and in Settings -> Storage."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import removal, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


@pytest.fixture
def emu(tmp_path):
    p = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    p.ensure()
    for n in (1, 2):
        stem = f"FF7 (Disc {n})"
        (p.roms / "psx" / f"{stem}.bin").write_bytes(b"x" * 1000)
        (p.roms / "psx" / f"{stem}.cue").write_text(f'FILE "{stem}.bin" BINARY\n')
    (p.roms / "snes" / "Mario.sfc").write_bytes(b"m" * 500)
    (p.roms / "snes" / "Zelda.sfc").write_bytes(b"z" * 500)
    (p.saves / "Snes9x").mkdir()
    (p.saves / "Snes9x" / "Mario.srm").write_bytes(b"s" * 8)
    (p.states / "Snes9x").mkdir()
    (p.states / "Snes9x" / "Mario.state1").write_bytes(b"s" * 50)
    (p.states / "Snes9x" / "Mario World.state").write_bytes(b"other game")  # not "Mario"
    (p.saves / "FF7.srm").write_bytes(b"card")
    return p


def test_plan_for_one_file(emu):
    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    plan = removal.plan(emu, mario)
    assert plan.files == [emu.roms / "snes" / "Mario.sfc"] and plan.files_size == 500
    assert sorted(f.name for f in plan.saves) == ["Mario.srm", "Mario.state1"]


def test_plan_for_several_discs(emu):
    ff7 = scan(emu, BY_ID["psx"])[0]
    plan = removal.plan(emu, ff7)
    names = sorted(f.name for f in plan.files)
    assert names == ["FF7 (Disc 1).bin", "FF7 (Disc 1).cue", "FF7 (Disc 2).bin", "FF7 (Disc 2).cue", "FF7.m3u"]
    assert [f.name for f in plan.saves] == ["FF7.srm"]


def test_remove_keeps_saves_unless_asked(emu):
    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    retroarch.write_core_options(retroarch.core_options_file(emu, mario), {"a": "b"})
    freed = removal.remove(emu, mario, with_saves=False)
    assert freed == 500 and not (emu.roms / "snes" / "Mario.sfc").exists()
    assert (emu.saves / "Snes9x" / "Mario.srm").exists() and not retroarch.core_options_file(emu, mario).exists()
    zelda = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Zelda")
    assert (emu.roms / "snes" / "Zelda.sfc").exists() and zelda


def test_remove_with_saves(emu):
    ff7 = scan(emu, BY_ID["psx"])[0]
    removal.remove(emu, ff7, with_saves=True)
    assert not list((emu.roms / "psx").iterdir()) and not (emu.saves / "FF7.srm").exists()
    assert (emu.states / "Snes9x" / "Mario World.state").exists()


@pytest.fixture
def tab(qtbot, emu):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    t = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(emu.root))
    qtbot.addWidget(t)
    t.resize(1280, 800)
    t.show()
    qtbot.waitUntil(lambda: "snes" in t.home.system_cards)
    return t


def test_remove_from_the_game_page(qtbot, tab, emu):
    from gamingcrypt.ui.emulation_pages import RomGamePage

    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    tab.open_rom(mario)
    page = tab.currentWidget()
    assert isinstance(page, RomGamePage) and not page.remove_button.isVisible()
    page.options_button.click()
    page.remove_button.click()
    confirm = page.confirm
    assert confirm is not None and "Really remove Mario?" in confirm.question.text()
    assert (emu.roms / "snes" / "Mario.sfc").exists()  # nothing yet
    assert confirm.saves_button.isVisible() and "2 files" in confirm.saves_button.text()
    confirm.cancel_button.click()
    assert page.confirm is None and (emu.roms / "snes" / "Mario.sfc").exists()
    page.remove_button.click()
    page.confirm.saves_button.click()  # the saves too
    assert page.confirm.saves_button.text().startswith("☑")
    page.confirm.remove_button.click()
    qtbot.waitUntil(lambda: tab.currentWidget() is not page)
    assert not (emu.roms / "snes" / "Mario.sfc").exists() and not (emu.saves / "Snes9x" / "Mario.srm").exists()
    assert "Mario removed" in tab.home.notice.text()
    qtbot.waitUntil(lambda: all(g.name != "Mario" for g in tab.roms.get("snes", [])))


def test_storage_lists_and_removes_emulated_games(qtbot, emu):
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, games_running=lambda: set(), emulation_fn=lambda: emu)
    qtbot.addWidget(page)
    page.show()
    changed = []
    page.roms_changed.connect(lambda: changed.append(True))
    page.refresh()
    qtbot.waitUntil(lambda: len(page.rom_rows) == 3)
    assert page.roms_heading.isVisible()
    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    text, remove = page.rom_rows[mario.appid]
    assert "Mario\nSNES" in text.text() and "saves" in text.text()
    remove.click()
    assert page.confirm is not None and (emu.roms / "snes" / "Mario.sfc").exists()
    page.confirm.remove_button.click()  # without the saves
    qtbot.waitUntil(lambda: bool(changed) and len(page.rom_rows) == 2)
    assert (emu.saves / "Snes9x" / "Mario.srm").exists() and "saves are kept" in page.status.text()


def test_storage_doesnt_remove_a_running_game(qtbot, emu):
    from gamingcrypt.ui.storage_page import StoragePage

    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    page = StoragePage(lambda: None, games_running=lambda: {mario.appid}, emulation_fn=lambda: emu)
    qtbot.addWidget(page)
    page.refresh()
    qtbot.waitUntil(lambda: len(page.rom_rows) == 3)
    page.rom_rows[mario.appid][1].click()
    assert page.confirm is None and "Close the game first" in page.status.text()

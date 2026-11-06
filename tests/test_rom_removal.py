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


def test_a_failed_rom_removal_stays_on_the_page_and_says_why(qtbot, tab, emu, monkeypatch):
    from gamingcrypt.emulation import removal

    def fails(*a, **k):
        raise OSError("Device or resource busy")

    monkeypatch.setattr(removal, "remove", fails)
    mario = next(g for g in scan(emu, BY_ID["snes"]) if g.name == "Mario")
    tab.open_rom(mario)
    page = tab.currentWidget()
    page.options_button.click()
    page.remove_button.click()
    page.confirm.remove_button.click()
    page.confirm.keep_button.click()
    qtbot.waitUntil(lambda: "resource busy" in page.status.text())
    assert tab.currentWidget() is page and page.confirm is None and page.status.property("error")
    assert (emu.roms / "snes" / "Mario.sfc").exists() and "removed" not in tab.home.notice.text()


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
    assert not confirm.keep_button.isVisible() and not confirm.none.isVisible()
    confirm.remove_button.click()
    # it has saves: asked on its own, before anything is deleted
    assert "Delete them too?" in confirm.question.text() and "Mario has" in confirm.question.text()
    assert "save state" in confirm.question.text() or "memory card" in confirm.question.text()
    assert confirm.keep_button.isVisible() and confirm.delete_saves_button.isVisible()
    assert not confirm.remove_button.isVisible() and (emu.roms / "snes" / "Mario.sfc").exists()
    confirm.cancel_button.click()
    assert page.confirm is None and (emu.roms / "snes" / "Mario.sfc").exists()
    page.remove_button.click()
    page.confirm.remove_button.click()
    page.confirm.delete_saves_button.click()  # the saves too
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
    text, remove, move = page.rom_rows[mario.appid]
    assert move.isHidden()  # no USB stick in: nowhere to move it
    assert "Mario\nSNES" in text.text() and "saves" in text.text()
    remove.click()
    assert page.confirm is not None and (emu.roms / "snes" / "Mario.sfc").exists()
    page.confirm.remove_button.click()
    assert (emu.roms / "snes" / "Mario.sfc").exists()  # asked about the saves first
    page.confirm.keep_button.click()  # without the saves
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


def test_a_game_without_saves_is_removed_after_one_question(qtbot, emu):
    from gamingcrypt.ui.remove_rom import RemoveConfirm

    game = next(g for g in scan(emu, BY_ID["snes"]) if g.name != "Mario" and not removal.save_files(emu, g))
    confirm = RemoveConfirm(emu, game)
    qtbot.addWidget(confirm)
    confirm.show()
    assert confirm.none.isVisible() and not confirm.keep_button.isVisible()
    said = []
    confirm.removed.connect(said.append)
    confirm.remove_button.click()
    qtbot.waitUntil(lambda: bool(said))
    assert "removed" in said[0] and "kept" not in said[0] and not game.path.exists()


def test_what_a_game_has_saved(emu):
    from gamingcrypt.ui.remove_rom import saves_text

    states, card = emu.states / "Mario.state", emu.saves / "Snes9x" / "Mario.srm"
    extras = [emu.states / "Mario.state.png", emu.states / "Mario.state.time", emu.states / "Mario.state3"]
    assert saves_text(emu, [states, *extras, card]) == "2 save states and its memory card"
    assert saves_text(emu, [states]) == "1 save state" and saves_text(emu, [card]) == "its memory card"

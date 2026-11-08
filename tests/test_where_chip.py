"""A game's page says which stick it's on: a fact chip "🔌 On STICK" - "· not in" while it's out, none
on the encrypted drive."""

import pytest

from gamingcrypt import moving
from gamingcrypt.system.removable import Removable
from tests.test_code_dialogs import rect_in
from tests.test_remembered_games import config, drive, make_tab, names, stick  # noqa: F401 - fixtures

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def chips(page) -> list[str]:
    return [c.text() for c in page.facts.chips()]


def open_game(tab, name):
    game = next(g for games in [*tab.roms.values(), tab.pc_games()] for g in games if g.name == name)
    if hasattr(game, "system"):
        tab.open_rom(game)
    else:
        tab.open_windows_game(game)
    return tab.currentWidget()


@pytest.mark.parametrize("w,h", SCREENS)
@pytest.mark.parametrize("name", ["Earthbound", "Celeste"])
def test_on_its_page(qtbot, drive, config, stick, name, w, h):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    tab.resize(w, h)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: name in names(tab))
    page = open_game(tab, name)
    qtbot.wait(20)
    assert chips(page)[1] == "🔌 On STICK"  # right after what it is
    chip = next(c for c in page.facts.chips() if c.text() == "🔌 On STICK")
    assert chip.isVisible()
    where = rect_in(chip, tab)
    assert tab.rect().contains(where), f"the chip is off the {w}x{h} page"


def test_out_and_in_again(qtbot, drive, config, stick):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    page = open_game(tab, "Earthbound")
    tab.set_drives([])
    qtbot.waitUntil(lambda: "🔌 On STICK · not in" in chips(page))
    assert chips(page).count("🔌 On STICK · not in") == 1 and "🔌 On STICK" not in chips(page)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "🔌 On STICK" in chips(page))
    assert not any("not in" in c for c in chips(page))


def test_moved_onto_the_drive_no_chip(qtbot, drive, config, stick):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    moving.move(tab.roms["snes"][0], moving.Place(None), tab.emulation)
    tab.reload_roms()
    qtbot.waitUntil(lambda: tab.roms["snes"][0].removable == "")
    page = open_game(tab, "Earthbound")
    assert not any(" On " in c for c in chips(page))


def test_an_sd_card_and_a_drive(qtbot, drive, config, tmp_path):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    card = Removable(tmp_path / "CARD", "sd", "CARD", uuid="5")
    ssd = Removable(tmp_path / "SSD", "drive", "SSD", uuid="6")
    for d, rom in ((card, "Zelda.sfc"), (ssd, "Metroid.sfc")):
        (d.mount / "roms" / "snes").mkdir(parents=True)
        (d.mount / "roms" / "snes" / rom).write_bytes(b"x")
    tab.set_drives([card, ssd])
    qtbot.waitUntil(lambda: {"Zelda", "Metroid"} <= set(names(tab)))
    assert "💾 On CARD" in chips(open_game(tab, "Zelda"))
    tab.back()
    assert "🖴 On SSD" in chips(open_game(tab, "Metroid"))


def test_a_windows_games_facts_rewritten_keep_it(qtbot, drive, config, stick):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Celeste" in names(tab))
    page = open_game(tab, "Celeste")
    page._show_facts()  # (a start file chosen: the facts anew)
    assert chips(page).count("🔌 On STICK") == 1

"""Options → Saves on an emulated game: every save state on its own line - its picture, slot, when,
how long was played - and deleted on its own; the others and the game's saves stay."""

import pytest
from PySide6.QtCore import QPoint, QRect

from gamingcrypt import saves
from gamingcrypt.emulation import savestates
from gamingcrypt.emulation.library import EmulationPaths
from tests.test_saves import confirm, open_page, people, rom, rom_save  # noqa: F401 - fixtures

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def states_of(root, user, rom):  # noqa: F811
    return [s.slot for s in savestates.slots(EmulationPaths(root, user), rom) if not s.empty]


@pytest.fixture
def root(tmp_path, rom):  # noqa: F811
    """The admin with states in slots 1, 3 and 9 (RetroArch's .state1 .state3 .state9 = slots 0, 2, 8),
    a picture and play time with the first, a cartridge save - Mia with one state of her own."""
    root = tmp_path / "Emulation"
    for index in (1, 3, 9):
        rom_save(root, "", f"Game.state{index}", f"state {index}")
    rom_save(root, "", "Game.state1.time", "3600")
    from PySide6.QtGui import QColor, QImage

    picture = QImage(160, 120, QImage.Format.Format_RGB32)
    picture.fill(QColor("#3a7"))
    target = EmulationPaths(root, "").states / "Game.state1.png"
    picture.save(str(target))
    rom_save(root, "", "core/Game.srm", "cartridge", "saves")
    rom_save(root, "u1", "Game.state2", "Mia's")
    return root


def test_one_state_deleted_the_others_stay(root, rom):  # noqa: F811
    assert states_of(root, "", rom) == [0, 2, 8]
    assert savestates.delete(EmulationPaths(root, ""), rom, 2)
    assert states_of(root, "", rom) == [0, 8]
    assert not savestates.delete(EmulationPaths(root, ""), rom, 2)  # (not there any more)
    assert savestates.delete(EmulationPaths(root, ""), rom, 0)
    states = EmulationPaths(root, "").states
    assert not (states / "Game.state1.png").exists() and not (states / "Game.state1.time").exists()  # its picture too
    assert (EmulationPaths(root, "").saves / "core/Game.srm").read_text() == "cartridge"  # the game's save stays
    assert states_of(root, "u1", rom) == [1]  # Mia's are hers


def test_the_overview_has_each_users_states(root, rom):  # noqa: F811
    found = {row.user: row for row in saves.overview(saves.RomSaves(root, rom), ["", "u1"])}
    assert [s.slot for s in found[""].states] == [0, 2, 8] and found[""].states[0].played == 3600
    assert [s.slot for s in found["u1"].states] == [1]


@pytest.mark.parametrize("w,h", SCREENS)
def test_on_the_saves_page(qtbot, root, rom, people, w, h):  # noqa: F811
    tab, page = open_page(qtbot, rom, saves.RomSaves(root, rom), people, None)
    tab.resize(w, h)
    qtbot.wait(30)
    lines = {k[2]: b for k, b in page.buttons.items() if k[0] == "" and k[1] == "state"}
    assert sorted(lines) == ["0", "2", "8"]
    texts = [lb.text() for lb in page.inner.findChildren(type(page.note)) if lb.text().startswith("Slot ")]
    assert texts[0].startswith("Slot 1  ·  ") and texts[0].endswith("\n1 h 00 min played")
    assert any(t.startswith("Slot 9  ·  ") for t in texts)
    assert "Save states · 3" in [lb.text() for lb in page.inner.findChildren(type(page.note))]
    for button in lines.values():  # the 🗑 of each line inside the page, not cut off on the right
        where = QRect(button.mapTo(tab, QPoint(0, 0)), button.size())
        assert where.right() <= tab.width() and where.left() >= 0, f"🗑 off the {w}x{h} page"
    lines["2"].click()
    confirm(qtbot, page, "Delete save state 3 of Game")
    qtbot.waitUntil(lambda: sorted(k[2] for k in page.buttons if k[0] == "" and k[1] == "state") == ["0", "8"])
    assert "Save state 3 deleted" in page.status.text()
    assert states_of(root, "", rom) == [0, 8] and states_of(root, "u1", rom) == [1]


def test_a_user_deletes_their_own_only(qtbot, root, rom, people):  # noqa: F811
    tab, page = open_page(qtbot, rom, saves.RomSaves(root, rom), people, people[1])
    lines = {k: b for k, b in page.buttons.items() if k[1] == "state"}
    assert list(lines) == [("u1", "state", "1")]  # only hers
    next(iter(lines.values())).click()
    confirm(qtbot, page, "Delete save state 2 of Game")
    qtbot.waitUntil(lambda: not any(k[1] == "state" for k in page.buttons))
    assert states_of(root, "u1", rom) == [] and states_of(root, "", rom) == [0, 2, 8]


def test_not_while_the_game_runs(qtbot, root, rom, people, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    tab, page = open_page(qtbot, rom, saves.RomSaves(root, rom), people, None)
    monkeypatch.setattr(page, "window", lambda: SimpleNamespace(game_watcher=SimpleNamespace(active=True)))
    page.buttons[("", "state", "0")].click()
    confirm(qtbot, page, "Delete save state 1")
    assert "Close the running game first" in page.status.text() and states_of(root, "", rom) == [0, 2, 8]


def test_a_windows_game_has_no_states_lines(qtbot, tmp_path, people):  # noqa: F811
    from tests.test_saves import make_prefix
    from gamingcrypt.wine.library import WindowsGame

    folder = tmp_path / "Windows Games" / "Hollow Knight"
    folder.mkdir(parents=True)
    game = WindowsGame(folder, "Hollow Knight")
    make_prefix(game, "")
    _tab, page = open_page(qtbot, game, saves.PrefixSaves(game), people, None)
    assert not any(k[1] == "state" for k in page.buttons)

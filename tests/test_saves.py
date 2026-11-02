"""A game's saves: backed up, restored, copied between users, deleted - nothing is lost on the way."""

import os
from pathlib import Path

import pytest

from gamingcrypt import saves
from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.emulation.systems import SYSTEMS
from gamingcrypt.wine import library
from gamingcrypt.wine.library import WindowsGame


def make_prefix(game, user, content="save", size=0):
    prefix = library.prefix_dir(game, user)
    documents = prefix / "pfx" / "drive_c" / "users" / "steamuser"
    documents.mkdir(parents=True)
    (documents / "save.dat").write_text(content)
    (prefix / "pfx" / "user.reg").write_text("[reg] " + content)
    (prefix / "pfx" / "dosdevices").mkdir()
    (prefix / "pfx" / "dosdevices" / "z:").symlink_to("/")
    (prefix / "pfx" / "dosdevices" / "c:").symlink_to("../drive_c")
    return prefix


def saved(game, user):
    return (library.prefix_dir(game, user) / "pfx/drive_c/users/steamuser/save.dat").read_text()


@pytest.fixture
def game(tmp_path):
    folder = tmp_path / "Windows Games" / "Hollow Knight"
    folder.mkdir(parents=True)
    (folder / "game.exe").write_text("x")
    return WindowsGame(folder, "Hollow Knight")


@pytest.fixture
def box(game):
    return saves.PrefixSaves(game)


def test_overview_lists_users_and_who_else_has_saves(game, box):
    make_prefix(game, "", "admin's")
    make_prefix(game, "gone", "a deleted user's")
    rows = {r.user: r for r in saves.overview(box, ["", "u1"])}
    assert set(rows) == {"", "u1", "gone"}
    assert rows[""].has_saves and rows[""].size > 0 and rows[""].changed > 0
    assert not rows["u1"].has_saves and rows["u1"].size == 0


def test_copy_to_a_user_without_saves(game, box):
    make_prefix(game, "", "admin's")
    saves.copy_to(box, "", "u1")
    assert saved(game, "u1") == "admin's" and saved(game, "") == "admin's"
    assert saves.backups(box, "u1") == []  # nothing there to back up


def test_copy_keeps_links_as_links(game, box):
    make_prefix(game, "", "admin's")
    saves.copy_to(box, "", "u1")
    z = library.prefix_dir(game, "u1") / "pfx/dosdevices/z:"
    assert z.is_symlink() and os.readlink(z) == "/"  # not a copy of the whole computer
    assert (library.prefix_dir(game, "u1") / "pfx/dosdevices/c:").resolve().name == "drive_c"


def test_copy_over_saves_backs_them_up_first(game, box):
    make_prefix(game, "", "admin's")
    make_prefix(game, "u1", "mine")
    saves.copy_to(box, "", "u1")
    assert saved(game, "u1") == "admin's"
    backup = saves.backups(box, "u1")[0]
    assert (backup.path / "pfx/drive_c/users/steamuser/save.dat").read_text() == "mine"
    saves.restore(box, "u1", backup)
    assert saved(game, "u1") == "mine"
    assert any((b.path / "pfx/drive_c/users/steamuser/save.dat").read_text() == "admin's"
               for b in saves.backups(box, "u1"))  # and what was replaced by that


def test_a_failed_copy_leaves_everything_as_it_was(game, box, monkeypatch):
    make_prefix(game, "", "admin's")
    make_prefix(game, "u1", "mine")

    def broken(source, target, **_kw):
        Path(target).mkdir(parents=True)
        (Path(target) / "half.dat").write_text("half")
        raise OSError("the drive is full")

    monkeypatch.setattr(saves.shutil, "copytree", broken)
    with pytest.raises(saves.SaveError, match="nothing was replaced"):
        saves.copy_to(box, "", "u1")
    monkeypatch.undo()
    assert saved(game, "u1") == "mine" and saved(game, "") == "admin's"
    assert saves.backups(box, "u1") == []
    assert list((box.root / library.BACKUPS / saves.WORK).iterdir()) == []  # no half copy left


def test_not_enough_room_is_said_before_anything_happens(game, box, monkeypatch):
    make_prefix(game, "", "admin's")
    make_prefix(game, "u1", "mine")
    monkeypatch.setattr(saves.shutil, "disk_usage", lambda _p: type("U", (), {"free": 1024})())
    with pytest.raises(saves.SaveError, match="free space"):
        saves.copy_to(box, "", "u1")
    assert saved(game, "u1") == "mine" and saves.backups(box, "u1") == []


def test_only_the_newest_backups_are_kept(game, box, monkeypatch):
    make_prefix(game, "", "admin's")
    clock = iter(["20260101-10000" + str(i) for i in range(5)])
    monkeypatch.setattr(saves.time, "strftime", lambda _f: next(clock))
    for _ in range(5):
        saves.back_up(box, "")
    names = [b.path.name for b in saves.backups(box, "")]
    assert names == ["20260101-100004", "20260101-100003", "20260101-100002"] and len(names) == saves.MAX_BACKUPS


def test_a_backup_in_the_same_second_gets_its_own_folder(game, box, monkeypatch):
    make_prefix(game, "", "admin's")
    monkeypatch.setattr(saves.time, "strftime", lambda _f: "20260101-100000")
    first, second = saves.back_up(box, ""), saves.back_up(box, "")
    assert first.path != second.path and len(saves.backups(box, "")) == 2


def test_delete_keeps_the_backups(game, box):
    make_prefix(game, "u1", "mine")
    backup = saves.back_up(box, "u1")
    saves.delete(box, "u1")
    assert not box.has("u1") and saves.backups(box, "u1")[0].path == backup.path
    row = next(r for r in saves.overview(box, []) if r.user == "u1")  # still listed: it has a backup
    assert not row.has_saves and len(row.backups) == 1
    saves.restore(box, "u1", backup)
    assert saved(game, "u1") == "mine"
    saves.delete_backup(saves.backups(box, "u1")[0])
    assert saves.backups(box, "u1") == []


def test_one_at_a_time(game, box):
    make_prefix(game, "", "admin's")
    assert saves._working.acquire(blocking=False)
    try:
        with pytest.raises(saves.SaveError, match="still running"):
            saves.back_up(box, "")
        (box.root / library.BACKUPS / saves.WORK).mkdir(parents=True)
        (box.root / library.BACKUPS / saves.WORK / "running").mkdir()
        saves.overview(box, [])
        assert (box.root / library.BACKUPS / saves.WORK / "running").exists()  # not tidied away beneath it
    finally:
        saves._working.release()
    saves.overview(box, [])
    assert not (box.root / library.BACKUPS / saves.WORK).exists()


def test_cut_off_in_the_middle_of_a_swap_the_old_saves_come_back(game, box):
    prefix = make_prefix(game, "u1", "mine")
    os.replace(prefix, prefix.with_name(prefix.name + saves.REPLACED))
    saves.overview(box, ["u1"])
    assert saved(game, "u1") == "mine"
    old = prefix.with_name(prefix.name + saves.REPLACED)
    old.mkdir()  # (swapped, but the old one not gone yet)
    saves.overview(box, ["u1"])
    assert not old.exists() and saved(game, "u1") == "mine"


def test_removing_a_game_takes_its_backups_only_when_asked_and_only_its_own(game, box, tmp_path):
    other_folder = game.path.parent / "Other"
    other_folder.mkdir()
    other = WindowsGame(other_folder, "Other")
    make_prefix(game, "u1", "mine")
    make_prefix(other, "u1", "other")
    saves.back_up(box, "u1")
    other_backup = saves.back_up(saves.PrefixSaves(other), "u1")
    assert [g.name for g in library.scan(game.path.parent)] == ["Hollow Knight", "Other"]  # no folder is a game
    (game.path / "again").mkdir()
    library.remove(game, with_saves=False)
    assert saves.backups(box, "u1")
    game.path.mkdir()
    library.remove(game, with_saves=True)
    assert saves.backups(box, "u1") == [] and other_backup.path.exists()


# --- emulated games ---------------------------------------------------------------------------
@pytest.fixture
def rom(tmp_path):
    system = next(s for s in SYSTEMS if s.emulator == "retroarch" and s.save_states)
    path = tmp_path / "Game.bin"
    path.write_bytes(b"x")
    return RomGame(system, path, "Game", 1)


def rom_save(root, user, name, content, folder="states"):
    paths = EmulationPaths(root, user)
    target = getattr(paths, folder) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def test_rom_saves_are_the_users_files_of_this_game(tmp_path, rom):
    root = tmp_path / "Emulation"
    rom_save(root, "", "Game.state1", "state")
    rom_save(root, "", "Game.state1.png", "picture")
    rom_save(root, "", "core/Game.srm", "cart", "saves")
    other = rom_save(root, "", "Other.state1", "someone else's game")
    box = saves.RomSaves(root, rom)
    assert box.owners() == [""] and box.has("") and not box.has("u1")
    saves.copy_to(box, "", "u1")
    states = EmulationPaths(root, "u1").states
    assert (states / "Game.state1").read_text() == "state" and (states / "Game.state1.png").read_text() == "picture"
    assert (EmulationPaths(root, "u1").saves / "core/Game.srm").read_text() == "cart"
    assert not (states / "Other.state1").exists() and other.exists()
    assert box.owners() == ["", "u1"]


def test_rom_copy_over_backs_up_replaces_all_and_can_go_back(tmp_path, rom):
    root = tmp_path / "Emulation"
    rom_save(root, "", "Game.state1", "admin's")
    mine = rom_save(root, "u1", "Game.state1", "mine")
    only_mine = rom_save(root, "u1", "Game.state5", "only mine")
    untouched = rom_save(root, "u1", "Other.state1", "another game")
    box = saves.RomSaves(root, rom)
    saves.copy_to(box, "", "u1")
    assert mine.read_text() == "admin's" and not only_mine.exists() and untouched.read_text() == "another game"
    saves.restore(box, "u1", saves.backups(box, "u1")[0])
    assert mine.read_text() == "mine" and only_mine.read_text() == "only mine"


def test_rom_delete_only_this_game_of_this_user(tmp_path, rom):
    root = tmp_path / "Emulation"
    admin = rom_save(root, "", "Game.state1", "admin's")
    mine = rom_save(root, "u1", "Game.state1", "mine")
    other = rom_save(root, "u1", "Other.state1", "another game")
    saves.delete(saves.RomSaves(root, rom), "u1")
    assert admin.exists() and not mine.exists() and other.exists()


# --- the page ---------------------------------------------------------------------------------
@pytest.fixture
def people():
    from gamingcrypt.users import User

    return [User("admin", "Admin", "pin", admin=True), User("u1", "Mia", "pin")]


def open_page(qtbot, game, box, people, me):
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.saves_page import SavesPage
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), user=me, people=lambda: people)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    page = SavesPage(tab, game, box)
    tab.push(page)
    qtbot.waitUntil(lambda: hasattr(page, "found"))
    return tab, page


def confirm(qtbot, page, text):
    from gamingcrypt.ui.modal import ConfirmBox

    box = next(b for b in page.findChildren(ConfirmBox) if b.isVisible())
    assert text in box.question.text()
    box.action_button.click()


def test_admin_sees_everybody_and_copies(qtbot, game, box, people):
    from gamingcrypt.ui.saves_page import CopyTarget

    make_prefix(game, "", "admin's")
    _tab, page = open_page(qtbot, game, box, people, people[0])
    assert [r.user for r in page.found] == ["", "u1"]
    assert ("u1", "backup", "") not in page.buttons  # no saves yet: nothing to back up
    page.buttons[("", "copy", "")].click()
    chooser = next(c for c in page.findChildren(CopyTarget) if c.isVisible())
    assert list(chooser.buttons) == ["u1"]
    chooser.buttons["u1"].click()
    confirm(qtbot, page, "Copy Admin's saves of Hollow Knight to Mia?")
    qtbot.waitUntil(lambda: "Copied to Mia" in page.status.text())
    assert saved(game, "u1") == "admin's"
    qtbot.waitUntil(lambda: next(r for r in page.found if r.user == "u1").has_saves)


def test_a_user_sees_only_their_own_and_cant_copy(qtbot, game, box, people):
    make_prefix(game, "", "the admin's secret")
    make_prefix(game, "u1", "mine")
    _tab, page = open_page(qtbot, game, box, people, people[1])
    assert [r.user for r in page.found] == ["u1"]
    assert ("u1", "copy", "") not in page.buttons and ("u1", "backup", "") in page.buttons
    assert "with the admin" in page.note.text()


def test_a_user_backs_up_restores_and_deletes(qtbot, game, box, people):
    make_prefix(game, "u1", "mine")
    _tab, page = open_page(qtbot, game, box, people, people[1])
    page.buttons[("u1", "backup", "")].click()
    qtbot.waitUntil(lambda: "Backed up" in page.status.text() and bool(page.found[0].backups))
    (library.prefix_dir(game, "u1") / "pfx/drive_c/users/steamuser/save.dat").write_text("newer")
    which = page.found[0].backups[0].path.name
    page.buttons[("u1", "restore", which)].click()
    confirm(qtbot, page, "backed up first")
    qtbot.waitUntil(lambda: "Restored" in page.status.text())
    assert saved(game, "u1") == "mine"
    qtbot.waitUntil(lambda: page.inner.isEnabled() and ("u1", "delete", "") in page.buttons)
    page.buttons[("u1", "delete", "")].click()
    confirm(qtbot, page, "Delete Mia's saves")
    qtbot.waitUntil(lambda: page.status.text() == "Deleted")
    assert not box.has("u1")


def test_a_failure_is_said_in_red_and_the_page_goes_on(qtbot, game, box, people, monkeypatch):
    make_prefix(game, "", "admin's")
    _tab, page = open_page(qtbot, game, box, people, people[0])

    def fail(*_a):
        raise saves.SaveError("Not enough free space")

    monkeypatch.setattr(saves, "back_up", fail)
    page.buttons[("", "backup", "")].click()
    qtbot.waitUntil(lambda: "free space" in page.status.text())
    assert page.status.property("error") is True
    qtbot.waitUntil(page.inner.isEnabled)


def test_not_while_a_game_runs(qtbot, game, box, people, monkeypatch):
    make_prefix(game, "", "admin's")
    _tab, page = open_page(qtbot, game, box, people, people[0])

    class Window:
        game_watcher = type("W", (), {"active": True})()

    monkeypatch.setattr(page, "window", lambda: Window())
    page.buttons[("", "backup", "")].click()
    assert "Close the running game" in page.status.text() and saves.backups(box, "") == []


def test_a_deleted_users_saves_can_still_be_copied_from(qtbot, game, box, people):
    make_prefix(game, "gone", "old")
    _tab, page = open_page(qtbot, game, box, people, people[0])
    row = next(r for r in page.found if r.user == "gone")
    assert page.name_of("gone") == "A deleted user" and row.has_saves
    assert {u for u, _n in page._targets(row)} == {"", "u1"}  # (nobody copies to someone deleted)


def test_game_pages_offer_saves(qtbot, game, tmp_path, rom):
    from gamingcrypt.linux.library import LinuxGame
    from gamingcrypt.ui.emulation_pages import RomGamePage
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.saves_page import SavesPage
    from gamingcrypt.ui.wine_pages import LinuxGamePage, WindowsGamePage
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), emulation_root=str(tmp_path / "Emulation"))
    qtbot.addWidget(tab)
    windows = WindowsGamePage(tab, game)
    tab.push(windows)
    windows.saves_button.click()
    assert isinstance(tab.currentWidget(), SavesPage) and isinstance(tab.currentWidget().box, saves.PrefixSaves)
    linux = LinuxGamePage(tab, LinuxGame(game.path, "A Linux game"))
    assert not hasattr(linux, "saves_button")
    page = RomGamePage(tab, rom)
    tab.push(page)
    page.saves_button.click()
    assert isinstance(tab.currentWidget().box, saves.RomSaves)

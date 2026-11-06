"""Moving games onto a USB stick / SD card and back, and formatting one - logic and UI."""

import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

from gamingcrypt import moving
from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation.library import EmulationPaths, scan_all
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.moving import MoveError, Place, Progress
from gamingcrypt.system import removable
from gamingcrypt.system.removable import FormatError, Removable
from gamingcrypt.wine import library as wine


def put(path: Path, data: bytes = b"x" * 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def emu(tmp_path):
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    put(paths.roms_for(BY_ID["snes"]) / "Super Mario World (USA).sfc")
    psx = paths.roms_for(BY_ID["psx"])
    for n in (1, 2):
        put(psx / f"Vagrant Story (Disc {n}).cue", f'FILE "Vagrant Story (Disc {n}).bin" BINARY'.encode())
        put(psx / f"Vagrant Story (Disc {n}).bin", b"b" * 1000)
    return paths


@pytest.fixture
def stick(tmp_path):
    mount = tmp_path / "STICK"
    mount.mkdir()
    return Removable(mount, "usb", "STICK", "/dev/sdb1", "exfat", "/dev/sdb", 32 * 1024 ** 3)


def rom(emu, system, drives=()):
    return scan_all(emu, drives)[system][0]


# --- emulated games ---------------------------------------------------------------------

def test_a_rom_to_the_stick_and_back(emu, stick):
    mario = rom(emu, "snes")
    assert [p.removable for p in moving.places(mario, [stick], emu)] == [stick]
    progress = Progress()
    moving.move(mario, Place(stick), emu, progress)
    assert progress.done == progress.total == 100
    on_stick = stick.mount / "Emulation" / "roms" / "snes" / "Super Mario World (USA).sfc"
    assert on_stick.exists() and not mario.path.exists()
    moved = rom(emu, "snes", [stick])
    assert moved.removable == "usb" and moved.appid == mario.appid  # favorites, play time, saves stay
    assert [p.removable for p in moving.places(moved, [stick], emu)] == [None]  # back onto the drive
    moving.move(moved, Place(None), emu)
    assert mario.path.exists() and not on_stick.exists()
    assert rom(emu, "snes", [stick]).removable == ""


def test_the_short_layout_on_a_stick_is_kept(emu, stick):
    (stick.mount / "roms").mkdir()
    moving.move(rom(emu, "snes"), Place(stick), emu)
    assert (stick.mount / "roms" / "snes" / "Super Mario World (USA).sfc").exists()
    assert not (stick.mount / "Emulation").exists()


def test_a_game_on_several_discs_moves_with_its_tracks_not_its_playlist(emu, stick):
    story = rom(emu, "psx")
    assert len(story.discs) == 2
    moving.move(story, Place(stick), emu)
    folder = stick.mount / "Emulation" / "roms" / "psx"
    assert sorted(p.name for p in folder.iterdir()) == [
        "Vagrant Story (Disc 1).bin", "Vagrant Story (Disc 1).cue",
        "Vagrant Story (Disc 2).bin", "Vagrant Story (Disc 2).cue"]
    assert story.path.exists()  # the playlist is GamingCrypt's, on the drive
    again = rom(emu, "psx", [stick])
    assert again.appid == story.appid and all(folder in d.parents for d in again.discs)
    assert str(folder) in again.path.read_text()  # rewritten: the discs where they are now


def test_one_already_there_isnt_overwritten(emu, stick):
    put(stick.mount / "Emulation" / "roms" / "snes" / "Super Mario World (USA).sfc", b"other")
    with pytest.raises(MoveError, match="already has"):
        moving.move(rom(emu, "snes"), Place(stick), emu)
    assert rom(emu, "snes").path.exists()


def test_not_enough_room(emu, stick, monkeypatch):
    monkeypatch.setattr(moving, "_free", lambda _p: 1000)
    with pytest.raises(MoveError, match="Not enough room on STICK"):
        moving.move(rom(emu, "snes"), Place(stick), emu)


def test_too_big_for_fat32(emu, tmp_path):
    fat = Removable(tmp_path / "FAT", "sd", "", fstype="vfat")
    fat.mount.mkdir()
    game = rom(emu, "snes")
    with open(game.path, "r+b") as f:
        f.truncate(moving.FAT_LIMIT + 1)  # (sparse)
    with pytest.raises(MoveError, match="bigger than 4 GB"):
        moving.check(game, Place(fat), emu, size=10)


def test_cancelled_or_broken_half_way_leaves_nothing_behind(emu, stick, monkeypatch):
    story = rom(emu, "psx")
    progress = Progress()
    progress.cancelled.set()
    with pytest.raises(MoveError, match="Cancelled"):
        moving.move(story, Place(stick), emu, progress)
    real = moving._copy_file
    copied = []

    def pulled_out(source, dest, progress):
        if copied:
            raise OSError(5, "Input/output error")
        copied.append(source)
        real(source, dest, progress)

    monkeypatch.setattr(moving, "_copy_file", pulled_out)
    with pytest.raises(MoveError, match="Input/output error"):
        moving.move(story, Place(stick), emu)
    folder = stick.mount / "Emulation" / "roms" / "psx"
    assert list(folder.iterdir()) == []
    assert all(d.exists() for d in story.discs)  # still all there


def test_a_copy_still_running_isnt_a_game(emu, stick):
    put(stick.mount / "Emulation" / "roms" / "snes" / ".moving-Zelda.sfc")
    assert [g.name for g in scan_all(emu, [stick])["snes"]] == ["Super Mario World"]


# --- Windows and Linux games ------------------------------------------------------------

@pytest.fixture
def windows(tmp_path):
    root = tmp_path / "GamingCrypt" / "Windows Games"
    put(root / "Celeste" / "Celeste.exe")
    put(root / "Celeste" / "Content" / "level.bin", b"l" * 500)
    os.symlink("Celeste.exe", root / "Celeste" / "link.exe")
    (root / ".prefixes" / "Celeste" / "pfx").mkdir(parents=True)
    return root


def test_a_windows_game_keeps_its_saves_on_the_drive(windows, stick):
    celeste = wine.scan(windows)[0]
    moving.move(celeste, Place(stick), None)
    there = stick.mount / "Windows Games" / "Celeste"
    assert (there / "Content" / "level.bin").read_bytes() == b"l" * 500
    assert not (there / "link.exe").is_symlink() and (there / "link.exe").exists()  # exFAT: a copy
    assert not celeste.path.exists()
    moved = wine.scan(windows, drives=[stick])[0]
    assert moved.removable == "usb" and moved.appid == celeste.appid
    assert wine.prefix_dir(moved) == windows / ".prefixes" / "Celeste"  # still there, still its
    moving.move(moved, Place(None), None)
    assert (windows / "Celeste" / "Celeste.exe").exists() and not there.exists()


def test_symlinks_stay_symlinks_on_ext4(windows, tmp_path):
    ext4 = Removable(tmp_path / "EXT", "drive", "", fstype="ext4")
    ext4.mount.mkdir()
    moving.move(wine.scan(windows)[0], Place(ext4), None)
    assert (ext4.mount / "Windows Games" / "Celeste" / "link.exe").is_symlink()


def test_linux_games_need_a_linux_file_system(tmp_path, stick):
    from gamingcrypt.linux import library as linux

    root = tmp_path / "GamingCrypt" / "Linux Games"
    put(root / "Hades" / "start.sh", b"#!/bin/sh\n")
    hades = linux.scan(root)[0]
    with pytest.raises(MoveError, match="format it for Linux|Format it for Linux"):
        moving.move(hades, Place(stick), None)
    ext4 = Removable(tmp_path / "EXT", "drive", "", fstype="ext4")
    ext4.mount.mkdir()
    (root / "Hades" / "start.sh").chmod(0o755)
    moving.move(hades, Place(ext4), None)
    assert os.access(ext4.mount / "Linux Games" / "Hades" / "start.sh", os.X_OK)  # still startable


def test_a_folder_already_there(windows, stick):
    (stick.mount / "Windows Games" / "Celeste").mkdir(parents=True)
    with pytest.raises(MoveError, match="already has a folder"):
        moving.move(wine.scan(windows)[0], Place(stick), None)


# --- formatting -------------------------------------------------------------------------

class Udisks:
    """lsblk, udisksctl and gdbus as they answer for a mounted stick."""

    def __init__(self, mount: Path, fail: str = ""):
        self.mount, self.fail = mount, fail
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(args)
        ok = subprocess.CompletedProcess
        if args[0] == "lsblk":
            listing = {"blockdevices": [{"name": "sdb", "path": "/dev/sdb", "type": "disk", "tran": "usb",
                                         "size": 32 * 1024 ** 3, "mountpoints": [None], "children": [
                                             {"name": "sdb1", "path": "/dev/sdb1", "type": "part",
                                              "fstype": "vfat", "mountpoints": ["/run/media/me/OLD"]}]}]}
            return ok(args, 0, json.dumps(listing), "")
        if args[:2] == ["udisksctl", "unmount"]:
            return ok(args, 1 if self.fail == "busy" else 0, "", "target is busy")
        if args[0] == "gdbus":
            if self.fail == "gdbus":
                return ok(args, 1, "", "Error: GDBus.Error:org.freedesktop.UDisks2.Error.Failed: "
                                       "Error creating file system: mkfs failed")
            return ok(args, 0, "(objectpath '/org/freedesktop/UDisks2/block_devices/sdb1',)\n", "")
        if args[:2] == ["udisksctl", "mount"]:
            return ok(args, 0, f"Mounted /dev/sdb1 at {self.mount}\n", "")
        raise AssertionError(args)


def test_format_a_stick(tmp_path, stick):
    system = Udisks(tmp_path / "NEW")
    now = removable.format_drive(stick, "exfat", "My Games!", run=system)
    assert now.mount == tmp_path / "NEW" and now.label == "My_Games" and now.fstype == "exfat"
    steps = [" ".join(c[:2]) if c[0] != "gdbus" else c[c.index("--method") + 1] for c in system.calls]
    assert steps == ["lsblk -J", "udisksctl unmount", "org.freedesktop.UDisks2.Block.Format",
                     "org.freedesktop.UDisks2.PartitionTable.CreatePartitionAndFormat", "udisksctl mount"]
    create = system.calls[3]
    assert "0x07" in create and "exfat" in create and "{'label': <'My_Games'>, 'take-ownership': <true>}" in create
    assert system.calls[2][-2:] == ["dos", "{}"]
    assert (now.mount / "Emulation" / "roms" / "snes").is_dir() and (now.mount / "Windows Games").is_dir()


def test_format_a_big_drive_as_ext4_uses_gpt(tmp_path):
    big = Removable(tmp_path / "X", "drive", "", disk="/dev/sdb", size=4 * 1024 ** 4)
    system = Udisks(tmp_path / "NEW")
    real = system.__call__

    def bigger(args, **kw):
        out = real(args, **kw)
        if args[0] == "lsblk":
            listing = json.loads(out.stdout)
            listing["blockdevices"][0]["size"] = 4 * 1024 ** 4
            out = subprocess.CompletedProcess(args, 0, json.dumps(listing), "")
        return out

    removable.format_drive(big, "ext4", "", run=bigger, layout=False)
    assert system.calls[2][-2:] == ["gpt", "{}"]
    assert "0fc63daf-8483-4772-8e79-3d69d8477de4" in system.calls[3]
    assert "{'label': <'GAMES'>, 'take-ownership': <true>}" in system.calls[3]


def test_format_errors(tmp_path, stick):
    with pytest.raises(FormatError, match="in use"):
        removable.format_drive(stick, "exfat", "G", run=Udisks(tmp_path, fail="busy"))
    with pytest.raises(FormatError, match="^Error creating file system: mkfs failed$"):
        removable.format_drive(stick, "exfat", "G", run=Udisks(tmp_path, fail="gdbus"))
    with pytest.raises(FormatError, match="isn't there"):
        removable.format_drive(Removable(tmp_path, "usb", disk="/dev/sdz"), "exfat", "G", run=Udisks(tmp_path))
    with pytest.raises(FormatError):
        removable.format_drive(stick, "ntfs", "G", run=Udisks(tmp_path))


def test_formats_this_device_can_make():
    assert removable.formats(lambda name: name == "mkfs.ext4") == ["ext4"]
    assert removable.formats(lambda name: "/usr/sbin/" + name) == ["exfat", "ext4"]
    assert removable.clean_label("") == "GAMES" and removable.clean_label("a very long name") == "a_very_long"


# --- UI ---------------------------------------------------------------------------------

@pytest.fixture
def tab(qtbot, emu, windows):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    t = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"],
                 emulation_root=str(emu.root), windows_root=str(windows))
    qtbot.addWidget(t)
    t.show()
    qtbot.waitUntil(lambda: set(t.home.system_cards) == {"snes", "psx"} and len(t.windows_games) == 1)
    return t


def test_move_from_the_game_page(qtbot, tab, emu, stick):
    mario = tab.roms["snes"][0]
    tab.open_rom(mario)
    page = tab.currentWidget()
    assert page.move_button.isHidden()  # no stick in
    tab.set_drives([stick])
    assert not page.move_button.isHidden()
    page.move_button.click()
    box = page.move_box
    assert [b.text().split(" · ")[0] for b in box.buttons] == ["🔌 To STICK"]
    assert box.window() is not None and page.move_modal.parent() is page.window()  # over everything
    box.buttons[0].click()
    assert box.steps.isVisible() and box.bar.isVisible() and box.cancel_button.text() == "Stop"
    qtbot.waitUntil(lambda: box.over)
    # it stays: where it is now, every step done
    assert box.title.text() == "✓ Super Mario World is on STICK now" and box.ok_button.isVisible()
    assert all(label.property("state") == "done" for label in box.step_labels.values())
    assert box.bar.value() == 1000 and box.numbers.text().startswith("Took ")
    assert "Super Mario World moved to STICK" in tab.home.notice.text()
    assert tab.currentWidget() is page
    box.ok_button.click()
    assert page.move_box is None and tab.currentWidget() is tab.home
    assert (stick.mount / "Emulation" / "roms" / "snes" / "Super Mario World (USA).sfc").exists()
    qtbot.waitUntil(lambda: tab.roms["snes"][0].removable == "usb")


def test_a_failed_move_says_why_on_the_page(qtbot, tab, emu, stick):
    put(stick.mount / "Windows Games" / "Celeste" / "x")
    tab.set_drives([stick])
    tab.open_windows_game(tab.windows_games[0])
    page = tab.currentWidget()
    page.move_button.click()
    box = page.move_box
    box.buttons[0].click()
    qtbot.waitUntil(lambda: box.over)
    assert box.title.text() == "✗ Celeste wasn't moved" and "already has a folder" in box.state.text()
    assert box.question.text() == "It went wrong while checking the room on STICK."
    assert box.step_labels["check"].property("state") == "failed"
    assert box.ok_button.text() == "Close"
    box.ok_button.click()
    assert page.move_box is None
    assert "already has a folder" in page.status.text() and page.status.isVisible()
    assert tab.currentWidget() is page


def test_only_the_admin_moves(qtbot, tab, stick):
    tab.set_drives([stick])
    tab.open_rom(tab.roms["snes"][0])
    page = tab.currentWidget()
    from types import SimpleNamespace

    tab.user = SimpleNamespace(can_delete_games=False)
    page.drives_changed()
    assert page.move_button.isHidden()


@pytest.fixture
def storage(qtbot, tab, emu, stick):
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, games_running=lambda: set(), emulation_fn=lambda: emu)
    page.library_fn = lambda: tab
    qtbot.addWidget(page)
    page.show()
    page.set_drives([stick])
    page.refresh()
    qtbot.waitUntil(lambda: len(page.rom_rows) == 2 and len(page.pc_rows) == 1)
    return page


def test_storage_shows_the_sticks_and_moves_games(qtbot, storage, stick):
    assert storage.drives_heading.isVisible()
    text, _bar, format_button = storage.drive_rows[stick]
    assert "STICK" in text.text() and "USB stick" in text.text() and "exfat" in text.text()
    assert format_button.isVisible()
    changed = []
    storage.roms_changed.connect(lambda: changed.append(1))
    celeste_row = next(iter(storage.pc_rows.values()))
    assert "Celeste\nWindows" in celeste_row[0].text()
    celeste_row[1].click()
    box = storage.mover
    box.buttons[0].click()
    qtbot.waitUntil(lambda: box.over and bool(changed))
    storage.mover_modal.dismissed.emit()  # a tap beside it: closes it now it's over
    assert storage.mover is None
    assert "Celeste moved to STICK" in storage.status.text()
    assert (stick.mount / "Windows Games" / "Celeste" / "Celeste.exe").exists()
    qtbot.waitUntil(lambda: "on STICK" in next(iter(storage.pc_rows.values()))[0].text())


def test_storage_formats_a_stick(qtbot, storage, stick, monkeypatch):
    done = []
    monkeypatch.setattr(removable, "formats", lambda: ["exfat", "ext4"])
    monkeypatch.setattr(removable, "format_drive",
                        lambda drive, fstype, label, run=None, step=None, encrypt=None:
                        done.append((fstype, label, encrypt)) or drive)
    looked = []
    storage.drives_changed.connect(lambda: looked.append(1))
    storage.drive_rows[stick][2].click()
    box = storage.formatter
    assert set(box.choices) == {"exfat", "ext4"} and box.format_button.isHidden()
    box.choices["exfat"].click()
    assert "Really delete everything on STICK" in box.question.text() and done == []
    box.format_button.click()
    qtbot.waitUntil(lambda: box.over)
    assert done == [("exfat", "STICK", None)] and looked == [1]  # (locked since a restart: not encrypted)
    assert "STICK is formatted (exFAT)" in storage.status.text()
    assert box.title.text() == "✓ STICK is ready for games" and box.ok_button.isVisible()
    box.ok_button.click()
    assert storage.formatter is None


def test_format_can_be_cancelled_and_isnt_for_users(qtbot, storage, stick, monkeypatch):
    monkeypatch.setattr(removable, "formats", lambda: ["ext4"])
    storage.drive_rows[stick][2].click()
    storage.formatter.cancel_button.click()
    assert storage.formatter is None
    storage.can_delete = lambda: False
    storage.show_drives()
    assert storage.drive_rows[stick][2].isHidden()
    storage.ask_format(stick)
    assert storage.formatter is None


def test_no_formatting_tools(qtbot):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(Removable(Path("/x"), "sd"), formats=[])
    qtbot.addWidget(box)
    assert "install exfatprogs" in box.question.text() and not box.choices


# --- what's shown while it runs -----------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_format_shows_each_step_and_the_time(qtbot, tmp_path, stick):
    from gamingcrypt.ui.format_drive import FormatConfirm

    clock = Clock()
    box = FormatConfirm(stick, formats=["ext4"], run=Udisks(tmp_path / "NEW"), clock=clock)
    qtbot.addWidget(box)
    box.show()
    box.choices["ext4"].click()
    box.reached[:] = []
    box.started_at = clock.now
    box.working = True
    box.chosen = "ext4"
    box.reached += ["check", "unmount", "table", "filesystem"]
    clock.now += 75
    box.show_steps()
    states = {k: label.property("state") for k, label in box.step_labels.items()}
    assert states == {"check": "done", "unmount": "done", "table": "done", "filesystem": "now",
                      "mount": "waiting", "encrypt": "waiting", "folders": "waiting"}
    assert box.step_labels["filesystem"].text() == "◐  Creating the ext4 file system…"
    assert box.state.text() == "Creating the ext4 file system…  ·  1:15" and box.bar.value() == 300
    box.working = False
    box._failed(FormatError("mkfs failed"))
    assert box.step_labels["filesystem"].property("state") == "failed"
    assert box.question.text() == "It went wrong while creating the ext4 file system."
    assert box.state.text() == "mkfs failed" and box.ok_button.text() == "Close"
    finished = []
    box.finished.connect(lambda: finished.append(1))
    box.gamepad_back()  # B closes it now
    assert finished == [1]


def test_format_runs_its_steps_for_real(qtbot, tmp_path, stick):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(stick, formats=["exfat"], run=Udisks(tmp_path / "NEW"))
    qtbot.addWidget(box)
    box.choices["exfat"].click()
    box.format_button.click()
    assert box.working and box.cancel_button.isHidden()  # can't be stopped half way
    box.gamepad_back()
    assert box.working
    qtbot.waitUntil(lambda: box.over)
    assert box.reached == [key for key, _t in removable.steps(False)]
    assert box.step_labels["encrypt"].isHidden()  # not encrypted: not a step
    assert all(label.property("state") == "done" for key, label in box.step_labels.items() if key != "encrypt")
    assert box.bar.value() == box.bar.maximum() and "Took 0:0" in box.question.text()


def test_move_shows_how_far_how_fast_and_how_long(qtbot, emu, stick):
    from gamingcrypt.ui.move_game import MoveGame

    clock = Clock()
    box = MoveGame(rom(emu, "psx"), [Place(stick)], emu, clock=clock)
    qtbot.addWidget(box)
    box.show()
    box.place, box.moving, box.started_at = Place(stick), True, clock.now
    box.speed_from = (clock.now, 0)
    p = box.progress
    p.stage, p.total, p.done, p.files, p.copied, p.current = "copy", 400 * 1024 ** 2, 100 * 1024 ** 2, 4, 1, "Disc 2.bin"
    clock.now += 2  # 100 MB in 2 s: 50 MB/s, 300 MB to go: 6 s
    box.show_progress()
    assert box.numbers.text() == "100.0 MB of 400.0 MB  ·  25%  ·  50.0 MB/s  ·  about 0:06 left  ·  0:02 so far"
    assert box.step_labels["check"].property("state") == "done"
    assert box.step_labels["copy"].text() == "◐  Copying the game - file 2 of 4…"
    assert box.step_labels["delete"].text() == "○  Deleting it from the encrypted drive"
    assert box.state.text() == "Copying Disc 2.bin" and box.bar.value() == 250


def test_stopping_a_move_says_its_where_it_was(qtbot, emu, stick, monkeypatch):
    from gamingcrypt.ui.move_game import MoveGame

    real = moving._copy_file

    def slow(source, dest, progress):
        progress.cancelled.wait(5)
        real(source, dest, progress)

    monkeypatch.setattr(moving, "_copy_file", slow)
    game = rom(emu, "psx")
    box = MoveGame(game, [Place(stick)], emu)
    qtbot.addWidget(box)
    box.buttons[0].click()
    box.cancel_button.click()
    assert box.cancel_button.text() == "Stopping…"
    qtbot.waitUntil(lambda: box.over)
    assert box.title.text() == "Vagrant Story wasn't moved" and "it's on the encrypted drive as before" in \
        box.question.text()
    assert all(d.exists() for d in game.discs) and not list((stick.mount / "Emulation" / "roms" / "psx").iterdir())


# --- permissions ----------------------------------------------------------------------------

@pytest.mark.skipif(os.geteuid() == 0, reason="root may write anywhere")
def test_a_stick_that_isnt_ours_is_said_before_copying(emu, stick):
    roms = stick.mount / "Emulation"
    roms.mkdir()
    roms.chmod(0o555)  # (as a stick formatted elsewhere: its folders root's)
    try:
        with pytest.raises(MoveError, match=r"Can't write to STICK: .*Emulation is read-only or belongs to another"):
            moving.move(rom(emu, "snes"), Place(stick), emu)
    finally:
        roms.chmod(0o755)
    assert rom(emu, "snes").path.exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root may delete anywhere")
def test_an_original_that_couldnt_be_deleted_isnt_copied(emu, stick):
    folder = emu.roms_for(BY_ID["snes"])
    folder.chmod(0o555)  # (e.g. made by the network share as another user)
    try:
        with pytest.raises(MoveError, match="couldn't be deleted from the encrypted drive afterwards.*Nothing"):
            moving.move(rom(emu, "snes"), Place(stick), emu)
    finally:
        folder.chmod(0o755)
    assert not (stick.mount / "Emulation" / "roms" / "snes").exists()


def test_read_only_folders_in_a_game_are_moved_and_deleted(windows, stick):
    data = windows / "Celeste" / "Content"
    data.chmod(0o555)  # (copied off a disc)
    celeste = wine.scan(windows)[0]
    moving.move(celeste, Place(stick), None)
    assert not celeste.path.exists()
    assert (stick.mount / "Windows Games" / "Celeste" / "Content" / "level.bin").exists()
    moved = wine.scan(windows, drives=[stick])[0]
    moving.move(moved, Place(None), None)  # and back: its read-only folder on the stick too
    assert (windows / "Celeste" / "Content" / "level.bin").exists() and not moved.path.exists()


def test_a_shortcut_the_stick_cant_have_is_copied(windows, tmp_path, monkeypatch):
    unknown = Removable(tmp_path / "ODD", "usb", "", fstype="")  # (lsblk didn't say)
    unknown.mount.mkdir()

    def refuse(*_a):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(moving.os, "symlink", refuse)
    moving.move(wine.scan(windows)[0], Place(unknown), None)
    link = unknown.mount / "Windows Games" / "Celeste" / "link.exe"
    assert link.exists() and not link.is_symlink()


def test_errors_say_where(emu, stick, monkeypatch):
    def denied(source, dest, progress):
        raise PermissionError(13, "Permission denied", str(dest))

    monkeypatch.setattr(moving, "_copy_file", denied)
    with pytest.raises(MoveError, match=r"Permission denied: .*STICK/Emulation/roms/snes/\.moving-Super"):
        moving.move(rom(emu, "snes"), Place(stick), emu)

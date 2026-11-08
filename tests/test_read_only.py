"""Sticks that can only be read: write-protected (an SD card's switch) or damaged (taken out without
ejecting: mounted read-only) - shown so, nothing moved onto them, and a damaged one repaired."""

import json
import subprocess
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint

from gamingcrypt import moving
from gamingcrypt.system import removable
from gamingcrypt.system.removable import Drives, Removable
from tests.test_code_dialogs import rect_in, screen, shown_parts

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def listing(ro_disk=False, ro_part=False, mount="/run/media/me/GAMES"):
    return {"blockdevices": [{"name": "mmcblk1", "path": "/dev/mmcblk1", "type": "disk", "tran": None, "rm": True,
                              "ro": ro_disk, "size": 64 * 1024 ** 3, "children": [
                                  {"name": "mmcblk1p1", "path": "/dev/mmcblk1p1", "type": "part", "fstype": "exfat",
                                   "label": "GAMES", "uuid": "AB-CD", "ro": ro_part, "mountpoints": [mount]}]}]}


@pytest.fixture(autouse=True)
def an_sd_slot(monkeypatch):
    monkeypatch.setattr(removable, "_is_sd_slot", lambda _name: True)


def test_write_protected_and_damaged(tmp_path):
    assert removable.parse(listing())[0][0].read_only == ""
    assert removable.parse(listing(ro_disk=True))[0][0].read_only == "locked"  # the switch
    assert removable.parse(listing(ro_part="1"))[0][0].read_only == "locked"
    damaged = removable.parse(listing(), ro_mounts={"/run/media/me/GAMES"})[0][0]
    assert damaged.read_only == "damaged"  # mounted read-only, though it could be written


def test_read_only_mounts(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/sda2 / ext4 rw,relatime 0 0\n"
                      "/dev/sdb1 /run/media/me/MY\\040GAMES exfat ro,nosuid,nodev,relatime 0 0\n"
                      "/dev/sdc1 /run/media/me/OTHER vfat rw,nosuid 0 0\n"
                      "proc /proc proc rw,nosuid,nodev,noexec 0 0\n")
    assert removable.read_only_mounts(mounts) == {"/run/media/me/MY GAMES"}
    assert removable.read_only_mounts(tmp_path / "missing") == set()


def test_looked_at_with_the_mounts(tmp_path, monkeypatch):
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/mmcblk1p1 /run/media/me/GAMES exfat ro,relatime 0 0\n")
    monkeypatch.setattr(removable, "MOUNTS", mounts)
    run = lambda args, **_k: subprocess.CompletedProcess(args, 0, json.dumps(listing()), "")  # noqa: E731
    assert Drives(run=run).look()[0].read_only == "damaged"


def test_nothing_is_moved_onto_one(tmp_path):
    from gamingcrypt.emulation.library import EmulationPaths, scan
    from gamingcrypt.emulation.systems import BY_ID

    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms_for(BY_ID["snes"]) / "Mario.sfc").write_bytes(b"x")
    game = scan(paths, BY_ID["snes"])[0]
    good = Removable(tmp_path / "A", "usb", "A")
    locked = Removable(tmp_path / "B", "sd", "B", read_only="locked")
    damaged = Removable(tmp_path / "C", "usb", "C", read_only="damaged")
    assert [p.removable for p in moving.places(game, [good, locked, damaged], paths)] == [good]


def test_an_encrypted_one_isnt_opened_read_only(tmp_path, monkeypatch):
    from gamingcrypt.system import stick_crypt

    mount = tmp_path / "GAMES"
    mount.mkdir()
    (mount / stick_crypt.CONTAINER).write_bytes(bytes(70))
    stick_crypt.keys.set("pw")
    tried = []
    monkeypatch.setattr(stick_crypt, "open_stick", lambda *a, **k: tried.append(a))
    drives = Drives(run=lambda args, **_k: subprocess.CompletedProcess(args, 0, json.dumps(listing(
        ro_disk=True, mount=str(mount))), ""))
    assert drives.look() == [] and tried == []
    assert drives.unusable[0].problem.startswith("Write-protected")


class Udisks:
    def __init__(self, mount, repair_ok=True):
        self.mount, self.repair_ok, self.calls = mount, repair_ok, []

    def __call__(self, args, **_kw):
        self.calls.append(args)
        if args[0] == "gdbus":
            assert removable.BUSY == {"/dev/mmcblk1"}  # (not mounted again by the app meanwhile)
            return subprocess.CompletedProcess(args, 0, "(true,)" if self.repair_ok else "(false,)", "")
        if args[:2] == ["udisksctl", "mount"]:
            return subprocess.CompletedProcess(args, 0, f"Mounted /dev/mmcblk1p1 at {self.mount}", "")
        return subprocess.CompletedProcess(args, 0, "", "")


def test_repair(tmp_path):
    damaged = Removable(Path("/run/media/me/GAMES"), "sd", "GAMES", "/dev/mmcblk1p1", "exfat", "/dev/mmcblk1",
                        read_only="damaged")
    system = Udisks(tmp_path / "GAMES")
    steps = []
    now = removable.repair(damaged, run=system, step=steps.append)
    assert steps == ["unmount", "repair", "mount"]
    assert now.read_only == "" and now.mount == tmp_path / "GAMES"
    method = next(c for c in system.calls if c[0] == "gdbus")
    assert method[method.index("--object-path") + 1].endswith("/block_devices/mmcblk1p1")
    assert method[method.index("--method") + 1] == "org.freedesktop.UDisks2.Filesystem.Repair"
    assert removable.BUSY == set()


def test_repair_that_fails_or_cant_be(tmp_path):
    damaged = Removable(Path("/x"), "sd", "GAMES", "/dev/mmcblk1p1", disk="/dev/mmcblk1", read_only="damaged")
    with pytest.raises(removable.FormatError, match="couldn't be repaired"):
        removable.repair(damaged, run=Udisks(tmp_path, repair_ok=False))
    with pytest.raises(removable.FormatError, match="write-protected"):
        removable.repair(Removable(Path("/x"), "sd", "G", "/dev/x1", read_only="locked"), run=Udisks(tmp_path))
    assert removable.BUSY == set()


# --- on screen ----------------------------------------------------------------------------------

def storage_with(qtbot, host, drives, unusable=()):
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.setParent(host)
    page.resize(host.size())
    page.show()
    page.set_drives(drives, list(unusable))
    qtbot.wait(20)
    return page


@pytest.mark.parametrize("w,h", SCREENS)
def test_storage_shows_them_with_repair(qtbot, tmp_path, w, h):
    host = screen(qtbot, w, h)
    locked = Removable(tmp_path, "sd", "CARD", "/dev/a1", "exfat", "/dev/a", read_only="locked")
    damaged = Removable(tmp_path, "usb", "STICK", "/dev/b1", "exfat", "/dev/b", read_only="damaged")
    page = storage_with(qtbot, host, [locked, damaged])
    card, stick = page.drive_rows[locked], page.drive_rows[damaged]
    assert "Write-protected" in card[0].text() and card[2].isHidden() and len(card) == 3  # no format, no repair
    assert "Read-only" in stick[0].text() and stick[3].text() == "🛠 Repair…"
    for widget in [*card, *stick]:
        if widget.isVisible():
            where = rect_in(widget, host)
            assert host.rect().contains(where), f"{widget} off the {w}x{h} screen"


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_repair_box_fits_and_shows_its_steps(qtbot, tmp_path, w, h):
    host = screen(qtbot, w, h)
    damaged = Removable(tmp_path, "usb", "STICK", "/dev/mmcblk1p1", "exfat", "/dev/mmcblk1", read_only="damaged")
    page = storage_with(qtbot, host, [damaged])
    page.ask_repair(damaged)
    box = page.repairer
    window_box = rect_in(box, box.window())
    assert box.window().rect().contains(window_box)
    assert abs(window_box.center().x() - box.window().width() / 2) <= 2
    box.run = Udisks(tmp_path / "STICK")
    looked = []
    page.drives_changed.connect(lambda: looked.append(1))
    box.repair_button.click()
    assert box.working and box.cancel_button.isHidden()
    page.close_repair()  # (a tap beside it: not while it repairs)
    assert page.repairer is box
    qtbot.waitUntil(lambda: box.over)
    assert box.title.text() == "✓ STICK is repaired" and looked == [1]
    assert all(label.property("state") == "done" for label in box.step_labels.values())
    for part in shown_parts(box):
        assert box.rect().contains(rect_in(part, box)), f"{part} cut off at {w}x{h}"
    box.ok_button.click()
    assert page.repairer is None


def test_a_failed_repair_says_where(qtbot, tmp_path):
    host = screen(qtbot, 1280, 800)
    damaged = Removable(tmp_path, "usb", "STICK", "/dev/mmcblk1p1", "exfat", "/dev/mmcblk1", read_only="damaged")
    page = storage_with(qtbot, host, [damaged])
    page.ask_repair(damaged)
    box = page.repairer
    box.run = Udisks(tmp_path, repair_ok=False)
    box.repair_button.click()
    qtbot.waitUntil(lambda: box.over)
    assert box.step_labels["repair"].property("state") == "failed"
    assert "couldn't be repaired" in box.state.text() and box.ok_button.text() == "Close"
    assert "Could not repair STICK" in page.status.text()


def test_a_damaged_stick_is_announced(tmp_path):
    from types import SimpleNamespace

    from gamingcrypt.app import MainWindow

    said = []
    app = SimpleNamespace(notify=lambda text, icon: said.append((icon, text)))
    MainWindow.drives_arrived(app, [], [])
    MainWindow.drives_arrived(app, [Removable(tmp_path, "usb", "STICK", "/dev/b1", disk="/dev/b", read_only="damaged"),
                                    Removable(tmp_path, "sd", "CARD", "/dev/c1", disk="/dev/c", read_only="locked")], [])
    assert said[0][0] == "⚠" and "Settings → Storage repairs it" in said[0][1]
    assert said[1] == ("🔒", "CARD is write-protected - its games play, nothing can be moved onto it")

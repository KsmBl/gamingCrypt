"""USB sticks, USB drives and SD cards: found, mounted, their games in the Games tab with a badge."""

import copy
import json
import subprocess
from pathlib import Path

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation.library import EmulationPaths, scan_all
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.system import removable
from gamingcrypt.system.removable import Drives, Removable, kind_of, parse
from gamingcrypt.wine import library as wine


def put(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def disk(name, tran="usb", size=32 * 1024 ** 3, rota=False, model="Cruzer Blade", children=(), rm=True, **extra):
    return {"name": name, "path": f"/dev/{name}", "type": "disk", "tran": tran, "rm": rm, "hotplug": True,
            "rota": rota, "size": size, "fstype": None, "mountpoints": [None], "label": None, "model": model,
            "children": list(children), **extra}


def part(name, mount=None, fstype="exfat", label=None):
    return {"name": name, "path": f"/dev/{name}", "type": "part", "fstype": fstype, "label": label,
            "mountpoints": [mount] if mount else [None]}


# --- which drives -----------------------------------------------------------------------

def test_kinds():
    assert kind_of(disk("sdb")) == "usb"
    assert kind_of(disk("sdb", rota=True)) == "drive"  # a hard disk in a USB case
    assert kind_of(disk("sdb", size=1000 * 1024 ** 3, model="Portable SSD T7")) == "drive"
    assert kind_of(disk("sdb", model="SD/MMC Card Reader")) == "sd"
    assert kind_of(disk("nvme0n1", tran="nvme", rm=False)) is None  # the device's own
    assert kind_of(disk("sda", tran="sata", rm=False)) is None


def test_sd_slot_or_own_emmc(monkeypatch):
    monkeypatch.setattr(removable, "_is_sd_slot", lambda name: name == "mmcblk1")
    assert kind_of(disk("mmcblk1", tran=None)) == "sd"
    assert kind_of(disk("mmcblk0", tran=None)) is None  # the eMMC the system is on


def test_parse_mounted_unmounted_and_left_out():
    listing = {"blockdevices": [
        disk("sda", tran="sata", rm=False, children=[part("sda1", "/")]),
        disk("sdb", children=[part("sdb1", "/run/media/me/GAMES", label="GAMES ")]),
        disk("sdc", rota=True, children=[part("sdc1"), part("sdc2", fstype="swap")]),
        disk("sdd", children=[part("sdd1", "/home/me/GamingCrypt")]),  # the encrypted drive itself
        disk("sde", children=[part("sde1", "/")]),  # booted from a stick: the system's
        {"name": "loop0", "type": "loop", "children": [{"name": "veracrypt1", "type": "dm",
                                                       "mountpoints": ["/home/me/GamingCrypt"]}]},
        {**disk("sdf"), "fstype": "vfat", "mountpoints": ["/run/media/me/STICK"]},  # no partition table
    ]}
    found, unmounted, blank = parse(listing, exclude=("/home/me/GamingCrypt",))
    assert found == [Removable(Path("/run/media/me/GAMES"), "usb", "GAMES"),
                     Removable(Path("/run/media/me/STICK"), "usb", "")]
    assert found[0].name == "GAMES" and found[1].name == "USB stick"
    assert [p["path"] for p in unmounted] == ["/dev/sdc1"]  # not the swap


def test_old_lsblk_has_one_mountpoint():
    listing = {"blockdevices": [disk("sdb", children=[{**part("sdb1"), "mountpoints": None,
                                                       "mountpoint": "/media/STICK"}])]}
    assert parse(listing)[0] == [Removable(Path("/media/STICK"), "usb", "")]


class FakeSystem:
    """lsblk and udisksctl: a stick that's mounted when udisks is asked to."""

    def __init__(self, mounts: bool = True):
        self.mounted = False
        self.mounts = mounts
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(args[0])
        if args[0] == "udisksctl":
            self.mounted = self.mounts
            return subprocess.CompletedProcess(args, 0 if self.mounts else 1, "Mounted", "not authorized")
        point = "/run/media/me/STICK" if self.mounted else None
        listing = {"blockdevices": [disk("sdb", children=[part("sdb1", point, label="STICK")])]}
        return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")


def test_an_unmounted_stick_is_mounted():
    system = FakeSystem()
    assert Drives(run=system).look() == [Removable(Path("/run/media/me/STICK"), "usb", "STICK")]
    assert system.calls == ["lsblk", "udisksctl", "lsblk"]


def test_one_that_wont_mount_isnt_tried_again_until_its_back():
    system = FakeSystem(mounts=False)
    drives = Drives(run=system)
    assert drives.look() == [] and drives.look() == []
    assert system.calls.count("udisksctl") == 1
    drives.run = lambda args, **_k: subprocess.CompletedProcess(args, 0, '{"blockdevices": []}', "")
    drives.look()  # taken out
    drives.run = system
    drives.look()
    assert system.calls.count("udisksctl") == 2


def test_nothing_mounted_when_asked_not_to():
    system = FakeSystem()
    assert Drives(run=system, mount=False).look() == []
    assert "udisksctl" not in system.calls


def test_no_lsblk():
    def missing(*_a, **_k):
        raise FileNotFoundError("lsblk")

    assert Drives(run=missing).look() == []


def test_tests_never_see_the_real_drives():
    assert Drives().look() == []  # (conftest)


# --- the games on them ------------------------------------------------------------------

@pytest.fixture
def drive(tmp_path):
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    put(paths.roms_for(BY_ID["snes"]) / "Super Mario World (USA).sfc")
    return paths


@pytest.fixture
def stick(tmp_path):
    mount = tmp_path / "STICK"
    put(mount / "Emulation" / "roms" / "snes" / "Chrono Trigger (USA).sfc")
    put(mount / "Emulation" / "roms" / "snes" / "Super Mario World (USA).sfc")  # on the drive too
    put(mount / "roms" / "gba" / "Metroid Fusion (USA).gba")  # the short layout
    put(mount / "Windows Games" / "Celeste" / "Celeste.exe")
    put(mount / "Linux Games" / "Hades" / "start.sh", b"#!/bin/sh\n")
    return Removable(mount, "usb", "STICK")


def test_roms_on_a_stick(drive, stick):
    found = scan_all(drive, [stick])
    snes = found["snes"]
    assert [(g.name, g.removable) for g in snes] == [("Chrono Trigger", "usb"), ("Super Mario World", "")]
    assert [(g.name, g.removable) for g in found["gba"]] == [("Metroid Fusion", "usb")]
    assert scan_all(drive) == {"snes": [snes[1]]}  # taken out: gone again


def test_a_game_on_several_discs_on_a_stick_has_its_playlist_on_the_drive(drive, stick):
    folder = stick.mount / "roms" / "psx"
    for n in (1, 2):
        put(folder / f"Vagrant Story (Disc {n}).cue", f'FILE "Vagrant Story (Disc {n}).bin" BINARY'.encode())
    game = scan_all(drive, [stick])["psx"][0]
    assert game.removable == "usb" and len(game.discs) == 2
    assert game.path.is_relative_to(drive.config)  # nothing written onto the stick
    assert not list(stick.mount.rglob("*.m3u"))


def test_windows_and_linux_games_on_a_stick_keep_their_saves_on_the_drive(tmp_path, stick):
    from gamingcrypt.linux import library as linux

    root = tmp_path / "GamingCrypt" / "Windows Games"
    put(root / "Celeste" / "Celeste.exe")  # on the drive too: that one
    put(root / "Hollow Knight" / "hk.exe")
    games = wine.scan(root, sizes=False, drives=[stick])
    assert [(g.name, g.removable) for g in games] == [("Celeste", ""), ("Hollow Knight", "")]
    (root / "Celeste").rename(root / "Celeste moved")
    games = wine.scan(root, sizes=False, drives=[stick])
    celeste = next(g for g in games if g.name == "Celeste")
    assert celeste.removable == "usb" and celeste.path == stick.windows / "Celeste"
    assert wine.prefix_dir(celeste) == root / ".prefixes" / "Celeste"
    assert wine.prefix_dir(celeste, "u1") == root / ".users" / "u1" / ".prefixes" / "Celeste"
    hades = linux.scan(tmp_path / "GamingCrypt" / "Linux Games", sizes=False, drives=[stick])
    assert [(g.name, g.removable, g.KIND) for g in hades] == [("Hades", "usb", "linux")]


def test_saves_page_of_a_game_on_a_stick(tmp_path, stick):
    from gamingcrypt.saves import PrefixSaves

    root = tmp_path / "GamingCrypt" / "Windows Games"
    (root / ".prefixes" / "Celeste" / "pfx").mkdir(parents=True)
    celeste = wine.scan(root, sizes=False, drives=[stick])[0]
    assert PrefixSaves(celeste).owners() == [""]


# --- the Games tab ----------------------------------------------------------------------

@pytest.fixture
def tab(qtbot, drive, tmp_path):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    t = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"],
                 emulation_root=str(drive.root), windows_root=str(tmp_path / "GamingCrypt" / "Windows Games"))
    qtbot.addWidget(t)
    t.show()
    qtbot.waitUntil(lambda: set(t.home.system_cards) == {"snes"})
    return t


def shown(tab) -> dict:
    """The emulated, Windows and Linux games in "Installed games" (not the fake Steam library's)."""
    return {card.game.name: card.game.removable for card in tab.home.grid.widgets()
            if hasattr(card.game, "removable") and card.isVisibleTo(tab.home.grid_widget)}


def test_put_in_and_taken_out(qtbot, tab, stick):
    assert shown(tab) == {"Super Mario World": ""}
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: len(shown(tab)) == 4)
    assert shown(tab) == {"Super Mario World": "", "Chrono Trigger": "usb", "Metroid Fusion": "usb",
                          "Celeste": "usb"}
    assert set(tab.home.system_cards) == {"snes", "gba"}
    cards = {card.game.name: card for card in tab.home.grid.widgets()}
    assert cards["Chrono Trigger"].cover.badge == "usb" and cards["Celeste"].cover.badge == "usb"
    assert cards["Super Mario World"].cover.badge == ""
    tab.set_drives([])
    qtbot.waitUntil(lambda: len(shown(tab)) == 1)
    assert set(tab.home.system_cards) == {"snes"}


def test_the_same_drives_dont_look_again(qtbot, tab, stick, monkeypatch):
    tab.set_drives([stick])
    looked = []
    monkeypatch.setattr(tab, "reload_roms", lambda: looked.append(1))
    tab.set_drives([Removable(stick.mount, "usb", "STICK")])
    assert looked == []


def test_game_pages_show_the_badge(qtbot, tab, tmp_path):
    sd = Removable(tmp_path / "SD", "sd")
    put(sd.mount / "roms" / "snes" / "Earthbound (USA).sfc")
    put(sd.windows / "Celeste" / "Celeste.exe")
    tab.set_drives([sd])
    qtbot.waitUntil(lambda: "Earthbound" in shown(tab) and "Celeste" in shown(tab))
    cards = {card.game.name: card for card in tab.home.grid.widgets()}
    cards["Earthbound"].clicked.emit(cards["Earthbound"].game)
    assert tab.currentWidget().cover.badge == "sd"
    tab.back()
    cards["Celeste"].clicked.emit(cards["Celeste"].game)
    page = tab.currentWidget()
    assert page.cover.badge == "sd"
    assert "Windows Games/.prefixes/Celeste" in page.saves_note()  # on the drive, not the card


@pytest.mark.parametrize("kind", ["usb", "drive", "sd"])
def test_badge_is_drawn(qtbot, kind):
    from PySide6.QtGui import QColor, QPixmap

    from gamingcrypt.ui import library_icons
    from gamingcrypt.ui.game_widgets import Cover

    icon = library_icons.removable(kind, 32).toImage()
    assert any(icon.pixelColor(x, y).alpha() for x in range(32) for y in range(32))
    cover = Cover()
    qtbot.addWidget(cover)
    cover.setFixedSize(200, 300)
    picture = QPixmap(200, 300)
    picture.fill(QColor("#ffffff"))
    cover.setPixmap(picture)
    plain = cover.grab().toImage()
    cover.set_badge(kind)
    badged = cover.grab().toImage()
    assert badged.pixelColor(200 - 12, 12) != plain.pixelColor(200 - 12, 12)  # the top right corner
    assert badged.pixelColor(100, 150) == plain.pixelColor(100, 150)  # the picture itself as it was


# --- sticks that can't be used, mounting them, and the notice ---------------------------------

def test_sticks_with_nothing_to_mount():
    listing = {"blockdevices": [
        disk("sdb"),  # brand new: no file system at all
        disk("sdc", children=[part("sdc1", fstype="hfsplus")]),  # a Mac's
        disk("sdd", children=[part("sdd1", fstype="crypto_LUKS")]),  # encrypted: not ours to touch
        disk("sde", size=0, model="SD/MMC Card Reader"),  # a card reader with no card in it
    ]}
    found, unmounted, blank = parse(listing)
    assert found == [] and unmounted == []
    assert [(d.disk, d.problem) for d in blank] == [
        ("/dev/sdb", "Not formatted - format it to use it"),
        ("/dev/sdc", "Its file system (hfsplus) can't be used - format it")]
    assert not blank[0].usable and blank[0].name == "USB stick"


class Mounter:
    """A stick udisks won't mount (as when polkit says no)."""

    def __init__(self):
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(args[0])
        if args[0] == "udisksctl":
            return subprocess.CompletedProcess(args, 1, "", "Error mounting /dev/sdb1: GDBus.Error:org.freedesktop."
                                                            "UDisks2.Error.NotAuthorizedCanObtain: Not authorized")
        listing = {"blockdevices": [disk("sdb", children=[part("sdb1", label="STICK")])]}
        return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")


def test_one_that_wont_mount_says_why():
    system = Mounter()
    drives = Drives(run=system)
    assert drives.look() == []
    assert [d.problem for d in drives.unusable] == ["Couldn't be mounted: Not authorized"]
    assert drives.unusable[0].device == "/dev/sdb1" and drives.unusable[0].disk == "/dev/sdb"
    drives.look()
    assert system.calls.count("udisksctl") == 1 and len(drives.unusable) == 1  # not tried again, still said


def test_a_stick_being_formatted_isnt_mounted_in_between():
    system = FakeSystem()
    removable.BUSY.add("/dev/sdb")
    try:
        assert Drives(run=system).look() == []
        assert "udisksctl" not in system.calls
    finally:
        removable.BUSY.discard("/dev/sdb")


class StickWithoutTable:
    """A stick with its file system right on the disk (/dev/sda, no partition table), mounted."""

    def __init__(self, mount, already=False, unmount_says=""):
        self.mount, self.already, self.unmount_says = mount, already, unmount_says
        self.calls = []

    def __call__(self, args, **_kwargs):
        self.calls.append(args)
        if args[0] == "lsblk":
            listing = {"blockdevices": [{**disk("sda"), "fstype": "vfat", "children": [],
                                         "mountpoints": ["/run/media/me/OLD"]}]}
            return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")
        if args[:2] == ["udisksctl", "unmount"]:
            return subprocess.CompletedProcess(args, 1 if self.unmount_says else 0, "", self.unmount_says)
        if args[0] == "gdbus":
            assert removable.BUSY == {"/dev/sda"}  # (the app doesn't mount it meanwhile)
            return subprocess.CompletedProcess(args, 0, "(objectpath '/org/freedesktop/UDisks2/block_devices/sda1',)", "")
        if args[:2] == ["udisksctl", "mount"]:
            if self.already:  # the desktop's automounter was quicker
                return subprocess.CompletedProcess(args, 1, "", "Error mounting /dev/sda1: GDBus.Error:org.freedesktop."
                                                   f"UDisks2.Error.AlreadyMounted: Device /dev/sda1 is already "
                                                   f"mounted at `{self.mount}'.")
            return subprocess.CompletedProcess(args, 0, f"Mounted /dev/sda1 at {self.mount}", "")
        raise AssertionError(args)


def test_format_a_stick_without_a_partition_table(tmp_path):
    stick = Removable(Path("/run/media/me/OLD"), "usb", "", "/dev/sda", "vfat", "/dev/sda", 16 * 1024 ** 3)
    system = StickWithoutTable(tmp_path / "NEW")
    now = removable.format_drive(stick, "exfat", "", run=system)
    unmounts = [c for c in system.calls if c[:2] == ["udisksctl", "unmount"]]
    assert [c[-1] for c in unmounts] == ["/dev/sda"]  # once - not again as its own "partition"
    assert now.mount == tmp_path / "NEW" and now.device == "/dev/sda1" and removable.BUSY == set()


def test_not_mounted_any_more_is_fine_and_the_automounter_may_be_quicker(tmp_path):
    stick = Removable(Path("/x"), "usb", "", "/dev/sda", "vfat", "/dev/sda")
    system = StickWithoutTable(tmp_path / "AUTO", already=True,
                               unmount_says="Error unmounting /dev/sda: GDBus.Error:org.freedesktop.UDisks2.Error."
                                            "NotMounted: Device `/dev/sda' is not mounted")
    assert removable.format_drive(stick, "ext4", "", run=system, layout=False).mount == tmp_path / "AUTO"


def test_a_failed_format_lets_it_be_mounted_again(tmp_path):
    stick = Removable(Path("/x"), "usb", "", "/dev/sda", "vfat", "/dev/sda")
    with pytest.raises(removable.FormatError):
        removable.format_drive(stick, "ext4", "", run=StickWithoutTable(tmp_path, unmount_says="target is busy"))
    assert removable.BUSY == set()


def test_a_new_stick_is_announced(tmp_path):
    from types import SimpleNamespace

    from gamingcrypt.app import MainWindow as App

    said = []
    app = SimpleNamespace(notify=lambda text, icon: said.append((icon, text)))
    old = Removable(tmp_path / "OLD", "usb", "OLD", "/dev/sdb1", disk="/dev/sdb")
    App.drives_arrived(app, [old], [])
    assert said == []  # in already when the drive was unlocked
    new = Removable(tmp_path / "GAMES", "sd", "GAMES", "/dev/mmcblk1p1", disk="/dev/mmcblk1")
    blank = Removable(Path(), "usb", "", "/dev/sdc", disk="/dev/sdc", problem="Not formatted - format it to use it")
    App.drives_arrived(app, [old, new], [blank])
    assert said == [("🔌", "GAMES (SD card) is ready - its games are in the list"),
                    ("⚠", "USB stick can't be used: Not formatted - format it to use it. Settings → Storage formats it")]
    App.drives_arrived(app, [old, new], [blank])
    assert len(said) == 2  # once


def test_storage_lists_a_stick_that_cant_be_used(qtbot, monkeypatch):
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    qtbot.addWidget(page)
    page.show()
    blank = Removable(Path(), "usb", "", "/dev/sdc", disk="/dev/sdc", size=8 * 1024 ** 3,
                      problem="Not formatted - format it to use it")
    page.set_drives([], [blank])
    assert page.drives_heading.isVisible()
    text, problem, button = page.drive_rows[("unusable", "/dev/sdc", "/dev/sdc")]
    assert text.text() == "USB stick\nUSB stick  ·  8.0 GB" and "Not formatted" in problem.text()
    monkeypatch.setattr(removable, "formats", lambda: ["exfat"])
    button.click()
    assert page.formatter is not None and page.formatter.drive is blank
    page.formatter.cancel_button.click()
    page.set_drives([], [])
    assert not page.drives_heading.isVisible()

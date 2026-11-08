"""How fast a stick is: looked at once when it's put in the first time - its USB port and a short
write test - kept on the encrypted drive, shown in Settings → Storage; a slow one gets a notice."""

import json
import os
from pathlib import Path

import pytest

from gamingcrypt import stick_memory
from gamingcrypt.system import drive_speed
from gamingcrypt.system.removable import Removable
from tests.test_code_dialogs import rect_in, screen
from tests.test_remembered_games import config, drive, make_tab  # noqa: F401 - fixtures

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1024, 600)]


def usb_device(sys_root: Path, disk: str, speed: str) -> None:
    """/sys as Linux has it: block/<disk>/device -> devices/.../<usb device>/.../<scsi device>, the USB
    device's folder with its idVendor and speed."""
    usb = sys_root / "devices" / "pci0000:00" / "0000:00:14.0" / "usb2" / "2-1"
    scsi = usb / "2-1:1.0" / "host3" / "target3:0:0" / "3:0:0:0"
    scsi.mkdir(parents=True)
    (usb / "idVendor").write_text("0781\n")
    (usb / "speed").write_text(f"{speed}\n")
    (usb.parent / "speed").write_text("5000\n")  # (the hub - not the stick)
    block = sys_root / "block" / disk
    block.mkdir(parents=True)
    (block / "device").symlink_to(scsi)


@pytest.mark.parametrize("speed,version", [("480", "2.0"), ("5000", "3.0"), ("10000", "3.1"), ("12", "1.1")])
def test_the_usb_port(tmp_path, speed, version):
    usb_device(tmp_path, "sdb", speed)
    assert drive_speed.usb_version("/dev/sdb", tmp_path) == version


def test_not_on_usb(tmp_path):
    (tmp_path / "devices" / "platform" / "mmc0" / "mmc0:0001").mkdir(parents=True)
    (tmp_path / "block" / "mmcblk1").mkdir(parents=True)
    (tmp_path / "block" / "mmcblk1" / "device").symlink_to(tmp_path / "devices" / "platform" / "mmc0" / "mmc0:0001")
    assert drive_speed.usb_version("/dev/mmcblk1", tmp_path) is None
    assert drive_speed.usb_version("/dev/sdz", tmp_path) is None and drive_speed.usb_version("", tmp_path) is None


def test_the_write_test_leaves_nothing(tmp_path):
    stick = tmp_path / "STICK"
    stick.mkdir()
    ticks = iter([0.0, 0.5])
    speed = drive_speed.write_speed(stick, size=2 * 1024 ** 2, clock=lambda: next(ticks))
    assert speed == 4.0 and list(stick.iterdir()) == []  # 2 MB in half a second; the file gone
    assert drive_speed.write_speed(tmp_path / "missing") is None


def test_slow_and_how_its_said():
    assert drive_speed.slow({"usb": "2.0", "write": 80.0})
    assert drive_speed.slow({"usb": "3.0", "write": 9.0})
    assert not drive_speed.slow({"usb": "3.0", "write": 90.0}) and not drive_speed.slow(None)
    assert drive_speed.describe({"usb": "3.0", "write": 94.6}) == "USB 3.0  ·  writes 95 MB/s"
    assert drive_speed.describe({"usb": "2.0", "write": 30.0}) == "USB 2.0  ·  writes 30 MB/s  ·  🐢 slow"
    assert drive_speed.describe({"usb": None, "write": 40.0}) == "writes 40 MB/s"
    assert "USB 3 port" in drive_speed.why_slow("GAMES", {"usb": "2.0", "write": 30.0})
    assert drive_speed.why_slow("GAMES", {"usb": "3.0", "write": 9.4}).startswith("GAMES writes only 9 MB/s")


def test_a_read_only_one_isnt_written_to(tmp_path):
    card = tmp_path / "CARD"
    card.mkdir()
    locked = Removable(card, "sd", "CARD", read_only="locked")
    assert drive_speed.measure(locked)["write"] is None and list(card.iterdir()) == []


@pytest.fixture
def slow_usb(tmp_path, monkeypatch):
    sys_root = tmp_path / "sys"
    usb_device(sys_root, "sdb", "480")
    monkeypatch.setattr(drive_speed, "SYS", sys_root)
    mount = tmp_path / "SLOW"
    mount.mkdir()
    return Removable(mount, "usb", "SLOW", "/dev/sdb1", "exfat", "/dev/sdb", uuid="77")


def test_measured_once_kept_on_the_drive_and_said(qtbot, drive, config, slow_usb):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    said = []
    tab.notify = lambda text, icon: said.append((icon, text))
    tab.set_drives([slow_usb])
    qtbot.waitUntil(lambda: bool(said))
    assert said[0][0] == "🐢" and said[0][1].startswith("SLOW is in a USB 2.0 port")
    data = json.loads((drive / ".gamingcrypt" / "sticks.json").read_text())
    assert data["fs:77"]["speed"]["usb"] == "2.0" and data["fs:77"]["speed"]["write"] > 0
    tab.set_drives([])
    tab.set_drives([slow_usb])  # put in again: known - not measured or said again
    qtbot.wait(200)
    assert len(said) == 1


def test_nothing_measured_while_the_drive_isnt_mounted(qtbot, drive, config, slow_usb, monkeypatch):  # noqa: F811
    monkeypatch.setattr(stick_memory, "REQUIRE_MOUNT", True)  # (locked: its folder an empty one)
    tab = make_tab(qtbot, drive, config)
    measured = []
    monkeypatch.setattr(drive_speed, "measure", lambda d, *a, **k: measured.append(d) or {})
    tab.set_drives([slow_usb])
    qtbot.wait(100)
    assert measured == []


@pytest.mark.parametrize("w,h", SCREENS)
def test_shown_in_storage(qtbot, drive, config, slow_usb, w, h):  # noqa: F811
    from gamingcrypt.ui.storage_page import StoragePage

    tab = make_tab(qtbot, drive, config)
    tab.notify = lambda *_a: None
    tab.set_drives([slow_usb])
    qtbot.waitUntil(lambda: tab.stick_memory.speed("fs:77") is not None)
    host = screen(qtbot, w, h)
    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.library_fn = lambda: tab
    page.setParent(host)
    page.resize(host.size())
    page.show()
    page.set_drives([slow_usb])
    qtbot.wait(20)
    text = page.drive_rows[slow_usb][0]
    assert "USB 2.0  ·  writes" in text.text() and "🐢 slow" in text.text()
    assert host.rect().contains(rect_in(text, host))

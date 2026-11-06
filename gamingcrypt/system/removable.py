"""USB sticks, USB drives and SD cards: their games are in the Games tab too, as long as they're in.

A drive is looked at like the encrypted one: ROMs in Emulation/roms/<system> (or roms/<system>),
Windows games in "Windows Games", Linux games in "Linux Games". Saves, save states, covers,
settings and Wine prefixes stay on the encrypted drive - the stick only carries the games.

In gaming mode nothing mounts a drive that's put in (no desktop's automounter): a partition
with a file system that isn't mounted is mounted through udisks, as the desktop would.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("usb", "drive", "sd")  # a USB stick, a USB hard disk / SSD, an SD card
LABELS = {"usb": "USB stick", "drive": "USB drive", "sd": "SD card"}
MOUNTABLE = {"vfat", "exfat", "ntfs", "ntfs3", "ext2", "ext3", "ext4", "btrfs", "f2fs", "xfs"}
SYSTEM_MOUNTS = ("/", "/boot", "/boot/efi", "/efi", "/home", "/usr", "/var", "/nix", "[SWAP]")
CARD_READER = re.compile(r"\b(sd|sdxc|sdhc|mmc|micro ?sd|card ?reader|cardreader)\b", re.IGNORECASE)
DRIVE_FROM = 256 * 1024 ** 3  # bigger than any common stick: a USB hard disk or SSD
LSBLK = ["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,TRAN,RM,HOTPLUG,ROTA,SIZE,FSTYPE,MOUNTPOINTS,LABEL,MODEL"]


@dataclass(frozen=True)
class Removable:
    mount: Path  # where it's mounted
    kind: str  # one of KINDS
    label: str = ""  # its name ("SANDISK", "Games") - "" when it has none
    device: str = field(default="", compare=False)  # /dev/sdb1

    @property
    def name(self) -> str:
        return self.label or LABELS[self.kind]

    def roms(self) -> list[Path]:
        """Where its ROMs may be: <drive>/Emulation/roms like on the encrypted drive, or <drive>/roms."""
        return [self.mount / "Emulation" / "roms", self.mount / "roms"]

    @property
    def windows(self) -> Path:
        return self.mount / "Windows Games"

    @property
    def linux(self) -> Path:
        return self.mount / "Linux Games"


def _mounts(node: dict) -> list[str]:
    points = node.get("mountpoints")
    if points is None:  # util-linux before 2.37
        points = [node.get("mountpoint")]
    return [p for p in points if p]


def _is_sd_slot(name: str) -> bool:
    """mmcblk0 is an SD card in its slot - or the device's own eMMC (its system on it)."""
    try:
        return Path(f"/sys/block/{name}/device/type").read_text().strip() == "SD"
    except OSError:
        return True  # (can't say: the system's own is left out by its mount points)


def kind_of(disk: dict) -> str | None:
    """"usb", "drive", "sd" - None: not one that's put in and taken out."""
    name, tran, model = disk.get("name") or "", disk.get("tran") or "", disk.get("model") or ""
    if name.startswith("mmcblk"):
        return "sd" if _is_sd_slot(name) else None
    if tran == "usb":
        if CARD_READER.search(model):
            return "sd"
        rotating = disk.get("rota") in (True, "1", 1)
        return "drive" if rotating or int(disk.get("size") or 0) > DRIVE_FROM else "usb"
    if tran in ("", None) and disk.get("type") == "disk" and disk.get("rm") in (True, "1", 1):
        return "usb"  # removable, but lsblk can't say how it's connected
    return None


def _partitions(disk: dict) -> list[dict]:
    """The disk itself when it has a file system (a stick formatted without a partition table),
    otherwise its partitions."""
    if disk.get("fstype") and not disk.get("children"):
        return [disk]
    return [c for c in disk.get("children") or [] if c.get("type") == "part"]


def parse(listing: dict, exclude: tuple[str, ...] = ()) -> tuple[list[Removable], list[dict]]:
    """lsblk's JSON: the mounted removable drives and the partitions that could be mounted.
    exclude: mount points that are never one of them (the encrypted drive)."""
    found, unmounted = [], []
    excluded = [os.path.realpath(p) for p in exclude if p]
    for disk in listing.get("blockdevices") or []:
        if disk.get("type") != "disk":
            continue
        kind = kind_of(disk)
        if kind is None:
            continue
        partitions = _partitions(disk)
        everything = [disk, *partitions, *(c for p in partitions for c in p.get("children") or [])]
        if any(point in SYSTEM_MOUNTS for node in everything for point in _mounts(node)):
            continue  # the device's own system is on it
        for part in partitions:
            points = _mounts(part)
            if not points:
                if (part.get("fstype") or "") in MOUNTABLE:
                    unmounted.append(part)
                continue
            point = points[0]
            real = os.path.realpath(point)
            if any(real == e or real.startswith(e + os.sep) or e.startswith(real + os.sep) for e in excluded):
                continue
            found.append(Removable(Path(point), kind, (part.get("label") or "").strip(), part.get("path") or ""))
    return found, unmounted


def _run(*args, **kwargs):
    return subprocess.run(*args, **kwargs)  # (tests: never the dev machine's own drives)


class Drives:
    """What's in right now - asked again on every look (a few seconds apart, in the background)."""

    def __init__(self, exclude: tuple[str, ...] = (), mount: bool = True, run=None):
        self.exclude = exclude
        self.mount = mount
        self.run = run or (lambda *a, **k: _run(*a, **k))
        self.tried: set[str] = set()  # partitions that wouldn't mount: not tried again until they're out

    def look(self) -> list[Removable]:
        try:
            out = self.run(LSBLK, capture_output=True, text=True, timeout=10)
            listing = json.loads(out.stdout or "{}")
        except (OSError, ValueError, subprocess.SubprocessError):
            return []
        found, unmounted = parse(listing, self.exclude)
        present = {p.get("path") for p in unmounted}
        self.tried &= present  # taken out: tried again when it's back
        if self.mount:
            for part in unmounted:
                path = part.get("path") or ""
                if not path or path in self.tried:
                    continue
                self.tried.add(path)
                if self._mount(path):
                    return self.look()  # mounted: found with its mount point
        return sorted(found, key=lambda d: str(d.mount))

    def _mount(self, device: str) -> bool:
        try:
            out = self.run(["udisksctl", "mount", "--no-user-interaction", "-b", device],
                           capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            log.info("couldn't mount %s: %s", device, exc)
            return False
        if out.returncode != 0:
            log.info("couldn't mount %s: %s", device, (out.stderr or "").strip())
            return False
        log.info("mounted %s: %s", device, (out.stdout or "").strip())
        return True

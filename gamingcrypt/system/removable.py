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
    fstype: str = field(default="", compare=False)  # "exfat", "vfat", "ext4" ...
    disk: str = field(default="", compare=False)  # the whole stick: /dev/sdb
    size: int = field(default=0, compare=False)  # the whole stick's, in bytes

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
            found.append(Removable(Path(point), kind, (part.get("label") or "").strip(), part.get("path") or "",
                                   part.get("fstype") or "", disk.get("path") or "", int(disk.get("size") or 0)))
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


# formatting ----------------------------------------------------------------------------------
UDISKS = "org.freedesktop.UDisks2"
FORMATS = {  # file system -> (what it's good for, its partition type in an MBR / a GPT table)
    "exfat": ("Works everywhere: Linux, Windows, Mac, most consoles. Not for Linux games",
              "0x07", "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"),
    "ext4": ("Linux only - Linux games start from it", "0x83", "0fc63daf-8483-4772-8e79-3d69d8477de4"),
}
MBR_UP_TO = 2 * 1024 ** 4  # bigger: a GPT table (an MBR can't reach past 2 TiB)
TOOL_FOLDERS = ("/usr/bin", "/usr/sbin", "/sbin", "/bin")


class FormatError(Exception):
    """Not formatted - and why, as a person says it."""


def formats(which=None) -> list[str]:
    """The file systems this device can make (udisks needs mkfs.<name> for it)."""
    import shutil

    which = which or (lambda name: shutil.which(name, path=os.pathsep.join([os.environ.get("PATH", ""),
                                                                           *TOOL_FOLDERS])))
    return [name for name in FORMATS if which(f"mkfs.{name}")]


def clean_label(label: str) -> str:
    """What every file system takes as a name: letters, digits, - and _, 11 at most."""
    label = re.sub(r"[^A-Za-z0-9_-]+", "", label.replace(" ", "_"))[:11]
    return label or "GAMES"


def _object(device: str) -> str:
    return f"/org/freedesktop/UDisks2/block_devices/{Path(device).name}"


def _gdbus(run, device: str, method: str, *args: str) -> str:
    out = run(["gdbus", "call", "--system", "--timeout", "1200", "--dest", UDISKS, "--object-path",
               _object(device), "--method", f"{UDISKS}.{method}", *args], capture_output=True, text=True,
              timeout=1300)
    if out.returncode != 0:
        lines = (out.stderr or "").strip().splitlines()
        # "Error: GDBus.Error:org.freedesktop.UDisks2.Error.Failed: Error formatting ...": the last part
        message = re.sub(r"^(Error: )?(GDBus\.Error:[\w.]+: )?", "", lines[-1]) if lines else ""
        raise FormatError(message or f"{method} failed")
    return out.stdout or ""


def format_drive(drive: Removable, fstype: str, label: str, run=None, layout=True) -> Removable:
    """Everything on the stick is deleted: a new partition table with one partition, the whole
    stick, in fstype. Mounted again, with the folders for games made (layout) - the stick as it is now."""
    from gamingcrypt.emulation.systems import SYSTEMS

    run = run or (lambda *a, **k: _run(*a, **k))
    if fstype not in FORMATS:
        raise FormatError(f"Can't format as {fstype}")
    if not drive.disk:
        raise FormatError("It isn't known which stick that is")
    label = clean_label(label)
    listing = json.loads(run(LSBLK, capture_output=True, text=True, timeout=10).stdout or "{}")
    disk = next((d for d in listing.get("blockdevices") or [] if d.get("path") == drive.disk), None)
    if disk is None:
        raise FormatError(f"{drive.name} isn't there any more")
    for part in [disk, *_partitions(disk)]:
        if _mounts(part):
            out = run(["udisksctl", "unmount", "--no-user-interaction", "-b", part["path"]],
                      capture_output=True, text=True, timeout=60)
            if out.returncode != 0:
                raise FormatError(f"{drive.name} is in use - close what's open on it "
                                  f"({(out.stderr or '').strip() or 'busy'})")
    table = "dos" if int(disk.get("size") or 0) <= MBR_UP_TO else "gpt"
    kind = FORMATS[fstype][1 if table == "dos" else 2]
    _gdbus(run, drive.disk, "Block.Format", table, "{}")
    out = _gdbus(run, drive.disk, "PartitionTable.CreatePartitionAndFormat", "0", "0", kind, "", "{}", fstype,
                 f"{{'label': <'{label}'>, 'take-ownership': <true>}}")
    found = re.search(r"block_devices/([A-Za-z0-9_]+)", out)
    device = f"/dev/{found.group(1)}" if found else ""
    if not device:
        raise FormatError("It was formatted, but the new partition wasn't found")
    out = run(["udisksctl", "mount", "--no-user-interaction", "-b", device], capture_output=True, text=True,
              timeout=60)
    mounted = re.search(r" at (.+?)\.?$", (out.stdout or "").strip())
    if out.returncode != 0 or not mounted:
        raise FormatError(f"It was formatted, but couldn't be mounted: {(out.stderr or '').strip()}")
    now = Removable(Path(mounted.group(1)), drive.kind, label, device, fstype, drive.disk, drive.size)
    if layout:
        for system in SYSTEMS:
            (now.mount / "Emulation" / "roms" / system.folder).mkdir(parents=True, exist_ok=True)
        now.windows.mkdir(exist_ok=True)
        now.linux.mkdir(exist_ok=True)
    return now

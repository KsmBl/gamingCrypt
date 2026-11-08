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
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

log = logging.getLogger(__name__)

KINDS = ("usb", "drive", "sd")  # a USB stick, a USB hard disk / SSD, an SD card
LABELS = {"usb": "USB stick", "drive": "USB drive", "sd": "SD card"}
MOUNTABLE = {"vfat", "exfat", "ntfs", "ntfs3", "ext2", "ext3", "ext4", "btrfs", "f2fs", "xfs"}
SYSTEM_MOUNTS = ("/", "/boot", "/boot/efi", "/efi", "/home", "/usr", "/var", "/nix", "[SWAP]")
CARD_READER = re.compile(r"\b(sd|sdxc|sdhc|mmc|micro ?sd|card ?reader|cardreader)\b", re.IGNORECASE)
DRIVE_FROM = 256 * 1024 ** 3  # bigger than any common stick: a USB hard disk or SSD
LSBLK = ["lsblk", "-J", "-b", "-o", "NAME,PATH,TYPE,TRAN,RM,HOTPLUG,ROTA,SIZE,FSTYPE,MOUNTPOINTS,LABEL,MODEL,UUID,RO"]


@dataclass(frozen=True)
class Removable:
    mount: Path  # where it's mounted
    kind: str  # one of KINDS
    label: str = ""  # its name ("SANDISK", "Games") - "" when it has none
    device: str = field(default="", compare=False)  # /dev/sdb1
    fstype: str = field(default="", compare=False)  # "exfat", "vfat", "ext4" ...
    disk: str = field(default="", compare=False)  # the whole stick: /dev/sdb
    size: int = field(default=0, compare=False)  # the whole stick's, in bytes
    problem: str = field(default="", compare=False)  # not usable (not mounted): why - "" when it is
    uuid: str = field(default="", compare=False)  # its file system's id: which stick it is (not its name)
    # nothing can be written to it: "locked" (an SD card's write protection switch) or "damaged" (mounted
    # read-only: it wasn't ejected safely, its file system needs a repair) - "" when it can be
    read_only: str = field(default="", compare=False)
    container: str = field(default="", compare=False)  # encrypted: its VeraCrypt container (stick_crypt.py)
    host: Path | None = field(default=None, compare=False)  # ... and where the stick itself is mounted

    @property
    def encrypted(self) -> bool:
        return bool(self.container)

    @property
    def usable(self) -> bool:
        return not self.problem

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


def _unusable(disk: dict, kind: str, problem: str, part: dict | None = None) -> Removable:
    """A stick that's in but has nothing to mount (yet): shown in Settings → Storage to be formatted."""
    part = part or disk
    return Removable(Path(), kind, (part.get("label") or "").strip(), part.get("path") or "", part.get("fstype") or "",
                     disk.get("path") or "", int(disk.get("size") or 0), problem)


READ_ONLY = {"locked": "Write-protected - move the switch on its side to unlock it, then put it in again",
             "damaged": "Read-only - it was taken out without ejecting it: repair it"}


def _yes(value) -> bool:
    return value in (True, 1, "1", "true")


def parse(listing: dict, exclude: tuple[str, ...] = (), ro_mounts: set | frozenset = frozenset()
          ) -> tuple[list[Removable], list[dict], list[Removable]]:
    """lsblk's JSON: the mounted removable drives, the partitions that could be mounted, and the
    sticks with nothing to mount (no file system, or one that can't be used: problem says).
    exclude: mount points that are never one of them (the encrypted drive). ro_mounts: the mount
    points mounted read-only (read_only_mounts())."""
    found, unmounted, blank = [], [], []
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
        if not any(_mounts(n) for n in everything) and not any((p.get("fstype") or "") in MOUNTABLE
                                                               for p in partitions):
            if not int(disk.get("size") or 0):
                continue  # a card reader without a card
            if any(p.get("fstype") == "crypto_LUKS" or n.get("type") == "crypt" for n in everything
                   for p in [n]):
                continue  # encrypted: not ours to touch (maybe even the games drive itself)
            known = [p.get("fstype") for p in partitions if p.get("fstype")]
            blank.append(_unusable(disk, kind, f"Its file system ({known[0]}) can't be used - format it" if known
                                   else "Not formatted - format it to use it"))
            continue
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
            locked = _yes(disk.get("ro")) or _yes(part.get("ro"))
            read_only = "locked" if locked else "damaged" if point in ro_mounts else ""
            found.append(Removable(Path(point), kind, (part.get("label") or "").strip(), part.get("path") or "",
                                   part.get("fstype") or "", disk.get("path") or "", int(disk.get("size") or 0),
                                   uuid=(part.get("uuid") or "").lower(), read_only=read_only))
    return found, unmounted, blank


MOUNTS = Path("/proc/self/mounts")


def read_only_mounts(mounts: Path | None = None) -> set[str]:
    """The mount points mounted read-only (ro among their options)."""
    found = set()
    try:
        lines = (mounts or MOUNTS).read_text().splitlines()
    except OSError:
        return found
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and "ro" in parts[3].split(","):
            found.add(parts[1].replace("\\040", " ").replace("\\011", "\t"))
    return found


def _run(*args, **kwargs):
    return subprocess.run(*args, **kwargs)  # (tests: never the dev machine's own drives)


class Drives:
    """What's in right now - asked again on every look (a few seconds apart, in the background)."""

    def __init__(self, exclude: tuple[str, ...] = (), mount: bool = True, run=None, crypt_factory=None):
        self.exclude = exclude
        self.mount = mount
        self.run = run or (lambda *a, **k: _run(*a, **k))
        self.crypt_factory = crypt_factory  # (tests: a stand-in VeraCrypt for the encrypted sticks)
        # by container id (stick_crypt.container_id) - not path: a stick renamed / mounted elsewhere is the same
        self.opened: dict[str, str] = {}  # the containers this opened -> their path (closed when the stick is out)
        self.refused: dict[str, str] = {}  # container -> the password it didn't open with (not tried again)
        self.tried: dict[str, str] = {}  # partitions that wouldn't mount -> why: not tried again until they're out
        self.unusable: list[Removable] = []  # (after look()) sticks that are in but can't be used: why

    def look(self) -> list[Removable]:
        """The sticks that are mounted - a new one is mounted first, ready for games. The ones that
        are in but couldn't be mounted (or have no file system) are in self.unusable."""
        try:
            out = self.run(LSBLK, capture_output=True, text=True, timeout=10)
            listing = json.loads(out.stdout or "{}")
        except (OSError, ValueError, subprocess.SubprocessError):
            return []
        found, unmounted, blanks = parse(listing, self.exclude, read_only_mounts())
        disks = {d.get("path"): d for d in listing.get("blockdevices") or []}
        present = {p.get("path") for p in unmounted}
        self.tried = {path: why for path, why in self.tried.items() if path in present}  # out: tried again when back
        unusable = []
        for part in unmounted:
            path = part.get("path") or ""
            disk = next((d for d in disks.values() if part is d or part in (d.get("children") or [])), {})
            if not path or disk.get("path") in BUSY:
                continue  # (being formatted: not mounted in between)
            if self.mount and path not in self.tried:
                why = self._mount(path)
                if not why:
                    return self.look()  # mounted: found with its mount point
                self.tried[path] = why
            if path in self.tried:
                unusable.append(_unusable(disk, kind_of(disk) or "usb", f"Couldn't be mounted: {self.tried[path]}",
                                          part))
        found = self._open_encrypted(found, unusable)
        self.unusable = [d for d in [*blanks, *unusable] if d.disk not in BUSY]
        return sorted(found, key=lambda d: str(d.mount))

    def _open_encrypted(self, found: list, unusable: list) -> list:
        """A stick with GamingCrypt's container: opened with the drive's password (stick_crypt.py) -
        the games are inside. Containers whose stick was taken out are closed."""
        from gamingcrypt.system import stick_crypt

        shown, present = [], set()
        password = stick_crypt.keys.password
        for stick in found:
            volume = stick_crypt.container_of(stick.mount) if stick.disk not in BUSY else None
            if volume is None:
                shown.append(stick)
                continue
            volume = str(volume)
            ident = stick_crypt.container_id(volume)
            present.add(ident)
            locked = replace(stick, container=volume, host=stick.mount)
            if stick.read_only:  # (VeraCrypt can't open it so: it would want to write)
                unusable.append(replace(locked, problem=READ_ONLY[stick.read_only]))
                continue
            if password is None:
                if stick_crypt.is_open(volume):
                    shown.append(replace(locked, mount=stick_crypt.mount_dir(volume), fstype="ext4"))
                else:
                    unusable.append(replace(locked, problem=stick_crypt.NEEDS_CODE))
                continue
            if self.refused.get(ident) == password:
                unusable.append(replace(locked, problem=stick_crypt.EARLIER))
                continue
            opened = stick_crypt.open_stick(stick, password, self.crypt_factory)
            if opened.problem:
                if opened.problem == stick_crypt.EARLIER:
                    self.refused[ident] = password
                unusable.append(opened)
                continue
            self.refused.pop(ident, None)
            self.opened[ident] = volume
            shown.append(opened)
        for ident in sorted(set(self.opened) - present):  # taken out while open
            stick_crypt.close(self.opened.pop(ident), self.crypt_factory)
        self.refused = {v: p for v, p in self.refused.items() if v in present}
        return shown

    def close_all(self) -> None:
        """The panic lock: every stick's container closed (its games aren't there any more)."""
        from gamingcrypt.system import stick_crypt

        for volume in sorted(self.opened.values()):
            stick_crypt.close(volume, self.crypt_factory)
        self.opened.clear()

    def _mount(self, device: str) -> str:
        """"" when it's mounted - otherwise why not."""
        try:
            out = self.run(["udisksctl", "mount", "--no-user-interaction", "-b", device],
                           capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            log.info("couldn't mount %s: %s", device, exc)
            return str(exc)
        if out.returncode != 0:
            why = (out.stderr or "").strip().splitlines()
            log.info("couldn't mount %s: %s", device, why)
            return re.sub(r"^Error mounting [^:]+: (GDBus\.Error:[\w.]+: )?", "", why[-1]) if why else "it failed"
        log.info("mounted %s: %s", device, (out.stdout or "").strip())
        return ""


# formatting ----------------------------------------------------------------------------------
UDISKS = "org.freedesktop.UDisks2"
FORMATS = {  # file system -> (what it's good for, its partition type in an MBR / a GPT table)
    "exfat": ("Works everywhere: Linux, Windows, Mac, most consoles. Not for Linux games",
              "0x07", "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"),
    "ext4": ("Linux only - Linux games start from it", "0x83", "0fc63daf-8483-4772-8e79-3d69d8477de4"),
}
BUSY: set[str] = set()  # disks being formatted (/dev/sdb): nothing mounts them meanwhile
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


# what formatting does, one after the other (step(key) is called as each one starts)
STEPS = (("check", "Checking the drive"), ("unmount", "Unmounting it"), ("table", "Writing a new partition table"),
         ("filesystem", "Creating the {fs} file system"), ("mount", "Mounting it again"),
         ("encrypt", "Encrypting it (a VeraCrypt container, your code)"), ("folders", "Making the folders for games"))


def steps(encrypted: bool) -> tuple:
    """What formatting does - encrypting only when it's asked to."""
    return tuple(s for s in STEPS if encrypted or s[0] != "encrypt")


def format_drive(drive: Removable, fstype: str, label: str, run=None, layout=True, step=None,
                 encrypt=None) -> Removable:
    """Everything on the stick is deleted (see _format) - and meanwhile the app doesn't mount it again
    (it looks every few seconds: a stick mounted between unmounting and formatting is busy)."""
    BUSY.add(drive.disk)
    try:
        return _format(drive, fstype, label, run, layout, step, encrypt)
    finally:
        BUSY.discard(drive.disk)


def _unmount(run, drive: Removable, disk: dict) -> None:
    """Every mounted file system on the stick, once each (a stick without a partition table has its file
    system on the disk itself: it's the disk and its "partition" at once)."""
    nodes = {}
    for node in [disk, *(disk.get("children") or []), *(c for p in disk.get("children") or []
                                                         for c in p.get("children") or [])]:
        if node.get("path") and _mounts(node):
            nodes.setdefault(node["path"], node)
    for path in nodes:
        out = run(["udisksctl", "unmount", "--no-user-interaction", "-b", path], capture_output=True, text=True,
                  timeout=60)
        why = (out.stderr or "").strip()
        if out.returncode != 0 and "not mounted" not in why.lower():  # (gone already: fine)
            raise FormatError(f"{drive.name} is in use - close what's open on it ({why or 'busy'})")


def _mount_new(run, device: str) -> Path:
    """The new partition mounted - or where the desktop's automounter was quicker to mount it."""
    for _try in range(5):
        out = run(["udisksctl", "mount", "--no-user-interaction", "-b", device], capture_output=True, text=True,
                  timeout=60)
        text = f"{out.stdout or ''}\n{out.stderr or ''}"
        mounted = re.search(r"Mounted \S+ at (.+?)\.?$", (out.stdout or "").strip(), re.MULTILINE)
        if out.returncode == 0 and mounted:
            return Path(mounted.group(1))
        already = re.search(r"already mounted at [`'\"](.+?)[`'\"]", text)
        if already:
            return Path(already.group(1))
        time.sleep(1)  # (the kernel may still be reading the new partition table)
    raise FormatError(f"It was formatted, but couldn't be mounted: {(out.stderr or '').strip()}")


def _format(drive: Removable, fstype: str, label: str, run=None, layout=True, step=None,
            encrypt=None) -> Removable:
    """encrypt(stick) -> the stick opened (stick_crypt.create): a VeraCrypt container filling it, the
    folders for games made inside."""
    """Everything on the stick is deleted: a new partition table with one partition, the whole
    stick, in fstype. Mounted again, with the folders for games made (layout) - the stick as it is now.
    step(key): each of STEPS as it starts (from this thread)."""
    from gamingcrypt.emulation.systems import SYSTEMS

    run = run or (lambda *a, **k: _run(*a, **k))
    step = step or (lambda _key: None)
    step("check")
    if fstype not in FORMATS:
        raise FormatError(f"Can't format as {fstype}")
    if not drive.disk:
        raise FormatError("It isn't known which stick that is")
    label = clean_label(label)
    listing = json.loads(run(LSBLK, capture_output=True, text=True, timeout=10).stdout or "{}")
    disk = next((d for d in listing.get("blockdevices") or [] if d.get("path") == drive.disk), None)
    if disk is None:
        raise FormatError(f"{drive.name} isn't there any more")
    step("unmount")
    if drive.container:  # an encrypted stick: its container closed first (it keeps the stick busy)
        from gamingcrypt.system import stick_crypt

        if not stick_crypt.close(drive.container):
            raise FormatError(f"{drive.name}'s encrypted container couldn't be closed - close what's open on it")
    _unmount(run, drive, disk)
    table = "dos" if int(disk.get("size") or 0) <= MBR_UP_TO else "gpt"
    kind = FORMATS[fstype][1 if table == "dos" else 2]
    step("table")
    _gdbus(run, drive.disk, "Block.Format", table, "{}")
    step("filesystem")
    out = _gdbus(run, drive.disk, "PartitionTable.CreatePartitionAndFormat", "0", "0", kind, "", "{}", fstype,
                 f"{{'label': <'{label}'>, 'take-ownership': <true>}}")
    found = re.search(r"block_devices/([A-Za-z0-9_]+)", out)
    device = f"/dev/{found.group(1)}" if found else ""
    if not device:
        raise FormatError("It was formatted, but the new partition wasn't found")
    step("mount")
    now = Removable(_mount_new(run, device), drive.kind, label, device, fstype, drive.disk, drive.size)
    if encrypt is not None:
        step("encrypt")
        now = encrypt(now)
    if layout:
        step("folders")
        for system in SYSTEMS:
            (now.mount / "Emulation" / "roms" / system.folder).mkdir(parents=True, exist_ok=True)
        now.windows.mkdir(exist_ok=True)
        now.linux.mkdir(exist_ok=True)
    return now


# repairing ----------------------------------------------------------------------------------
REPAIR_STEPS = (("unmount", "Unmounting it"), ("repair", "Checking and repairing its file system"),
                ("mount", "Mounting it again"))


def repair(drive: Removable, run=None, step=None) -> Removable:
    """A stick mounted read-only because it wasn't ejected safely: its file system checked and
    repaired (udisks - fsck), mounted again. The stick as it is now (RepairError: why not)."""
    run = run or (lambda *a, **k: _run(*a, **k))
    step = step or (lambda _key: None)
    if drive.read_only == "locked":
        raise FormatError(f"{drive.name} is write-protected: move the switch on its side, then put it in again")
    device = drive.device
    if not device:
        raise FormatError("It isn't known which stick that is")
    BUSY.add(drive.disk)
    try:
        step("unmount")
        if drive.container:
            from gamingcrypt.system import stick_crypt

            if not stick_crypt.close(drive.container):
                raise FormatError(f"{drive.name}'s encrypted container couldn't be closed - close what's open on it")
        out = run(["udisksctl", "unmount", "--no-user-interaction", "-b", device], capture_output=True, text=True,
                  timeout=60)
        why = (out.stderr or "").strip()
        if out.returncode != 0 and "not mounted" not in why.lower():
            raise FormatError(f"{drive.name} is in use - close what's open on it ({why or 'busy'})")
        step("repair")
        answer = _gdbus(run, device, "Filesystem.Repair", "{}")
        if "true" not in answer.lower():
            raise FormatError("Its file system couldn't be repaired - format it to use it again")
        step("mount")
        return replace(drive, mount=_mount_new(run, device), read_only="", container="", host=None)
    finally:
        BUSY.discard(drive.disk)

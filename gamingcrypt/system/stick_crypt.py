"""Encrypted USB sticks, USB drives and SD cards: a VeraCrypt container on them, opened with the code
of the encrypted drive.

The container (GamingCrypt.vc, filling the stick) has the same password as the drive's volume: the
admin's code through the same key derivation (scrypt, the same salt - kdf.py). So the codes that
unlock the drive open the stick too - the admin's, and every user's through their key slot
(keyslots.py). Next to it is its sidecar (GamingCrypt.vc.gamingcrypt.json, sidecar.py) with the
derivation's settings and the users' key slots, nothing secret: another device with GamingCrypt
opens it with the same codes, plain VeraCrypt with ``gamingcrypt --volume-password``.

While GamingCrypt is unlocked the volume's password is kept in memory (Keys) - the drive is open
then anyway. A stick put in is opened with it, its games in the list; the panic lock closes it.

A stick encrypted while the admin had another code doesn't open with today's password: it's opened
once with that code (its sidecar has the derivation it was made with) and given today's password.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import replace
from pathlib import Path

from gamingcrypt.unlock import kdf, keyslots, sidecar
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker

log = logging.getLogger(__name__)

CONTAINER = "GamingCrypt.vc"
MIN_SIZE_GB = 1
SPARE = 256 * 1024 ** 2  # left free next to the container (its sidecar, the file system's own)
EARLIER = "Encrypted with an earlier code (or another device's) - unlock it once with that code"
NEEDS_CODE = "Encrypted - unlock it with your code"


class Keys:
    """The drive's volume password while it's unlocked (None: locked, or not known since a restart)."""

    def __init__(self):
        self._password: str | None = None
        self.lock = threading.Lock()

    @property
    def password(self) -> str | None:
        with self.lock:
            return self._password

    def set(self, password: str | None) -> None:
        with self.lock:
            self._password = password

    def clear(self) -> None:
        self.set(None)


keys = Keys()


def container_of(mount: Path | str) -> Path | None:
    path = Path(mount) / CONTAINER
    return path if path.is_file() else None


_ids: dict[str, str] = {}  # container path -> its id (known after the stick is gone: to close it)


def container_id(volume: str | Path) -> str:
    """Which container it is - whatever the stick is called and wherever it's mounted: from the salt
    at the start of every VeraCrypt volume (64 random bytes, written once when it's made). Two
    sticks both called GAMES are two containers; a stick renamed, or mounted at GAMES1, is the same."""
    try:
        with open(volume, "rb") as f:
            head = f.read(64)
    except OSError:
        head = b""
    if len(head) == 64:
        _ids[str(volume)] = hashlib.sha256(head).hexdigest()[:16]
    return _ids.get(str(volume)) or hashlib.sha256(str(volume).encode()).hexdigest()[:16]


def mount_dir(volume: str | Path) -> Path:
    """Where a stick's container is opened: below the home folder (the helper allows it there) - one
    folder per container (container_id), not per path."""
    return Path(os.path.expanduser("~/.local/share/gamingcrypt/drives")) / container_id(volume)


def unlocker(volume: str | Path, factory=None, mount_point: Path | None = None) -> VeraCryptUnlocker:
    """The stick's password is the volume's password as it is (no derivation on top: kdf=None)."""
    where = mount_point if mount_point is not None else mount_dir(volume)
    cfg = {"volume": str(volume), "mount_point": str(where), "kdf": None, "keyring": None}
    return (factory or VeraCryptUnlocker.from_config)(cfg)


def write_info(volume: str | Path, unlock_cfg: dict, users: list | None = None) -> bool:
    """Its sidecar: the derivation's settings and the users' key slots - what the drive's has."""
    return sidecar.write_sidecar(str(volume), {"method": unlock_cfg.get("method", ""), "kdf": unlock_cfg.get("kdf"),
                                               "keyring": unlock_cfg.get("keyring"), "mount_point": ""}, users)


def password_from_code(volume: str | Path, secret: str) -> str | None:
    """The password a stick was encrypted with, from a code that opened the drive back then: the
    admin's (the derivation in its sidecar) or a user's (their key slot there)."""
    info = sidecar.read_sidecar(str(volume)) or {}
    candidates = []
    if info.get("kdf"):
        try:
            candidates.append(kdf.derive_password(secret, info["kdf"]))
        except kdf.KDFError:
            pass
    keyring = info.get("keyring") if isinstance(info.get("keyring"), dict) else {}
    slots = [keyring.get("admin"), *(u.get("slot") for u in info.get("users") or [])]
    for slot in slots:
        master = keyslots.open_slot(secret, slot) if slot else None
        if master is not None:
            password = keyslots.open_vault(master, keyring.get("vault"))
            if password:
                return password  # (a key slot that opened is the right one)
    return candidates[0] if candidates else None


def _mounted(path: Path) -> bool:
    return os.path.ismount(path)  # (tests: a stand-in VeraCrypt "mounts" by making a note)


def is_open(volume: str | Path) -> bool:
    return _mounted(mount_dir(volume))


def open_stick(stick, password: str, factory=None):
    """The stick's container opened - the stick as the games see it (mount: inside the container).
    Otherwise the stick with its problem (why it isn't open)."""
    volume = container_of(stick.mount)
    if volume is None:
        return stick
    inside = mount_dir(volume)
    opened = replace(stick, mount=inside, fstype="ext4", container=str(volume), host=stick.mount, problem="")
    if _mounted(inside):
        return opened
    try:
        inside.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return replace(stick, container=str(volume), host=stick.mount, problem=f"Couldn't be opened: {exc}")
    result = unlocker(volume, factory).unlock(password)
    if result.success:
        log.info("opened the encrypted %s", stick.device)
        return opened
    wrong = "wrong code" in result.message.lower()
    why = EARLIER if wrong else f"Couldn't be opened: {result.message}"
    return replace(stick, container=str(volume), host=stick.mount, problem=why)


def close(volume: str | Path, factory=None, force: bool = True) -> bool:
    """Closed by where it's open (VeraCrypt takes the mount folder too): also when its stick was taken
    out, or is mounted somewhere else now."""
    if not is_open(volume):
        return True
    inside = mount_dir(volume)
    result = unlocker(inside, factory, mount_point=inside).dismount(force=force)
    try:
        mount_dir(volume).rmdir()
    except OSError:
        pass
    return result.success


def create(stick, password: str, unlock_cfg: dict, users: list | None = None, progress=None, factory=None,
           cancel=None, free: int | None = None, share: float = 1.0):
    """The container on a stick that's just been formatted - filling it, or that share of it (the rest
    stays a normal drive, for anything else) - and its sidecar. The stick, opened, with the folders for
    games inside."""
    import shutil

    free = shutil.disk_usage(stick.mount).free if free is None else free
    share = min(1.0, max(0.05, float(share)))
    size_gb = int((free * share - (SPARE if share >= 1.0 else 0)) // 1024 ** 3)
    if size_gb < MIN_SIZE_GB:
        raise CryptError(f"{stick.name} is too small for an encrypted container (at least {MIN_SIZE_GB + 1} GB)")
    volume = Path(stick.mount) / CONTAINER
    result = unlocker(volume, factory).create_volume(str(volume), size_gb, password, quick=True, progress=progress,
                                                     cancel=cancel)
    if not result.success:
        raise CryptError(f"The encrypted container couldn't be made: {result.message}")
    if not write_info(volume, unlock_cfg, users):
        log.warning("couldn't write the sidecar of %s", volume)
    opened = open_stick(stick, password, factory)
    if getattr(opened, "problem", ""):
        raise CryptError(opened.problem)
    return opened


def rekey(volume: str | Path, old: str, new: str, unlock_cfg: dict, users: list | None = None,
          factory=None) -> bool:
    """Today's password for a stick that had another one (closed meanwhile, opened again after)."""
    was_open = is_open(volume)
    if was_open and not close(volume, factory, force=False):
        return False
    unlocker_ = unlocker(volume, factory)
    result = unlocker_.change_password(old, new)
    if result.success:
        write_info(volume, unlock_cfg, users)
    if was_open:
        unlocker(volume, factory).unlock(new if result.success else old)
    return result.success


class CryptError(Exception):
    """Not encrypted / opened - why, as a person says it."""


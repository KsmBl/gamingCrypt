"""``<container>.gamingcrypt.json`` next to a container file.

Holds everything needed to unlock the container except the secret itself:
unlock method, KDF parameters (salt) and mount point - and, once there are more
users, their names, methods and key slots (see keyslots.py). None of it is secret.
It lets GamingCrypt recognise an existing container on start (even with a lost
config.json) and keeps a copy of the KDF salt right next to the volume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from gamingcrypt.unlock.secrets import METHODS

SUFFIX = ".gamingcrypt.json"
VERSION = 1


def default_container_path() -> str:
    return str(Path.home() / "GamingCrypt.vc")


def sidecar_path(volume: str) -> Path:
    return Path(os.path.expanduser(volume) + SUFFIX)


USER_FIELDS = ("id", "name", "method", "age", "picked", "locked", "slot")  # (not their Steam settings: those aren't for a file anyone can read)


def write_sidecar(volume: str, unlock_cfg: dict, users: list | None = None, admin: dict | None = None) -> bool:
    """Only for container *files* (not devices). Returns False if it couldn't be written."""
    volume = os.path.expanduser(volume)
    if not volume or not os.path.isfile(volume):
        return False
    data = {
        "version": VERSION,
        "method": unlock_cfg.get("method", ""),
        "kdf": unlock_cfg.get("kdf"),
        "mount_point": unlock_cfg.get("mount_point", ""),
    }
    if unlock_cfg.get("keyring"):
        data["keyring"] = unlock_cfg["keyring"]
    if users:
        data["users"] = [{k: u[k] for k in USER_FIELDS if k in u} for u in users if isinstance(u, dict)]
    if admin:
        data["admin"] = admin
    target = sidecar_path(volume)
    tmp = target.with_name("." + target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
        try:
            os.chmod(tmp, 0o600)  # the owner's only (where the file system has that)
        except OSError:
            pass
        tmp.replace(target)
    except OSError:
        return False
    return True


def read_sidecar(volume: str) -> dict | None:
    try:
        data = json.loads(sidecar_path(volume).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("method") not in METHODS:
        return None
    kdf = data.get("kdf")
    if kdf is not None and not isinstance(kdf, dict):
        return None
    found = {"method": data["method"], "kdf": kdf, "mount_point": str(data.get("mount_point") or "")}
    if isinstance(data.get("keyring"), dict):
        found["keyring"] = data["keyring"]
    if isinstance(data.get("users"), list):
        found["users"] = [u for u in data["users"] if isinstance(u, dict) and u.get("id")]
    if isinstance(data.get("admin"), dict):
        found["admin"] = data["admin"]
    return found


def candidates(unlock_cfg: dict) -> list[str]:
    paths = []
    if unlock_cfg.get("volume"):
        paths.append(os.path.expanduser(unlock_cfg["volume"]))
    default = default_container_path()
    if default not in paths:
        paths.append(default)
    return paths


def find_container(unlock_cfg: dict) -> dict | None:
    """An existing container with a readable sidecar: ``{"volume", "method", "kdf", "mount_point"}``
    - and "keyring", "users", "admin" where there are more users."""
    for volume in candidates(unlock_cfg):
        if os.path.exists(volume):
            data = read_sidecar(volume)
            if data:
                return {"volume": volume, **data}
    return None


def existing_container(unlock_cfg: dict) -> str | None:
    """Path of a container that already exists (with or without sidecar)."""
    for volume in candidates(unlock_cfg):
        if os.path.exists(volume):
            return volume
    return None

"""``<container>.gamingcrypt.json`` next to a container file.

Holds everything needed to unlock the container except the secret itself:
unlock method, KDF parameters (salt) and mount point. None of it is secret.
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


def write_sidecar(volume: str, unlock_cfg: dict) -> bool:
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
    target = sidecar_path(volume)
    tmp = target.with_name("." + target.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2))
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
    return {"method": data["method"], "kdf": kdf, "mount_point": str(data.get("mount_point") or "")}


def candidates(unlock_cfg: dict) -> list[str]:
    paths = []
    if unlock_cfg.get("volume"):
        paths.append(os.path.expanduser(unlock_cfg["volume"]))
    default = default_container_path()
    if default not in paths:
        paths.append(default)
    return paths


def find_container(unlock_cfg: dict) -> dict | None:
    """An existing container with a readable sidecar: ``{"volume", "method", "kdf", "mount_point"}``."""
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

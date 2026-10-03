"""Register the encrypted drive as a Steam library folder automatically.

Steam keeps its library folders in ``config/libraryfolders.vdf`` (read at
start) and ``steamapps/libraryfolders.vdf``. A library additionally needs a
``steamapps`` folder and a ``libraryfolder.vdf`` marker inside it. Steam
rewrites these files when it exits, so it must not be running while we edit
them.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.steam import library, vdf

LABEL = "GamingCrypt"


@dataclass
class LibraryResult:
    status: str  # "already", "added", "no_steam", "not_mounted", "failed"
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("already", "added")


def steam_running(proc: Path = Path("/proc")) -> bool:
    for comm in proc.glob("[0-9]*/comm"):
        try:
            if comm.read_text().strip() in ("steam", "steamwebhelper"):
                return True
        except OSError:
            continue
    return False


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def close_steam(client, is_running: Callable[[], bool] = steam_running,
                sleep: Callable[[float], None] = time.sleep, timeout: float = 30.0) -> bool:
    """Ask Steam to exit and wait for it. True when Steam is not running (any more)."""
    if not is_running():
        return True
    if client is None or not client.shutdown():
        return False
    waited = 0.0
    while is_running():
        if waited >= timeout:
            return False
        sleep(0.5)
        waited += 0.5
    return True


def is_registered(root: Path, path: Path) -> bool:
    return any(_same(folder, path) for folder in library.library_folders(root))


def _vdf_files(root: Path) -> list[Path]:
    files = [root / "config" / "libraryfolders.vdf", root / "steamapps" / "libraryfolders.vdf"]
    existing = [f for f in files if f.is_file()]
    return existing or [root / "steamapps" / "libraryfolders.vdf"]


def _add_entry(file: Path, path: Path, contentid: str) -> None:
    try:
        data = vdf.load(file)
    except (OSError, vdf.VDFError):
        data = {}
    folders = vdf.iget(data, "libraryfolders")
    if not isinstance(folders, dict):
        folders = {}
        data = {"libraryfolders": folders}
    for value in folders.values():
        if isinstance(value, dict) and _same(Path(vdf.iget(value, "path", default="") or "/nonexistent"), path):
            return
    if not folders and file.parent.parent.joinpath("steamapps").is_dir():
        # A fresh file must still list Steam's own library as "0".
        folders["0"] = {"path": str(file.parent.parent), "label": "", "contentid": "0", "totalsize": "0",
                        "update_clean_bytes_tally": "0", "time_last_update_verified": "0", "apps": {}}
    index = max((int(k) for k in folders if k.isdigit()), default=-1) + 1
    folders[str(index)] = {
        "path": str(path),
        "label": LABEL,
        "contentid": contentid,
        "totalsize": "0",
        "update_clean_bytes_tally": "0",
        "time_last_update_verified": "0",
        "apps": {},
    }
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + ".gamingcrypt.tmp")
    tmp.write_text(vdf.dumps(data))
    tmp.replace(file)


def prepare_folder(path: Path, contentid: str) -> None:
    (path / "steamapps" / "common").mkdir(parents=True, exist_ok=True)
    marker = path / "libraryfolder.vdf"
    if not marker.exists():
        marker.write_text(vdf.dumps({"libraryfolder": {"contentid": contentid, "label": LABEL}}))


def register_library(root: Path, path: Path, rng: Callable[[], int] | None = None) -> None:
    contentid = str((rng or (lambda: random.getrandbits(63)))())
    prepare_folder(path, contentid)
    for file in _vdf_files(root):
        _add_entry(file, path, contentid)


def ensure_library(
    root: Path | None,
    path: str,
    client=None,
    is_running: Callable[[], bool] = steam_running,
    is_mounted: Callable[[str], bool] = os.path.ismount,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = 30.0,
) -> LibraryResult:
    """Make sure the mounted container at ``path`` is a Steam library (idempotent)."""
    if root is None:
        return LibraryResult("no_steam", "Steam not found - start Steam once, then unlock again")
    if not path or not is_mounted(path):
        # Never create steamapps on the unencrypted disk below the mount point.
        return LibraryResult("not_mounted")
    target = Path(path)
    if is_registered(root, target):
        if not (target / "steamapps").is_dir():
            prepare_folder(target, "0")
        return LibraryResult("already")
    if is_running() and not close_steam(client, is_running, sleep, timeout):
        return LibraryResult("failed", "Close Steam so GamingCrypt can add your encrypted drive as library")
    try:
        register_library(root, target)
    except OSError as exc:
        return LibraryResult("failed", f"Could not add the Steam library: {exc}")
    return LibraryResult("added", f"Your encrypted drive ({path}) is now a Steam library")

"""Install games without Steam's install dialog.

Steam downloads any owned app whose ``appmanifest_<id>.acf`` says
"update required + update started" (StateFlags 1026) when it starts. So we
write that manifest into the wanted library (the encrypted drive), restart
Steam minimised (``-silent``) and watch the manifest for progress.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.steam import library, library_setup, vdf

STATE_UPDATE_REQUIRED = 2
STATE_FULLY_INSTALLED = 4
STATE_UPDATE_STARTED = 1024
QUEUED_FLAGS = STATE_UPDATE_REQUIRED | STATE_UPDATE_STARTED  # 1026


@dataclass
class InstallResult:
    ok: bool
    message: str = ""


@dataclass
class InstallProgress:
    state: str  # "missing", "queued", "downloading", "installed"
    downloaded: int = 0
    total: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.downloaded / self.total if self.total else 0.0


def install_dir_name(name: str, appid: int) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().rstrip(".")
    return cleaned or f"app_{appid}"


def manifest_path(library_path: Path, appid: int) -> Path:
    return Path(library_path) / "steamapps" / f"appmanifest_{int(appid)}.acf"


def write_manifest(library_path: Path, appid: int, name: str, owner: str = "") -> Path:
    """Write a "please download me" manifest. Never overwrites an existing one."""
    path = manifest_path(library_path, appid)
    if path.exists():
        return path
    state = {
        "appid": str(int(appid)),
        "Universe": "1",
        "name": name,
        "StateFlags": str(QUEUED_FLAGS),
        "installdir": install_dir_name(name, appid),
        "LastUpdated": "0",
        "SizeOnDisk": "0",
        "buildid": "0",
        "BytesToDownload": "0",
        "BytesDownloaded": "0",
        "AutoUpdateBehavior": "0",
        "AllowOtherDownloadsWhileRunning": "0",
        "ScheduledAutoUpdate": "0",
        "UserConfig": {},
        "MountedConfig": {},
    }
    if owner:
        state["LastOwner"] = owner
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(vdf.dumps({"AppState": state}))
    tmp.replace(path)
    return path


def find_manifest(root: Path, appid: int) -> Path | None:
    for folder in library.library_folders(root):
        path = manifest_path(folder, appid)
        if path.is_file():
            return path
    return None


def progress(root: Path | None, appid: int) -> InstallProgress:
    path = find_manifest(root, appid) if root is not None else None
    if path is None:
        return InstallProgress("missing")
    try:
        state = vdf.iget(vdf.load(path), "AppState") or {}
    except (OSError, vdf.VDFError):
        return InstallProgress("queued")

    def num(key: str) -> int:
        try:
            return int(vdf.iget(state, key, default=0) or 0)
        except ValueError:
            return 0

    flags = num("StateFlags")
    done, total = num("BytesDownloaded"), num("BytesToDownload")
    if flags == STATE_FULLY_INSTALLED:
        return InstallProgress("installed", done or total, total)
    if total > 0:
        return InstallProgress("downloading", done, total)
    return InstallProgress("queued", done, total)


def install(
    root: Path | None,
    library_path: Path,
    appid: int,
    name: str,
    client,
    owner: str = "",
    is_running: Callable[[], bool] = library_setup.steam_running,
    sleep: Callable[[float], None] = time.sleep,
) -> InstallResult:
    if root is None:
        return InstallResult(False, "Steam wasn't found on this device")
    existing = find_manifest(root, appid)
    if existing is None:
        if not (Path(library_path) / "steamapps").is_dir():
            return InstallResult(False, f"Library {library_path} is not available - is the drive unlocked?")
        try:
            write_manifest(library_path, appid, name, owner)
        except OSError as exc:
            return InstallResult(False, f"Could not queue the download: {exc}")
    # Steam only picks up new manifests on start -> restart it, minimised.
    if not library_setup.close_steam(client, is_running, sleep):
        return InstallResult(False, "Steam didn't close - close it and try again")
    if not client.start_silent():
        return InstallResult(False, "Could not start Steam")
    return InstallResult(True, "Download started in the background")

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

# Steam's EAppState bits (appmanifest "StateFlags")
STATE_UPDATE_REQUIRED = 2
STATE_FULLY_INSTALLED = 4
STATE_UPDATE_RUNNING = 256
STATE_UPDATE_PAUSED = 512
STATE_UPDATE_STARTED = 1024
STATE_VALIDATING = 1 << 17
STATE_PREALLOCATING = 1 << 19
STATE_DOWNLOADING = 1 << 20
STATE_STAGING = 1 << 21
STATE_COMMITTING = 1 << 22
ACTIVE = (STATE_UPDATE_RUNNING | STATE_VALIDATING | STATE_PREALLOCATING | STATE_DOWNLOADING
          | STATE_STAGING | STATE_COMMITTING)
QUEUED_FLAGS = STATE_UPDATE_REQUIRED | STATE_UPDATE_STARTED  # 1026


@dataclass
class InstallResult:
    ok: bool
    message: str = ""


def classify(flags: int, downloaded: int = 0, total: int = 0) -> str:
    """"installed", "downloading", "paused", "queued" or "other"."""
    if flags & STATE_UPDATE_PAUSED:
        return "paused"
    if flags & ACTIVE or (flags & STATE_UPDATE_REQUIRED and 0 < downloaded < total):
        return "downloading"
    if flags & STATE_UPDATE_REQUIRED or (flags & STATE_UPDATE_STARTED and total > 0):
        return "queued" if total == 0 or downloaded == 0 else "downloading"
    if flags & STATE_FULLY_INSTALLED:
        return "installed"
    return "other"


@dataclass
class Download:
    appid: int
    name: str
    state: str  # "downloading", "paused" or "queued"
    downloaded: int
    total: int
    is_update: bool
    library: str = ""

    @property
    def percent(self) -> float:
        return 100.0 * self.downloaded / self.total if self.total else 0.0


def _manifest_numbers(path: Path) -> tuple[dict, int, int, int] | None:
    try:
        state = vdf.iget(vdf.load(path), "AppState") or {}
    except (OSError, vdf.VDFError):
        return None

    def num(key: str) -> int:
        try:
            return int(vdf.iget(state, key, default=0) or 0)
        except ValueError:
            return 0

    done, total = num("BytesDownloaded"), num("BytesToDownload")
    staged, to_stage = num("BytesStaged"), num("BytesToStage")
    # Steam sometimes advances only its staging counters - use whichever is further,
    # expressed in download bytes so the two never mix.
    if to_stage > 0:
        if total > 0:
            done = max(done, int(total * min(staged, to_stage) / to_stage))
        else:
            done, total = staged, to_stage
    return state, num("StateFlags"), done, total


def downloads(root: Path | None) -> list[Download]:
    """Everything Steam has queued, is downloading or paused, in all library folders."""
    if root is None:
        return []
    found: dict[int, Download] = {}
    for folder in library.library_folders(root):
        for path in sorted((folder / "steamapps").glob("appmanifest_*.acf")):
            parsed = _manifest_numbers(path)
            if parsed is None:
                continue
            state, flags, done, total = parsed
            try:
                appid = int(vdf.iget(state, "appid", default=0) or 0)
            except ValueError:
                continue
            name = vdf.iget(state, "name", default="") or f"App {appid}"
            if not appid or not library.is_game(appid, name):
                continue
            kind = classify(flags, done, total)
            if kind in ("downloading", "paused", "queued"):
                # SizeOnDisk already grows during a *first* download - only Steam's
                # "fully installed" bit means there's an installed version to keep.
                is_update = bool(flags & STATE_FULLY_INSTALLED)
                found.setdefault(appid, Download(appid, name, kind, done, total, is_update, str(folder)))
    order = {"downloading": 0, "paused": 1, "queued": 2}
    return sorted(found.values(), key=lambda d: (order[d.state], d.name.casefold()))


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
    parsed = _manifest_numbers(path)
    if parsed is None:
        return InstallProgress("queued")
    _state, flags, done, total = parsed
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


def _remove(path: Path, remove_tree: Callable[[Path], None]) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        remove_tree(path)


def uninstall(
    root: Path | None,
    appid: int,
    client,
    is_running: Callable[[], bool] = library_setup.steam_running,
    sleep: Callable[[float], None] = time.sleep,
    remove_tree: Callable[[Path], None] | None = None,
) -> InstallResult:
    """Uninstall without Steam's confirmation dialog.

    Deletes the game files, manifest, workshop items, shader cache and partial
    downloads. The Proton prefix (``compatdata/<appid>``) is kept on purpose:
    many Windows games keep their save games there.
    """
    import shutil

    remove_tree = remove_tree or shutil.rmtree
    manifest = find_manifest(root, appid) if root is not None else None
    if manifest is None:
        return InstallResult(False, "The game is not installed")
    parsed = _manifest_numbers(manifest)
    state = parsed[0] if parsed else {}
    name = vdf.iget(state, "name", default="") or f"App {appid}"
    installdir = str(vdf.iget(state, "installdir", default="") or "")
    steamapps = manifest.parent
    common = steamapps / "common"
    target = common / installdir
    # Never delete anything outside <library>/steamapps/common/<one folder>.
    if (not installdir or installdir in (".", "..") or "/" in installdir or "\\" in installdir
            or target.parent.resolve() != common.resolve()):
        return InstallResult(False, f"Refusing to delete {target} - unexpected install folder")
    was_running = is_running()
    if was_running and not library_setup.close_steam(client, is_running, sleep):
        return InstallResult(False, "Steam didn't close - close it and try again")
    try:
        _remove(target, remove_tree)
        for extra in (steamapps / "workshop" / "content" / str(appid),
                      steamapps / "workshop" / f"appworkshop_{appid}.acf",
                      steamapps / "shadercache" / str(appid),
                      steamapps / "downloading" / str(appid)):
            _remove(extra, remove_tree)
        manifest.unlink()
    except OSError as exc:
        return InstallResult(False, f"Could not delete everything: {exc}")
    finally:
        if was_running:
            client.start_silent()
    return InstallResult(True, f"{name} was uninstalled")

"""Reading the local Steam installation: library folders, installed games, playtime."""

from __future__ import annotations

import re
from pathlib import Path

from gamingcrypt.steam import vdf
from gamingcrypt.steam.models import SteamGame

# Tools that Steam lists as apps but which are not games.
EXCLUDED_APPIDS = {
    228980,   # Steamworks Common Redistributables
    1070560,  # Steam Linux Runtime 1.0 (scout)
    1391110,  # Steam Linux Runtime 2.0 (soldier)
    1628350,  # Steam Linux Runtime 3.0 (sniper)
    1493710,  # Proton Experimental
    2180100,  # Proton Hotfix
    1826330,  # Proton EasyAntiCheat Runtime
    1161040,  # Proton BattlEye Runtime
}
EXCLUDED_NAME = re.compile(r"^(Proton\b|Steam Linux Runtime|Steamworks Common)", re.I)

# StateFlags bit 4 = fully installed; anything else means an update/download is pending.
STATE_FULLY_INSTALLED = 4


def default_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        home / "snap" / "steam" / "common" / ".local" / "share" / "Steam",
        home / ".steam" / "root",
    ]


def find_steam_root(configured: str = "", home: Path | None = None) -> Path | None:
    candidates = [Path(configured).expanduser()] if configured else default_roots(home)
    for candidate in candidates:
        if (candidate / "steamapps").is_dir():
            return candidate.resolve()
    return None


def library_folders(root: Path) -> list[Path]:
    """All Steam library folders (the root itself + extra drives, e.g. the VeraCrypt one)."""
    folders = [root]
    try:
        data = vdf.load(root / "steamapps" / "libraryfolders.vdf")
    except (OSError, vdf.VDFError):
        return folders
    entries = vdf.iget(data, "libraryfolders", default={}) or {}
    for value in entries.values():
        path = vdf.iget(value, "path") if isinstance(value, dict) else value
        if isinstance(path, str) and path:
            p = Path(path)
            if p not in folders and p.resolve() not in [f.resolve() for f in folders]:
                folders.append(p)
    return folders


def is_game(appid: int, name: str) -> bool:
    return appid not in EXCLUDED_APPIDS and not EXCLUDED_NAME.match(name or "")


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_manifest(path: Path, library: Path) -> SteamGame | None:
    try:
        state = vdf.iget(vdf.load(path), "AppState")
    except (OSError, vdf.VDFError):
        return None
    if not isinstance(state, dict):
        return None
    appid = _int(vdf.iget(state, "appid"))
    name = vdf.iget(state, "name", default="") or ""
    if not appid or not is_game(appid, name):
        return None
    flags = _int(vdf.iget(state, "StateFlags"), STATE_FULLY_INSTALLED)
    # A manifest alone doesn't mean installed: queued / paused / cancelled downloads have
    # one too. Only Steam's "fully installed" bit counts (an update may be pending on top).
    installed = bool(flags & STATE_FULLY_INSTALLED)
    return SteamGame(
        appid=appid,
        name=name,
        installed=installed,
        install_dir=str(library / "steamapps" / "common" / (vdf.iget(state, "installdir", default="") or "")),
        library_path=str(library),
        size_on_disk=_int(vdf.iget(state, "SizeOnDisk")),
        last_updated=_int(vdf.iget(state, "LastUpdated")) or None,
        update_pending=installed and flags != STATE_FULLY_INSTALLED,
    )


def installed_games(root: Path, include_pending: bool = False) -> list[SteamGame]:
    """Games with a manifest; only fully installed ones unless ``include_pending``."""
    games: dict[int, SteamGame] = {}
    for folder in library_folders(root):
        steamapps = folder / "steamapps"
        if not steamapps.is_dir():
            continue  # e.g. the encrypted drive isn't mounted
        for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
            game = read_manifest(manifest, folder)
            if game is not None and (game.installed or include_pending):
                games.setdefault(game.appid, game)
    return list(games.values())


def local_playtime(root: Path, account_id: int | None = None) -> dict[int, dict[str, int]]:
    """Playtime (minutes) and last-played timestamps per appid from localconfig.vdf.

    ``account_id`` limits it to one Steam account (``userdata/<account_id>``).
    """
    result: dict[int, dict[str, int]] = {}
    pattern = f"{account_id}/config/localconfig.vdf" if account_id is not None else "*/config/localconfig.vdf"
    for cfg in sorted((root / "userdata").glob(pattern)):
        try:
            data = vdf.load(cfg)
        except (OSError, vdf.VDFError):
            continue
        apps = vdf.iget(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps", default={}) or {}
        for key, values in apps.items():
            appid = _int(key)
            if not appid or not isinstance(values, dict):
                continue
            entry = result.setdefault(appid, {"playtime": 0, "last_played": 0})
            entry["playtime"] = max(entry["playtime"], _int(vdf.iget(values, "Playtime")))
            entry["last_played"] = max(entry["last_played"], _int(vdf.iget(values, "LastPlayed")))
    return result


def logged_in_user(root: Path) -> dict | None:
    """The Steam account last used on this machine: ``{"steam_id", "name"}`` (from loginusers.vdf)."""
    try:
        users = vdf.iget(vdf.load(root / "config" / "loginusers.vdf"), "users", default={}) or {}
    except (OSError, vdf.VDFError):
        return None
    best, best_key = None, None
    for steam_id, info in users.items():
        if not steam_id.isdigit() or not isinstance(info, dict):
            continue
        key = (vdf.iget(info, "MostRecent") == "1", _int(vdf.iget(info, "Timestamp")))
        if best_key is None or key > best_key:
            best_key = key
            best = {"steam_id": steam_id,
                    "name": vdf.iget(info, "PersonaName") or vdf.iget(info, "AccountName") or steam_id}
    return best

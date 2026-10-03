"""Per-game Proton (compatibility tool) selection.

Steam keeps the choice in ``config/config.vdf`` under
InstallConfigStore/Software/Valve/Steam/CompatToolMapping/<appid> ("0" is the
global default). Official Proton builds are addressed by an internal name
(``proton_experimental``, ``proton_9``, ``proton_63`` …), custom ones (e.g.
GE-Proton) by the key in their ``compatibilitytool.vdf``. Steam rewrites
config.vdf when it exits, so it must be closed while we change it.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.steam import library, library_setup, vdf

MAPPING_PATH = ("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping")


@dataclass(frozen=True)
class CompatTool:
    name: str  # what Steam stores
    display: str


def official_name(folder: str) -> str | None:
    """Folder name of an official Proton install -> Steam's internal tool name."""
    low = folder.lower()
    if "experimental" in low:
        return "proton_experimental"
    if "hotfix" in low:
        return "proton_hotfix"
    match = re.fullmatch(r"proton (\d+)\.(\d+)(?: \(beta\))?", low)
    if not match:
        return None
    major, minor = match.groups()
    return f"proton_{major}{'' if minor == '0' else minor}"


def _version_key(tool: CompatTool) -> tuple:
    numbers = [int(n) for n in re.findall(r"\d+", tool.display)]
    special = 0 if "experimental" in tool.name else 1 if "hotfix" in tool.name else 2
    return (special, [-n for n in numbers], tool.display.casefold())


def official_tools(root: Path) -> list[CompatTool]:
    tools = {}
    for folder in library.library_folders(root):
        common = folder / "steamapps" / "common"
        if not common.is_dir():
            continue
        for path in common.iterdir():
            name = official_name(path.name) if (path / "proton").exists() else None
            if name:
                tools.setdefault(name, CompatTool(name, path.name))
    return sorted(tools.values(), key=_version_key)


def custom_dirs(root: Path, home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    return [root / "compatibilitytools.d", home / ".steam" / "root" / "compatibilitytools.d",
            Path("/usr/share/steam/compatibilitytools.d")]


def custom_tools(root: Path, home: Path | None = None) -> list[CompatTool]:
    tools = {}
    for base in custom_dirs(root, home):
        for manifest in sorted(base.glob("*/compatibilitytool.vdf")) if base.is_dir() else []:
            try:
                entries = vdf.iget(vdf.load(manifest), "compatibilitytools", "compat_tools", default={}) or {}
            except (OSError, vdf.VDFError):
                continue
            for name, info in entries.items():
                display = vdf.iget(info, "display_name", default=name) if isinstance(info, dict) else name
                tools.setdefault(name, CompatTool(name, display or name))
    return sorted(tools.values(), key=_version_key)


def available(root: Path | None, home: Path | None = None) -> list[CompatTool]:
    if root is None:
        return []
    return official_tools(root) + custom_tools(root, home)


def _config(root: Path) -> Path:
    return root / "config" / "config.vdf"


def current(root: Path | None, appid: int) -> str | None:
    if root is None:
        return None
    try:
        data = vdf.load(_config(root))
    except (OSError, vdf.VDFError):
        return None
    entry = vdf.iget(data, *MAPPING_PATH, str(appid))
    name = vdf.iget(entry, "name") if isinstance(entry, dict) else None
    return name or None


def _child(mapping: dict, key: str) -> dict:
    for existing, value in mapping.items():
        if existing.lower() == key.lower() and isinstance(value, dict):
            return value
    mapping[key] = {}
    return mapping[key]


def write_choice(root: Path, appid: int, name: str | None) -> None:
    path = _config(root)
    try:
        data = vdf.load(path)
    except (OSError, vdf.VDFError):
        data = {}
    mapping = data
    for key in MAPPING_PATH:
        mapping = _child(mapping, key)
    if name is None:
        mapping.pop(str(appid), None)  # back to Steam's default
    else:
        mapping[str(appid)] = {"name": name, "config": "", "priority": "250"}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".gamingcrypt.tmp")
    tmp.write_text(vdf.dumps(data))
    tmp.replace(path)


def set_tool(root: Path | None, appid: int, name: str | None, client,
             is_running: Callable[[], bool] = library_setup.steam_running,
             sleep: Callable[[float], None] = time.sleep) -> tuple[bool, str]:
    if root is None:
        return False, "Steam wasn't found on this device"
    was_running = is_running()
    if was_running and not library_setup.close_steam(client, is_running, sleep):
        return False, "Steam didn't close - close it and try again"
    try:
        write_choice(root, appid, name)
    except OSError as exc:
        return False, f"Could not change the setting: {exc}"
    finally:
        if was_running:
            client.start_silent()
    return True, f"Compatibility tool: {name or 'Steam default'}"

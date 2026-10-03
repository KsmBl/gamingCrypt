"""Loading and saving of the user configuration (JSON, XDG paths)."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "fullscreen": True,
    "unlock": {
        # Which unlock methods are offered on the lock screen.
        "methods": ["pin", "password", "pattern"],
        # Path to the VeraCrypt volume (file container or device, e.g. /dev/sda2).
        "volume": "",
        # Where the volume gets mounted. Empty = let VeraCrypt choose.
        "mount_point": "",
        # Run veracrypt through `sudo -n` (see install.sh for the sudoers rule).
        "use_sudo": True,
        "veracrypt_binary": "veracrypt",
        "pim": 0,
        "keyfiles": [],
    },
    "steam": {
        # Steam installation root. Empty = auto-detect.
        "root": "",
        # Optional: Steam Web API key + SteamID64 to show the full library.
        "api_key": "",
        "steam_id": "",
        "country": "de",
        "language": "english",
        # Command used to talk to the Steam client. Empty = auto-detect.
        "command": "",
    },
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gamingcrypt"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "gamingcrypt"


def config_path() -> Path:
    return config_dir() / "config.json"


def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load the config, falling back to defaults for missing keys or a broken file."""
    path = path or config_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return _merge(DEFAULTS, data)


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))

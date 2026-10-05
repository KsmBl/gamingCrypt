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
        # Unlock method chosen in the first-start setup: "pin", "password",
        # "pattern" (3x3 swipe) or "grid5" (5x5 tap). Empty = setup not done yet.
        "method": "",
        # Path to the VeraCrypt volume (file container or device, e.g. /dev/sda2).
        "volume": "",
        # Where the volume gets mounted. Empty = let VeraCrypt choose.
        "mount_point": "",
        # Run veracrypt through `sudo -n` (see install.sh for the sudoers rule).
        "use_sudo": True,
        "veracrypt_binary": "veracrypt",
        # Restricted root helper installed by install.sh; used with sudo if present.
        "sudo_helper": "/usr/local/lib/gamingcrypt/veracrypt-helper",
        "pim": 0,
        "keyfiles": [],
        # scrypt parameters + salt applied to every secret (set by the setup).
        # BACK THIS UP: without the salt the volume can't be unlocked.
        "kdf": None,
    },
    "system": {
        # Re-applied at start because they reset on reboot. None = leave as is.
        "display": None,  # {"output", "width", "height", "refresh"}
        "power_limit_w": None,
        # Volume per press of the + / - buttons (gaming mode), -10..10.
        # Negative swaps the buttons, 0 turns them off.
        "volume_step": 5,
        # Gaming mode: ask for the unlock code again after sleeping this many
        # minutes (0 = always, None = never).
        "lock_after_sleep_min": None,
        # Gaming mode, short press of the power button: "menu" (the power menu) or
        # "sleep". Sleep doesn't wake up again on every device, so it's opt-in.
        "power_button": "menu",
        # Set when the device didn't wake up from sleep: sleep is offered no more.
        "sleep_broken": False,
        # Second operating system for "Restart into …" (asked by install.sh): a UEFI
        # boot entry like "0000", "none", or None = every system found.
        "other_os": None,
    },
    "input": {
        # Apply calibration + button mapping through a virtual controller.
        "enabled": False,
        "profiles": {},  # per controller model: mapping + calibration
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
        # Register the mounted container as Steam library folder after unlocking.
        "auto_library": True,
        # Download owned games in the background (no Steam install dialog).
        "silent_install": True,
        # Uninstall without Steam's confirmation dialog (GamingCrypt asks itself).
        "silent_uninstall": True,
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

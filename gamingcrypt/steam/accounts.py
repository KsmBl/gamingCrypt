"""Several Steam accounts on one device.

Steam lists every account that logged in on this machine in
``config/loginusers.vdf``. Switching works like the usual Linux account
switchers: close Steam, set ``AutoLoginUser`` in ``registry.vdf``, mark the
account as most recent and start Steam again (minimised). This only logs in
without a password prompt if "Remember password" was ticked for that account.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.steam import library_setup, vdf

STEAMID64_BASE = 76561197960265728


@dataclass
class Account:
    steam_id: str
    account_name: str
    persona: str
    most_recent: bool
    remembers_password: bool

    @property
    def account_id(self) -> int:
        """The 32-bit id used for ``userdata/<id>``."""
        return int(self.steam_id) - STEAMID64_BASE


def _loginusers(root: Path) -> Path:
    return root / "config" / "loginusers.vdf"


def list_accounts(root: Path | None) -> list[Account]:
    if root is None:
        return []
    try:
        users = vdf.iget(vdf.load(_loginusers(root)), "users", default={}) or {}
    except (OSError, vdf.VDFError):
        return []
    accounts = []
    for steam_id, info in users.items():
        if not steam_id.isdigit() or not isinstance(info, dict):
            continue
        name = vdf.iget(info, "AccountName") or ""
        accounts.append(Account(
            steam_id=steam_id,
            account_name=name,
            persona=vdf.iget(info, "PersonaName") or name or steam_id,
            most_recent=vdf.iget(info, "MostRecent") == "1",
            remembers_password=vdf.iget(info, "RememberPassword") == "1",
        ))
    return sorted(accounts, key=lambda a: (not a.most_recent, a.persona.casefold()))


def registry_path(root: Path, home: Path | None = None) -> Path:
    """Steam's registry.vdf: ~/.steam/registry.vdf (native) or inside the Flatpak sandbox."""
    home = home or Path.home()
    candidates = []
    for parent in root.parents:
        if parent.name == "com.valvesoftware.Steam":
            candidates.append(parent / ".steam" / "registry.vdf")
    candidates.append(home / ".steam" / "registry.vdf")
    return next((c for c in candidates if c.exists()), candidates[0])


def _set(mapping: dict, key: str, value) -> None:
    """Set ``key`` keeping Steam's existing spelling (it isn't consistent about case)."""
    for existing in mapping:
        if existing.lower() == key.lower():
            mapping[existing] = value
            return
    mapping[key] = value


def _child(mapping: dict, key: str) -> dict:
    for existing, value in mapping.items():
        if existing.lower() == key.lower() and isinstance(value, dict):
            return value
    mapping[key] = {}
    return mapping[key]


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".gamingcrypt.tmp")
    tmp.write_text(vdf.dumps(data))
    tmp.replace(path)


def set_auto_login(root: Path, account: Account, home: Path | None = None) -> None:
    reg_path = registry_path(root, home)
    try:
        registry = vdf.load(reg_path)
    except (OSError, vdf.VDFError):
        registry = {}
    steam = _child(_child(_child(_child(_child(registry, "Registry"), "HKCU"), "Software"), "Valve"), "Steam")
    _set(steam, "AutoLoginUser", account.account_name)
    _set(steam, "RememberPassword", "1")
    _write(reg_path, registry)

    data = vdf.load(_loginusers(root))
    users = _child(data, "users")
    for steam_id, info in users.items():
        if isinstance(info, dict):
            chosen = steam_id == account.steam_id
            _set(info, "MostRecent", "1" if chosen else "0")
            if chosen:
                _set(info, "AllowAutoLogin", "1")
    _write(_loginusers(root), data)


def switch_account(
    root: Path | None,
    account: Account,
    client,
    home: Path | None = None,
    is_running: Callable[[], bool] = library_setup.steam_running,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    if root is None:
        return False, "Steam wasn't found on this device"
    if not account.account_name:
        return False, "Steam doesn't know the login name of this account"
    # Steam rewrites both files when it exits -> it must be closed first.
    if not library_setup.close_steam(client, is_running, sleep):
        return False, "Steam didn't close - close it and try again"
    try:
        set_auto_login(root, account, home)
    except (OSError, vdf.VDFError) as exc:
        return False, f"Could not switch: {exc}"
    if not client.start_silent():
        return False, "Switched, but Steam could not be started"
    if not account.remembers_password:
        return True, f"Switched to {account.persona} - Steam will ask for the password once"
    return True, f"Switched to {account.persona}"

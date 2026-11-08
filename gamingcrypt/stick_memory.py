"""Which games are on which USB stick, USB drive or SD card - remembered, so a stick that isn't in
keeps its games in the list, greyed out ("Put GAMES in to play"), in Favorites and Continue playing.

Kept on the encrypted drive (<drive>/.gamingcrypt/sticks.json), never outside it: which games
someone has is GamingCrypt's content, like the games themselves. A stick is known by its file
system's id (or its container's), not its name. Whether the games of a stick that isn't in are
shown is each user's own setting (config "sticks", users.OWN).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

FOLDER = ".gamingcrypt"
NAME = "sticks.json"
KINDS = ("roms", "windows", "linux")
REQUIRE_MOUNT = True  # (tests: a folder stands in for the encrypted drive)
_lock = threading.Lock()  # (the three libraries are looked at in three threads at once)


def stick_key(drive) -> str:
    """Which stick: its file system's id - its container's when it has one but no id - its name last."""
    if getattr(drive, "uuid", ""):
        return f"fs:{drive.uuid}"
    if getattr(drive, "container", ""):
        from gamingcrypt.system import stick_crypt

        return f"vc:{stick_crypt.container_id(drive.container)}"
    return f"name:{drive.name}"


class StickMemory:
    def __init__(self, drive_root: Path | str):
        self.path = Path(drive_root) / FOLDER / NAME

    @property
    def usable(self) -> bool:
        """The encrypted drive is mounted (unlocked) - locked, its folder is an empty one on the device
        itself, and nothing is written there."""
        root = self.path.parent.parent
        return os.path.ismount(root) if REQUIRE_MOUNT else root.is_dir()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{NAME}.tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)

    def update(self, kind: str, drives: list, games: list) -> None:
        """The games of one kind ("roms", "windows", "linux") that are on the sticks that are in now -
        what was on them before and isn't any more is forgotten."""
        if not self.usable:
            return
        with _lock:
            data = self.load()
            changed = False
            for drive in drives:
                key = stick_key(drive)
                entry = data.setdefault(key, {})
                listed = sorted((record(g) for g in games if getattr(g, "stick", "") == key),
                                key=lambda r: r.get("name", "").casefold())
                fresh = {"name": drive.name, "kind": drive.kind, "seen": entry.get("seen", 0)}
                if entry.get(kind) != listed or any(entry.get(k) != v for k, v in fresh.items() if k != "seen"):
                    entry.update(fresh, **{kind: listed})
                    changed = True
                if time.time() - float(entry.get("seen", 0)) > 3600:
                    entry["seen"] = int(time.time())
                    changed = True
            if changed:
                self._save(data)

    def forget(self, key: str) -> None:
        with _lock:
            data = self.load()
            if data.pop(key, None) is not None:
                self._save(data)

    def away(self, present: set[str]) -> dict:
        """The remembered sticks that aren't in: key -> {"name", "kind", "roms", "windows", "linux"}."""
        return {k: v for k, v in self.load().items() if k not in present and isinstance(v, dict)}


def record(game) -> dict:
    from gamingcrypt.emulation.library import RomGame

    if isinstance(game, RomGame):
        return {"name": game.name, "system": game.system.id, "path": str(game.path), "size": game.size,
                "discs": [str(d) for d in game.discs]}
    return {"name": game.name, "path": str(game.path), "size": game.size}


def ghosts(memory: StickMemory | None, kind: str, present: set[str], home: Path | None = None) -> list:
    """The games of the sticks that aren't in, as games of that kind - away: the stick's name."""
    if memory is None:
        return []
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.emulation.systems import BY_ID
    from gamingcrypt.linux.library import LinuxGame
    from gamingcrypt.wine.library import WindowsGame

    found = []
    for key, entry in memory.away(present).items():
        for item in entry.get(kind) or []:
            try:
                if kind == "roms":
                    system = BY_ID.get(item["system"])
                    if system is None:
                        continue
                    game = RomGame(system, Path(item["path"]), item["name"], int(item.get("size", 0)),
                                   discs=tuple(Path(d) for d in item.get("discs") or ()),
                                   removable=entry.get("kind", "usb"), stick=key, away=entry.get("name", "?"))
                else:
                    cls = LinuxGame if kind == "linux" else WindowsGame
                    game = cls(Path(item["path"]), item["name"], int(item.get("size", 0)),
                               removable=entry.get("kind", "usb"), home=home, stick=key,
                               away=entry.get("name", "?"))
            except (KeyError, TypeError, ValueError):
                continue
            found.append(game)
    return found

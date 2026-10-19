"""Minecraft instances in <drive>/Minecraft/Instances: a folder each, with its own worlds, settings,
resource packs (and later mods) - and instance.json: which Minecraft it runs.

What every instance shares - the game's versions, libraries, sounds and Java - is downloaded once
into <drive>/Minecraft/Shared (see minecraft/portable). An instance is a game like a Linux one
(play time, Continue, Favorites, search): it's a WindowsGame without Proton / Wine.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from gamingcrypt.wine.library import WindowsGame

MINECRAFT_APPID_BASE = 0x30000000  # below the Linux games' ids, far above Steam's
INSTANCES = "Instances"
SHARED = "Shared"
ACCOUNTS = ".accounts"
SETTINGS = "instance.json"
LATEST = "release"  # portablemc: the newest release, whatever it is when the instance is started
# Minecraft is fullscreen in gaming mode (gamescope shows one window anyway); the GUI scaled to the screen
OPTIONS = "fullscreen:true\nguiScale:0\n"


@dataclass
class MinecraftInstance(WindowsGame):
    version: str = LATEST
    installed: str = ""  # the version last installed for it ("" - not yet)

    KIND = "minecraft"
    LABEL = "Minecraft"
    APPID_BASE = MINECRAFT_APPID_BASE
    AGE = 6  # USK 6 (ratings.py)
    GENRES = ("Adventure", "Simulation")  # (game_facts: the filters)
    YEAR = 2011

    def describe_version(self) -> str:
        return "the newest release" if self.version == LATEST else self.version


def is_minecraft_appid(appid: int | None) -> bool:
    return appid is not None and MINECRAFT_APPID_BASE <= appid < MINECRAFT_APPID_BASE + 0x10000000


def _read(folder: Path) -> MinecraftInstance | None:
    try:
        data = json.loads((folder / SETTINGS).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return MinecraftInstance(folder, str(data.get("name") or folder.name), version=str(data.get("version") or LATEST),
                             installed=str(data.get("installed") or ""))


def scan(root: Path) -> list[MinecraftInstance]:
    """Every instance, by name."""
    try:
        folders = [f for f in (root / INSTANCES).iterdir() if f.is_dir() and not f.name.startswith(".")]
    except OSError:
        return []
    found = [i for i in (_read(f) for f in folders) if i is not None]
    return sorted(found, key=lambda i: (i.name.casefold(), i.path.name.casefold()))


def save(instance: MinecraftInstance) -> None:
    (instance.path / SETTINGS).write_text(json.dumps(
        {"name": instance.name, "version": instance.version, "installed": instance.installed}, indent=1))


def folder_name(name: str) -> str:
    cleaned = re.sub(r"[^\w .-]+", "", name, flags=re.UNICODE).strip(" .")
    return cleaned or "Minecraft"


def create(root: Path, name: str, version: str = LATEST) -> MinecraftInstance:
    """A new instance (a folder of its own also when the name is taken)."""
    instances = root / INSTANCES
    instances.mkdir(parents=True, exist_ok=True)
    base = folder_name(name)
    folder, number = instances / base, 2
    while folder.exists():
        folder, number = instances / f"{base} {number}", number + 1
    folder.mkdir()
    (folder / "options.txt").write_text(OPTIONS)
    instance = MinecraftInstance(folder, name.strip() or base, version=version)
    save(instance)
    return instance


def remove(instance: MinecraftInstance) -> None:
    """Its folder - worlds included."""
    shutil.rmtree(instance.path)

"""What takes space in the Steam libraries, and freeing it.

Safe to delete: shader caches (Steam rebuilds them when a game starts) and data of
downloads that are no longer queued (cancelled). Never touched: compatdata - the
Proton prefixes hold save games.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.steam import installer, library


def tree_size(path: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


@dataclass
class GameSpace:
    appid: int
    name: str
    game_bytes: int
    shader_bytes: int
    library: Path


@dataclass
class LibrarySpace:
    path: Path
    free: int
    total: int


@dataclass
class Report:
    libraries: list[LibrarySpace] = field(default_factory=list)
    games: list[GameSpace] = field(default_factory=list)
    leftovers: list[Path] = field(default_factory=list)
    leftover_bytes: int = 0

    @property
    def shader_bytes(self) -> int:
        return sum(g.shader_bytes for g in self.games)


def scan(root: Path | None) -> Report:
    report = Report()
    if root is None:
        return report
    games = {g.appid: g for g in library.installed_games(root, include_pending=True)}
    queued = {d.appid for d in installer.downloads(root)}
    for folder in library.library_folders(root):
        steamapps = folder / "steamapps"
        if not steamapps.is_dir():
            continue  # e.g. the encrypted drive while locked
        try:
            usage = shutil.disk_usage(folder)
            report.libraries.append(LibrarySpace(folder, usage.free, usage.total))
        except OSError:
            pass
        for appid, game in games.items():
            if Path(game.install_dir).parent.parent != steamapps:
                continue
            shader = steamapps / "shadercache" / str(appid)
            game_bytes = game.size_on_disk or tree_size(Path(game.install_dir))
            report.games.append(GameSpace(appid, game.name, game_bytes,
                                          tree_size(shader) if shader.is_dir() else 0, folder))
        for kind in ("downloading", "temp"):
            for entry in sorted((steamapps / kind).glob("*")) if (steamapps / kind).is_dir() else []:
                if entry.is_dir() and entry.name.isdigit() and int(entry.name) not in queued:
                    report.leftovers.append(entry)
                    report.leftover_bytes += tree_size(entry)
    report.games.sort(key=lambda g: g.game_bytes + g.shader_bytes, reverse=True)
    return report


def clear_shader_cache(game: GameSpace) -> int:
    path = game.library / "steamapps" / "shadercache" / str(game.appid)
    if not path.is_dir():
        return 0
    freed = tree_size(path)
    shutil.rmtree(path, ignore_errors=True)
    return freed


def clear_leftovers(report: Report) -> int:
    freed = 0
    for path in report.leftovers:
        if path.parent.name in ("downloading", "temp") and path.parent.parent.name == "steamapps":
            freed += tree_size(path)
            shutil.rmtree(path, ignore_errors=True)
    return freed

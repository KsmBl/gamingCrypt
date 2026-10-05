"""Removing an emulated game: its files - and, when asked, its save states and memory card.

RetroArch names saves after the game file ("Game.srm", "Game.state1", "Game.ldci"), in
saves/ and states/ or a folder per core below them; LRPS2 keeps per-game memory cards
in bios/pcsx2/memcards. A game on several discs: the discs, their tracks and the
playlist GamingCrypt wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gamingcrypt.emulation.library import EmulationPaths, RomGame, _referenced


@dataclass
class Removal:
    files: list[Path]  # the game
    saves: list[Path]  # save states, memory cards, RetroArch's disc memory

    @staticmethod
    def size(files: list[Path]) -> int:
        total = 0
        for f in files:
            try:
                total += f.stat().st_size
            except OSError:
                pass
        return total

    @property
    def files_size(self) -> int:
        return self.size(self.files)

    @property
    def saves_size(self) -> int:
        return self.size(self.saves)


def game_files(game: RomGame) -> list[Path]:
    """The images and what they point to (.m3u -> .cue -> .bin tracks)."""
    queue = list(game.discs) or [game.path]
    found: list[Path] = []
    while queue:
        image = queue.pop(0)
        if image in found:
            continue
        found.append(image)
        if image.suffix.lower() in (".cue", ".gdi", ".m3u"):
            wanted = _referenced(image)
            try:
                queue += [f for f in image.parent.iterdir() if f.name.lower() in wanted and f != image]
            except OSError:
                pass
    if game.discs:
        found.append(game.path)  # the playlist GamingCrypt wrote
    return [f for f in dict.fromkeys(found) if f.exists()]


def _named_like(folder: Path, stems: set[str]) -> list[Path]:
    """Files called "<stem>.<something>" anywhere below the folder."""
    try:
        files = [f for f in folder.rglob("*") if f.is_file()]
    except OSError:
        return []
    return [f for f in files if any(f.name == stem or f.name.startswith(stem + ".") for stem in stems)]


def save_files(paths: EmulationPaths, game: RomGame) -> list[Path]:
    stems = {game.path.stem} | {disc.stem for disc in game.discs}
    found = _named_like(paths.saves, stems) + _named_like(paths.states, stems)
    found += _named_like(paths.bios / "pcsx2" / "memcards", stems)
    return sorted(set(found))


def plan(paths: EmulationPaths, game: RomGame) -> Removal:
    return Removal(game_files(game), save_files(paths, game))


def remove(paths: EmulationPaths, game: RomGame, with_saves: bool) -> int:
    """Delete it; the bytes freed. GamingCrypt's own leftovers (cover, options) go too."""
    removal = plan(paths, game)
    targets = removal.files + (removal.saves if with_saves else [])
    from gamingcrypt.emulation import retroarch

    leftovers = [paths.config / "covers" / game.system.id / f"{game.path.stem}{suffix}" for suffix in (".png", ".miss", ".nomatch")]
    leftovers.append(retroarch.core_options_file(paths, game))
    freed = Removal.size(targets)
    for f in targets + leftovers:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass
    return freed

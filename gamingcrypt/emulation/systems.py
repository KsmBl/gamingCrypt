"""The systems GamingCrypt knows: folder name, game file types, RetroArch cores (best first)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class System:
    id: str
    name: str
    extensions: tuple[str, ...]
    cores: tuple[str, ...]  # RetroArch core names (file "<name>_libretro.so"), preferred first
    bios: tuple[str, ...] = ()  # files the cores need in bios/ (checked, never shipped)

    @property
    def folder(self) -> str:
        return self.id


ARCHIVES = (".zip", ".7z")
DISCS = (".cue", ".chd", ".iso", ".m3u", ".pbp", ".cso")

SYSTEMS: tuple[System, ...] = (
    System("nes", "Nintendo Entertainment System", (".nes", ".fds", ".unf") + ARCHIVES,
           ("mesen", "nestopia", "fceumm")),
    System("snes", "Super Nintendo", (".sfc", ".smc", ".fig", ".swc") + ARCHIVES, ("snes9x", "bsnes")),
    System("n64", "Nintendo 64", (".n64", ".z64", ".v64") + ARCHIVES, ("mupen64plus_next", "parallel_n64")),
    System("gb", "Game Boy", (".gb",) + ARCHIVES, ("gambatte", "sameboy", "mgba")),
    System("gbc", "Game Boy Color", (".gbc",) + ARCHIVES, ("gambatte", "sameboy", "mgba")),
    System("gba", "Game Boy Advance", (".gba",) + ARCHIVES, ("mgba", "vba_next"), ("gba_bios.bin",)),
    System("nds", "Nintendo DS", (".nds",) + ARCHIVES, ("melonds", "desmume")),
    System("gc", "GameCube", (".iso", ".gcm", ".gcz", ".rvz", ".ciso"), ("dolphin",)),
    System("mastersystem", "Sega Master System", (".sms",) + ARCHIVES, ("genesis_plus_gx", "picodrive")),
    System("megadrive", "Sega Mega Drive / Genesis", (".md", ".gen", ".smd", ".bin") + ARCHIVES,
           ("genesis_plus_gx", "picodrive")),
    System("gamegear", "Sega Game Gear", (".gg",) + ARCHIVES, ("genesis_plus_gx",)),
    System("segacd", "Sega CD", (".cue", ".chd", ".iso", ".m3u"), ("genesis_plus_gx",),
           ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin")),
    System("saturn", "Sega Saturn", (".cue", ".chd", ".m3u"), ("mednafen_saturn", "yabasanshiro"),
           ("sega_101.bin", "mpr-17933.bin")),
    System("dreamcast", "Sega Dreamcast", (".cdi", ".gdi", ".chd", ".m3u"), ("flycast",)),
    System("psx", "PlayStation", DISCS, ("swanstation", "mednafen_psx_hw", "pcsx_rearmed"),
           ("scph5501.bin",)),
    System("psp", "PlayStation Portable", (".iso", ".cso", ".pbp", ".chd"), ("ppsspp",)),
    System("pce", "PC Engine / TurboGrafx-16", (".pce", ".cue", ".chd") + ARCHIVES, ("mednafen_pce_fast",)),
    System("atari2600", "Atari 2600", (".a26", ".bin") + ARCHIVES, ("stella",)),
    System("arcade", "Arcade", (".zip", ".7z"), ("fbneo", "mame2003_plus")),
)
BY_ID = {s.id: s for s in SYSTEMS}

"""Game speed for Windows, Linux and Steam games (and Minecraft): their clock runs faster or slower,
as with Cheat Engine's speedhack - changed while the game runs, from the quick menu.

speedhack.c (prebuilt here, 64- and 32-bit) is preloaded into every game GamingCrypt starts and
into Steam (which hands it on to its games); it reads the speed for one game from a small file
(see speed_file). Both libraries are preloaded: each process takes the one that fits it (the
other is skipped - ld.so notes that in the game's log, as with Steam's overlay).
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIBRARIES = (HERE / "libgamingcrypt-speed64.so", HERE / "libgamingcrypt-speed32.so")
APPID_VARIABLE = "GAMINGCRYPT_SPEED_APPID"


def available(machine: str | None = None) -> bool:
    """x86 PCs (the prebuilt libraries), with /dev/shm for the speed file."""
    return ((machine or platform.machine()).lower() in ("x86_64", "amd64") and all(p.is_file() for p in LIBRARIES)
            and Path("/dev/shm").is_dir())


def speed_file(uid: int | None = None) -> Path:
    return Path("/dev/shm") / f"gamingcrypt-speed-{os.getuid() if uid is None else uid}"


def preload(existing: str = "") -> str:
    """LD_PRELOAD with the libraries added (what's there already stays first, e.g. MangoHud)."""
    parts = [p for p in existing.replace(" ", ":").split(":") if p and Path(p).name not in
             {lib.name for lib in LIBRARIES}]
    return ":".join([*parts, *(str(lib) for lib in LIBRARIES)])


def game_env(appid: int, base: dict | None = None) -> dict[str, str]:
    """For a game GamingCrypt starts: the libraries, and which game it is."""
    if not available():
        return {}
    base = os.environ if base is None else base
    return {"LD_PRELOAD": preload(base.get("LD_PRELOAD", "")), APPID_VARIABLE: str(int(appid))}


def steam_env(base: dict | None = None) -> dict[str, str]:
    """For starting Steam: its games get the libraries from it (they know their app id themselves;
    Steam's own processes have none and are never touched)."""
    base = dict(os.environ if base is None else base)
    if available():
        base["LD_PRELOAD"] = preload(base.get("LD_PRELOAD", ""))
    return base


def set_speed(appid: int, speed: float, path: Path | None = None) -> None:
    """The game's clock at this speed from now on (1: as it is)."""
    path = path or speed_file()
    if abs(speed - 1.0) < 1e-6:
        clear(path)
        return
    part = path.with_name(path.name + ".part")
    part.write_text(f"{speed:g} {int(appid)}\n")
    part.replace(path)  # (read whole or not at all)


def clear(path: Path | None = None) -> None:
    (path or speed_file()).unlink(missing_ok=True)


def loaded(pids, proc: Path = Path("/proc")) -> bool:
    """Is the speedhack in one of these processes (the game was started with it)?"""
    names = {lib.name for lib in LIBRARIES}
    for pid in pids:
        try:
            maps = (proc / str(pid) / "maps").read_text(errors="replace")
        except OSError:
            continue
        if any(name in maps for name in names):
            return True
    return False

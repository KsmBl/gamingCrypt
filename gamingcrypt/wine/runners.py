"""What starts a Windows game: a Proton (Steam's official ones, GE-Proton & co.) or a Wine.

Proton outside of Steam: through umu-launcher when it's installed (it brings Steam's
runtime), otherwise Proton's own "proton run" script.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.wine.library import WindowsGame, prefix_dir


@dataclass(frozen=True)
class Runner:
    id: str  # "proton:GE-Proton9-20", "wine:system"
    label: str
    kind: str  # "proton" / "wine"
    path: Path  # Proton's folder, or the wine program


def _version_key(runner: Runner) -> tuple:
    numbers = [int(n) for n in re.findall(r"\d+", runner.label)]
    return (runner.kind != "proton", "experimental" not in runner.label.lower(), [-n for n in numbers],
            runner.label.casefold())


def steam_roots(home: Path) -> list[Path]:
    return [home / ".local" / "share" / "Steam", home / ".steam" / "steam", home / ".steam" / "root",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]


def proton_runners(home: Path, extra_libraries: list[Path] = ()) -> list[Runner]:
    found: dict[str, Runner] = {}
    from gamingcrypt.steam.library import library_folders

    folders = []
    for root in steam_roots(home):
        folders.append(root / "compatibilitytools.d")
        # Steam's own Protons: in any of its libraries (also the one on the encrypted drive)
        folders += [lib / "steamapps" / "common" for lib in library_folders(root)]
    folders += [Path(p) / "steamapps" / "common" for p in extra_libraries]
    folders.append(Path("/usr/share/steam/compatibilitytools.d"))
    for folder in folders:
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if (entry / "proton").is_file():
                key = f"proton:{entry.name}"
                found.setdefault(key, Runner(key, entry.name, "proton", entry))
    return list(found.values())


def wine_runners(home: Path, which: Callable[[str], str | None] = shutil.which) -> list[Runner]:
    found = []
    system = which("wine")
    if system:
        found.append(Runner("wine:system", "Wine (system)", "wine", Path(system)))
    lutris = home / ".local" / "share" / "lutris" / "runners" / "wine"
    try:
        builds = sorted(lutris.iterdir())
    except OSError:
        builds = []
    for build in builds:
        program = build / "bin" / "wine"
        if program.is_file():
            found.append(Runner(f"wine:{build.name}", f"Wine {build.name}", "wine", program))
    return found


def available(home: Path | None = None, which: Callable[[str], str | None] = shutil.which,
              extra_libraries: list[Path] = ()) -> list[Runner]:
    """Every Proton and Wine on this device, the newest Proton first."""
    home = home or Path.home()
    return sorted(proton_runners(home, extra_libraries) + wine_runners(home, which), key=_version_key)


ICD_DIRS = (Path("/usr/share/vulkan/icd.d"), Path("/etc/vulkan/icd.d"))


def is_32bit(exe: Path) -> bool:
    """A 32-bit Windows program (PE machine i386) - old games like GTA San Andreas."""
    try:
        with open(exe, "rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    if head[:2] != b"MZ" or len(head) < 0x40:
        return False
    pe = int.from_bytes(head[0x3C:0x40], "little")
    return head[pe:pe + 4] == b"PE\0\0" and int.from_bytes(head[pe + 4:pe + 6], "little") == 0x14C


DRIVER_VENDORS = {"radeon": "0x1002", "amd": "0x1002", "intel": "0x8086", "nvidia": "0x10de"}


def gpu_vendors(drm: Path = Path("/sys/class/drm")) -> set[str]:
    found = set()
    for vendor in drm.glob("card*/device/vendor"):
        try:
            found.add(vendor.read_text().strip().lower())
        except OSError:
            pass
    return found


def vulkan_32bit(icd_dirs=ICD_DIRS, lib32: Path = Path("/usr/lib32"), vendors: set[str] | None = None) -> bool:
    """Is there a 32-bit Vulkan driver for this device's GPU? Proton draws 32-bit games through it
    (DXVK): without one they find no GPU and quit right after starting. (A driver for a GPU that
    isn't there doesn't count - the handheld had NVIDIA's installed next to its AMD GPU.)"""
    import json

    vendors = gpu_vendors() if vendors is None else vendors
    for folder in icd_dirs:
        try:
            files = list(Path(folder).glob("*.json"))
        except OSError:
            continue
        for file in files:
            try:
                library = json.loads(file.read_text()).get("ICD", {}).get("library_path", "")
            except (OSError, ValueError, AttributeError):
                continue
            needs = next((v for name, v in DRIVER_VENDORS.items() if name in library.lower()), None)
            if needs is None or needs not in vendors:
                continue  # software rendering, or another GPU's driver
            if "/lib32/" in library or "i386" in library:
                return True  # e.g. radeon_icd.i686.json -> /usr/lib32/libvulkan_radeon.so
            if library and "/" not in library and (lib32 / library).exists():
                return True  # one name for both (e.g. NVIDIA's): its 32-bit library is there
    return False


VULKAN_32 = ("{game} is a 32-bit game - Proton needs the 32-bit Vulkan driver for it, which isn't installed. "
             "Run ./install.sh again (or: sudo pacman -S lib32-vulkan-radeon on AMD, lib32-vulkan-intel on Intel).")


def pick(runners: list[Runner], wanted: str | None) -> Runner | None:
    """The chosen one - or the default (the newest Proton, else a Wine)."""
    return next((r for r in runners if r.id == wanted), runners[0] if runners else None)


def command(runner: Runner, game: WindowsGame, exe: str, home: Path,
            which: Callable[[str], str | None] = shutil.which) -> tuple[list[str], dict[str, str], Path]:
    """(program and arguments, environment additions, working folder)."""
    target = game.path / exe
    prefix = prefix_dir(game)
    env = {"WINEDEBUG": "-all"}
    if runner.kind == "wine":
        env["WINEPREFIX"] = str(prefix / "pfx")
        return [str(runner.path), str(target)], env, target.parent
    umu = which("umu-run")
    if umu:  # Steam's runtime around Proton, as in Steam
        env.update(WINEPREFIX=str(prefix / "pfx"), PROTONPATH=str(runner.path), GAMEID="umu-default",
                   STORE="none")
        return [umu, str(target)], env, target.parent
    steam = next((r for r in steam_roots(home) if r.is_dir()), steam_roots(home)[0])
    env.update(STEAM_COMPAT_DATA_PATH=str(prefix), STEAM_COMPAT_CLIENT_INSTALL_PATH=str(steam))
    return [str(runner.path / "proton"), "run", str(target)], env, target.parent


def launch(game: WindowsGame, exe: str, runner: Runner, data_dir: Path, log_dir: Path,
           popen=subprocess.Popen, home: Path | None = None,
           which: Callable[[str], str | None] = shutil.which) -> tuple[bool, str]:
    """Start it like a Steam game (the "reaper" wrapper: gamescope, quick menu, Force quit)."""
    from gamingcrypt.emulation.retroarch import reaper

    home = home or Path.home()
    if not (game.path / exe).is_file():
        return False, f"{exe} isn't in the game's folder any more - pick the start file in Options"
    args, extra, cwd = command(runner, game, exe, home, which)
    prefix_dir(game).mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **extra}
    try:
        with open(log_dir / "wine.log", "wb") as log:
            popen([str(reaper(data_dir)), "SteamLaunch", f"AppId={game.appid}", "--", *args],
                  cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                  start_new_session=True)
    except OSError as exc:
        return False, f"It didn't start: {exc}"
    return True, f"Starting {game.name} with {runner.label}…"

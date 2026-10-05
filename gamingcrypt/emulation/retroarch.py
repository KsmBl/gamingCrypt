"""Starting games with RetroArch (installed natively; cores, BIOS, saves on the drive).

RetroArch is started through a tiny "reaper" script with "SteamLaunch AppId=<id>" -
the shape gamescope (Steam mode) and GamingCrypt's game watcher recognise a game by.
So the emulator gets the screen like a Steam game, the loading screen, quick menu and
Force quit work unchanged.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Callable

from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.emulation.systems import System

COMMAND_PORT = 55355
CORE_DIRS = (Path("/usr/lib/libretro"), Path("/usr/lib64/libretro"))  # system-wide, as a fallback
REAPER = """#!/bin/sh
# Started by GamingCrypt: "reaper SteamLaunch AppId=<id> -- <command>" lets gamescope and
# GamingCrypt treat the emulator like a Steam game. Stays the parent (no exec).
while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do shift; done
[ "$1" = "--" ] && shift
"$@"
"""


def available(which: Callable[[str], str | None] = shutil.which) -> bool:
    return bool(which("retroarch"))


def installed_cores(paths: EmulationPaths) -> dict[str, Path]:
    """core name -> file; the drive's cores/ first (uploaded ones win)."""
    found: dict[str, Path] = {}
    for folder in (paths.cores, *CORE_DIRS):
        try:
            files = sorted(folder.glob("*_libretro.so"))
        except OSError:
            continue
        for f in files:
            found.setdefault(f.name[: -len("_libretro.so")], f)
    return found


def find_core(paths: EmulationPaths, system: System, wanted: str | None = None) -> Path | None:
    cores = installed_cores(paths)
    if wanted and wanted in cores:
        return cores[wanted]
    return next((cores[c] for c in system.cores if c in cores), None)


def write_config(paths: EmulationPaths, extra: dict[str, str] | None = None) -> Path:
    """Settings GamingCrypt needs on top of the user's RetroArch config."""
    settings = {
        "libretro_directory": paths.cores, "system_directory": paths.bios,
        "savefile_directory": paths.saves, "savestate_directory": paths.states,
        "screenshot_directory": paths.screenshots, "libretro_info_path": "/usr/share/libretro/info",
        "video_fullscreen": "true", "pause_nonactive": "false", "config_save_on_exit": "false",
        "network_cmd_enable": "true", "network_cmd_port": str(COMMAND_PORT),
        "input_autodetect_enable": "true", "input_menu_toggle_gamepad_combo": "2",  # L3 + R3: RetroArch menu
        "savestate_auto_index": "false", "menu_driver": "ozone",
        "input_remapping_directory": paths.config / "remaps",
    }
    settings.update(extra or {})
    path = paths.config / "gamingcrypt.cfg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f'{key} = "{value}"\n' for key, value in settings.items()))
    return path


def reaper(data_dir: Path) -> Path:
    path = data_dir / "reaper"
    if not path.exists() or path.read_text() != REAPER:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(REAPER)
    path.chmod(0o755)
    return path


def command(game: RomGame, core: Path, config: Path, reaper_path: Path) -> list[str]:
    return [str(reaper_path), "SteamLaunch", f"AppId={game.appid}", "--",
            "retroarch", "--appendconfig", str(config), "-L", str(core), str(game.path)]


def launch(game: RomGame, paths: EmulationPaths, data_dir: Path, log_dir: Path, core_name: str | None = None,
           popen=subprocess.Popen, which: Callable[[str], str | None] = shutil.which) -> tuple[bool, str]:
    if not available(which):
        return False, "RetroArch isn't installed - run ./install.sh"
    core = find_core(paths, game.system, core_name)
    if core is None:
        wanted = game.system.cores[0]
        return False, (f"No RetroArch core for {game.system.name} yet - add e.g. {wanted}_libretro.so "
                       "to the cores folder (⬆ Add games)")
    config = write_config(paths)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_dir / "retroarch.log", "ab") as log:
            popen(command(game, core, config, reaper(data_dir)), stdin=subprocess.DEVNULL, stdout=log,
                  stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ))
    except OSError as exc:
        return False, f"RetroArch didn't start: {exc}"
    return True, f"Starting {game.name}…"


def send(command_text: str, port: int = COMMAND_PORT) -> bool:
    """RetroArch network command: SAVE_STATE, LOAD_STATE, QUIT …"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(command_text.encode(), ("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()

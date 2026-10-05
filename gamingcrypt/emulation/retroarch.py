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
from gamingcrypt.input import evdev
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


VIRTUAL_PAD = evdev.VIRTUAL_NAME  # what games see while the remapper runs
# RetroArch's udev numbering for an Xbox 360 layout pad (the virtual one and xpad devices)
PAD_BINDS = {
    "input_b_btn": "0", "input_a_btn": "1", "input_y_btn": "2", "input_x_btn": "3", "input_l_btn": "4",
    "input_r_btn": "5", "input_select_btn": "6", "input_start_btn": "7", "input_l3_btn": "9", "input_r3_btn": "10",
    "input_up_btn": "h0up", "input_down_btn": "h0down", "input_left_btn": "h0left", "input_right_btn": "h0right",
    "input_l2_axis": "+2", "input_r2_axis": "+5",
    "input_l_x_plus_axis": "+0", "input_l_x_minus_axis": "-0", "input_l_y_plus_axis": "+1",
    "input_l_y_minus_axis": "-1", "input_r_x_plus_axis": "+3", "input_r_x_minus_axis": "-3",
    "input_r_y_plus_axis": "+4", "input_r_y_minus_axis": "-4",
}
PADS = (VIRTUAL_PAD, "Microsoft X-Box 360 pad")


def write_autoconfig(folder: Path) -> Path:
    """Controller profiles, so RetroArch knows the buttons (no autoconfig package needed)."""
    udev = folder / "udev"
    udev.mkdir(parents=True, exist_ok=True)
    for name in PADS:
        lines = {"input_driver": "udev", "input_device": name, "input_vendor_id": "1118",
                 "input_product_id": "654", **PAD_BINDS}
        (udev / f"{name}.cfg").write_text("".join(f'{k} = "{v}"\n' for k, v in lines.items()))
    return folder


def write_config(paths: EmulationPaths, extra: dict[str, str] | None = None) -> Path:
    """Settings GamingCrypt needs on top of the user's RetroArch config."""
    settings = {
        "libretro_directory": paths.cores, "system_directory": paths.bios,
        "savefile_directory": paths.saves, "savestate_directory": paths.states,
        "screenshot_directory": paths.screenshots, "libretro_info_path": "/usr/share/libretro/info",
        "video_fullscreen": "true", "pause_nonactive": "false", "config_save_on_exit": "false",
        "network_cmd_enable": "true", "network_cmd_port": str(COMMAND_PORT),
        "input_autodetect_enable": "true", "input_menu_toggle_gamepad_combo": "2",  # L3 + R3: RetroArch menu
        "savestate_auto_index": "false", "menu_driver": "ozone", "auto_remaps_enable": "true",
        "input_remapping_directory": paths.config / "remaps",
        # the physical pad is grabbed by the remapper: player 1 is the virtual one when it's there
        "input_joypad_driver": "udev", "joypad_autoconfig_dir": write_autoconfig(paths.config / "autoconfig"),
        "input_player1_reserved_device": VIRTUAL_PAD, "input_player1_device_reservation_type": "1",
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
           popen=subprocess.Popen, which: Callable[[str], str | None] = shutil.which,
           layout: dict[str, str] | None = None) -> tuple[bool, str]:
    if not available(which):
        return False, "RetroArch isn't installed - run ./install.sh"
    core = find_core(paths, game.system, core_name)
    if core is None:
        wanted = game.system.cores[0]
        return False, (f"No RetroArch core for {game.system.name} yet - add e.g. {wanted}_libretro.so "
                       "to the cores folder (⬆ Add emulator games)")
    config = write_config(paths)
    from gamingcrypt.emulation import layouts

    layouts.write_remap(paths.config / "remaps", core.name, game.system.id, layout or {})  # the system's layout
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

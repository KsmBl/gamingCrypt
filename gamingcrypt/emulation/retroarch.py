"""Starting games with RetroArch (installed natively; cores, BIOS, saves on the drive).

RetroArch is started through a tiny "reaper" script with "SteamLaunch AppId=<id>" -
the shape gamescope (Steam mode) and GamingCrypt's game watcher recognise a game by.
So the emulator gets the screen like a Steam game, the loading screen, quick menu and
Force quit work unchanged.
"""

from __future__ import annotations

import os
import re
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


FAST_SPEEDS = (1.25, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0)
SLOW_SPEEDS = (0.1, 0.25, 0.5, 0.75)
DEFAULT_FAST, DEFAULT_SLOW = 2.0, 0.5
MODES = ("slow", "normal", "fast")


def speed_settings(fast: float = DEFAULT_FAST, slow: float = DEFAULT_SLOW) -> dict[str, str]:
    """The rates of fast-forward and slow motion (RetroArch reads them only at start; switching
    between slow / normal / fast is instant)."""
    return {"fastforward_ratio": f"{fast:g}", "slowmotion_ratio": f"{1 / slow:g}"}


def mode_commands(old: str, new: str) -> list[str]:
    """RetroArch's toggles from one speed mode to another."""
    commands = []
    if old != new:
        if old == "fast":
            commands.append("FAST_FORWARD")
        if old == "slow":
            commands.append("SLOWMOTION")
        if new == "fast":
            commands.append("FAST_FORWARD")
        if new == "slow":
            commands.append("SLOWMOTION")
    return commands


# Input lag. Light systems: preemptive frames (when a button changes, RetroArch re-runs the
# last frame with it - one frame less delay, cheap for these cores) and a short display queue.
# Heavy ones (PS1/PS2/N64/GameCube ...) would lose speed: only the input is read late.
LOW_LAG_SYSTEMS = {"nes", "snes", "gb", "gbc", "gba", "megadrive", "mastersystem", "gamegear", "pce", "atari2600"}
LOW_LAG = {"preemptive_frames_enable": "true", "run_ahead_frames": "1", "run_ahead_enabled": "false",
           "video_hard_sync": "true", "video_hard_sync_frames": "0", "video_max_swapchain_images": "2"}
NORMAL_LAG = {"preemptive_frames_enable": "false", "run_ahead_enabled": "false", "video_hard_sync": "false",
              "video_max_swapchain_images": "3"}


def lag_settings(system_id: str, choice: str | None = None) -> dict[str, str]:
    """choice: None = automatic (reduced on light systems), "normal" = off."""
    settings = {"input_poll_type_behavior": "2"}  # late: the input as fresh as possible
    reduced = system_id in LOW_LAG_SYSTEMS and choice != "normal"
    settings.update(LOW_LAG if reduced else NORMAL_LAG)
    return settings


# Memory card per game or one for all games - the cores' own options (checked in the core files)
MEMORY_CARDS = {
    "swanstation": {"own": {"swanstation_MemoryCards_Card1Type": "Libretro"},
                    "shared": {"swanstation_MemoryCards_Card1Type": "Shared"}},
    "pcsx2": {"own": {"pcsx2_shared_memory_cards": "disabled"},
              "shared": {"pcsx2_shared_memory_cards": "enabled"}},
}


# Widescreen: the core reports 16:9 (and patches games that have no own setting) - a 4:3 game
# would be stretched, so it's per game ("Screen" in the game's options)
WIDESCREEN = {"pcsx2": {"16:9": {"pcsx2_widescreen_hint": "enabled (16:9)"},
                        None: {"pcsx2_widescreen_hint": "disabled"}}}


def core_options_file(paths: EmulationPaths, game: RomGame) -> Path:
    return paths.config / "core-options" / game.system.id / f"{game.path.stem}.opt"


def write_core_options(path: Path, values: dict[str, str]) -> Path:
    """Set options in the game's own core options file; what RetroArch saved there stays."""
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if line.split("=", 1)[0].strip() not in values]
    lines += [f'{key} = "{value}"' for key, value in values.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def disc_commands(current: int, target: int) -> list[str]:
    """Open the tray, step to the disc, close it (RetroArch's disc control)."""
    if current == target:
        return []
    step = "DISK_NEXT" if target > current else "DISK_PREV"
    return ["DISK_EJECT_TOGGLE", *[step] * abs(target - current), "DISK_EJECT_TOGGLE"]


def current_disc(paths: EmulationPaths, game: RomGame, core: Path | None) -> int:
    """The disc RetroArch starts with (it remembers the last one in an .ldci file) - 0-based."""
    import json

    from gamingcrypt.emulation import layouts

    if not game.discs:
        return 0
    folders = [paths.saves] + ([paths.saves / layouts.core_name(core.name)] if core else [])
    for folder in folders:
        try:
            data = json.loads((folder / f"{game.path.stem}.ldci").read_text())
        except (OSError, ValueError):
            continue
        name = Path(str(data.get("image_path", ""))).name if isinstance(data, dict) else ""
        for index, disc in enumerate(game.discs):
            if disc.name == name:
                return index
    return 0


def command(game: RomGame, core: Path, config: Path, reaper_path: Path) -> list[str]:
    return [str(reaper_path), "SteamLaunch", f"AppId={game.appid}", "--",
            "retroarch", "--verbose", "--appendconfig", str(config), "-L", str(core), str(game.path)]


def launch(game: RomGame, paths: EmulationPaths, data_dir: Path, log_dir: Path, core_name: str | None = None,
           popen=subprocess.Popen, which: Callable[[str], str | None] = shutil.which,
           layout: dict[str, str] | None = None, fast: float = DEFAULT_FAST,
           slow: float = DEFAULT_SLOW, memory_card: str | None = None,
           widescreen: str | None = None, input_lag: str | None = None) -> tuple[bool, str]:
    if not available(which):
        return False, "RetroArch isn't installed - run ./install.sh"
    core = find_core(paths, game.system, core_name)
    if core is None:
        wanted = game.system.cores[0]
        return False, (f"No RetroArch core for {game.system.name} yet - add e.g. {wanted}_libretro.so "
                       "to the cores folder (⬆ Add emulator games)")
    extra = {**speed_settings(fast, slow), **lag_settings(game.system.id, input_lag)}
    if game.system.video:
        extra["video_driver"] = game.system.video
    short = core.name.removesuffix(".so").removesuffix("_libretro")
    options = dict(MEMORY_CARDS.get(short, {}).get(memory_card or "", {}))
    if short in WIDESCREEN and (widescreen or core_options_file(paths, game).exists() or options):
        options.update(WIDESCREEN[short].get(widescreen, WIDESCREEN[short][None]))
    if options:  # the game's own core options file
        extra["global_core_options"] = "true"
        extra["core_options_path"] = write_core_options(core_options_file(paths, game), options)
    config = write_config(paths, extra)
    from gamingcrypt.emulation import layouts

    layouts.write_remap(paths.config / "remaps", core.name, game.system.id, layout or {})  # the system's layout
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_dir / LOG_NAME, "wb") as log:  # this game's log (its frame rate is read from it)
            popen(command(game, core, config, reaper(data_dir)), stdin=subprocess.DEVNULL, stdout=log,
                  stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ))
    except OSError as exc:
        return False, f"RetroArch didn't start: {exc}"
    return True, f"Starting {game.name}…"


LOG_NAME = "retroarch.log"
_FPS = re.compile(r"(?:SET_SYSTEM_AV_INFO|\[Core\] Geometry):.*?FPS: ([0-9.]+)")


def content_fps(log: Path) -> float | None:
    """The frame rate the running game asked for last (from RetroArch's log), e.g. 50 for PAL."""
    try:
        with open(log, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 512 * 1024))
            text = fh.read().decode(errors="replace")
    except OSError:
        return None
    found = _FPS.findall(text)
    return float(found[-1]) if found else None


def refresh_for(fps: float | None) -> int:
    """The screen refresh that shows the game evenly: 50 Hz for 50 fps games, else the default (0)."""
    return 50 if fps is not None and abs(fps - 50) < 0.5 else 0


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

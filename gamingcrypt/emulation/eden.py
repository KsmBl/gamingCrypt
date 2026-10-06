"""Nintendo Switch games with Eden (a standalone emulator - there's no RetroArch core).

Eden is downloaded on first use (its AppImage, unpacked once - no FUSE needed) into
GamingCrypt's data folder, outside the drive. Everything of the games lives on the
encrypted drive: Eden's data (saves, NAND, keys) in Emulation/saves/switch, its
settings in Emulation/config/switch. The keys and firmware are taken from
bios/switch. Started through the same "reaper" script as RetroArch, so gamescope
and GamingCrypt treat it like a Steam game.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import requests

from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.input import evdev

RELEASES = "https://git.eden-emu.dev/api/v1/repos/eden-emu/eden/releases?limit=5"
FALLBACK = "https://stable.eden-emu.dev/v0.2.1/Eden-Linux-v0.2.1-{arch}-clang-pgo.AppImage"
ARCHES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "aarch64", "arm64": "aarch64"}


def install_dir() -> Path:
    from gamingcrypt.system.updater import data_dir

    return data_dir() / "emulators" / "eden"


def app_run(folder: Path | None = None) -> Path:
    return (folder or install_dir()) / "app" / "AppRun"


def available(folder: Path | None = None) -> bool:
    return app_run(folder).exists()


def download_url(get: Callable, machine: str | None = None) -> str | None:
    """The newest release's AppImage for this machine."""
    arch = ARCHES.get((machine or platform.machine()).lower())
    if arch is None:
        return None
    try:
        for release in get(RELEASES).json():
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(f"-{arch}-clang-pgo.AppImage") and name.startswith("Eden-Linux"):
                    return asset["browser_download_url"]
    except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError):
        pass
    return FALLBACK.format(arch=arch)


def install(folder: Path | None = None, get: Callable | None = None, runner=subprocess.run,
            machine: str | None = None) -> Path | None:
    """Download and unpack Eden; the AppRun to start it (None: offline / failed)."""
    folder = folder or install_dir()
    if available(folder):
        return app_run(folder)
    get = get or (lambda url: requests.get(url, timeout=600))
    url = download_url(get, machine)
    if url is None:
        return None
    try:
        response = get(url)
    except requests.RequestException:
        return None
    if response.status_code != 200 or not response.content.startswith(b"\x7fELF"):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    image = folder / "Eden.AppImage"
    image.write_bytes(response.content)
    image.chmod(0o755)
    shutil.rmtree(folder / "squashfs-root", ignore_errors=True)
    try:
        runner([str(image), "--appimage-extract"], cwd=str(folder), capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        image.unlink(missing_ok=True)
    unpacked = folder / "squashfs-root"
    if not (unpacked / "AppRun").exists():
        shutil.rmtree(unpacked, ignore_errors=True)
        return None
    shutil.rmtree(folder / "app", ignore_errors=True)
    unpacked.rename(folder / "app")
    return app_run(folder)


# --- the controller ----------------------------------------------------------------------------

def _crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def sdl_guid(name: str = evdev.VIRTUAL_NAME, bus: int = evdev.BUS_USB, vendor: int = evdev.VIRTUAL_VENDOR,
             product: int = evdev.VIRTUAL_PRODUCT, version: int = 0x0110) -> str:
    """SDL's id of a controller (what Eden's input settings name it by)."""
    crc = _crc16(name.encode())
    raw = b"".join(v.to_bytes(2, "little") for v in (bus, crc, vendor, 0, product, 0, version, 0))
    return raw.hex()


def controls(guid: str | None = None) -> dict[str, str]:
    """Player 1 = GamingCrypt's virtual controller, buttons where a Switch has them
    (A right, B bottom - like the RetroArch systems)."""
    sdl = f"guid:{guid or sdl_guid()},port:0,engine:sdl"
    buttons = {"a": 1, "b": 0, "x": 3, "y": 2, "l": 4, "r": 5, "minus": 6, "plus": 7, "home": 8,
               "lstick": 9, "rstick": 10}
    values = {f"player_0_button_{k}": f'"button:{v},{sdl}"' for k, v in buttons.items()}
    values.update({f"player_0_button_d{d}": f'"hat:0,direction:{d},{sdl}"' for d in ("up", "down", "left", "right")})
    values["player_0_button_zl"] = f'"axis:2,threshold:0.500000,invert:+,{sdl}"'
    values["player_0_button_zr"] = f'"axis:5,threshold:0.500000,invert:+,{sdl}"'
    values["player_0_lstick"] = f'"axis_x:0,axis_y:1,deadzone:0.150000,range:1.000000,{sdl}"'
    values["player_0_rstick"] = f'"axis_x:3,axis_y:4,deadzone:0.150000,range:1.000000,{sdl}"'
    values["player_0_connected"] = "true"
    values["player_0_type"] = "0"  # Pro Controller
    return values


SETTINGS = {
    "UI": {"firstStart": "false", "check_for_updates": "false", "fullscreen": "true", "confirmStop": "2"},
}


def merge_ini(text: str, section: str, values: dict[str, str]) -> str:
    """Set keys in a Qt ini (with the "\\default=false" Qt marks them changed with)."""
    lines = text.splitlines()
    wanted = {**{f"{k}\\default": "false" for k in values}, **values}
    start = next((i for i, line in enumerate(lines) if line.strip() == f"[{section}]"), None)
    if start is None:
        lines += ([""] if lines else []) + [f"[{section}]"]
        start = len(lines) - 1
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    seen = set()
    for i in range(start + 1, end):
        key = lines[i].split("=", 1)[0]
        if key in wanted:
            lines[i] = f"{key}={wanted[key]}"
            seen.add(key)
    missing = [f"{k}={v}" for k, v in wanted.items() if k not in seen]
    lines[end:end] = missing
    return "\n".join(lines) + "\n"


def prepare(paths: EmulationPaths) -> dict[str, str]:
    """Eden's folders on the drive, keys + firmware from bios/switch, settings; the environment to start it."""
    data, config = paths.saves / "switch", paths.config / "switch"
    eden_data = data / "eden"
    keys = eden_data / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    source = paths.bios / "switch"
    for name in ("prod.keys", "title.keys"):
        if (source / name).is_file():
            shutil.copy2(source / name, keys / name)
    firmware = source / "firmware"
    if firmware.is_dir():
        registered = eden_data / "nand" / "system" / "Contents" / "registered"
        registered.mkdir(parents=True, exist_ok=True)
        for nca in firmware.glob("*.nca"):
            link = registered / nca.name
            if not link.exists():
                link.symlink_to(nca)
    ini = config / "eden" / "qt-config.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    text = ini.read_text() if ini.exists() else ""
    text = merge_ini(text, "Controls", controls())
    for section, values in SETTINGS.items():
        text = merge_ini(text, section, values)
    ini.write_text(text)
    return {"XDG_DATA_HOME": str(data), "XDG_CONFIG_HOME": str(config), "QT_QPA_PLATFORM": "xcb"}


def launch(game: RomGame, paths: EmulationPaths, data_dir: Path, log_dir: Path, popen=subprocess.Popen,
           folder: Path | None = None) -> tuple[bool, str]:
    from gamingcrypt.emulation import retroarch

    if not available(folder):
        return False, "The Switch emulator (Eden) isn't installed yet"
    env = dict(os.environ, **prepare(paths))
    command = [str(retroarch.reaper(data_dir)), "SteamLaunch", f"AppId={game.appid}", "--",
               str(app_run(folder)), "-f", "-g", str(game.path)]
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_dir / "eden.log", "ab") as log:
            popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                  start_new_session=True, env=env)
    except OSError as exc:
        return False, f"Eden didn't start: {exc}"
    return True, f"Starting {game.name}…"

"""Playing a movie with mpv - full screen, controller and touch, resumable.

mpv is started through the same "reaper SteamLaunch AppId=<id>" wrapper as the
emulators, so gamescope shows it like a game and the quick menu, volume popup and
Force quit work. GamingCrypt asks mpv (JSON IPC socket) every few seconds where
it is and keeps that in the movie's .nfo - so a closed, crashed or force-quit
movie goes on where it was.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Callable

from gamingcrypt.movies.library import Movie

SOCKET_NAME = "gamingcrypt-mpv.sock"
LOG_NAME = "mpv.log"
# No volume of its own: the volume buttons and the quick menu set the device's volume
# (GamingCrypt shows it). Touch: touch.lua. The controller is read by GamingCrypt (remote_command): mpv
# would take the physical pad, which GamingCrypt holds - its buttons never reach mpv.
INPUT_CONF = """\
VOLUME_UP ignore
VOLUME_DOWN ignore
MUTE ignore
WHEEL_UP ignore
WHEEL_DOWN ignore
9 ignore
0 ignore
/ ignore
* ignore
m ignore
"""
TOUCH_SCRIPT = Path(__file__).with_name("touch.lua")  # big buttons instead of mpv's own controls
CONTROLS = ("A / Start: pause · B: stop · ◀ ▶: 10 s back / 30 s on · ▲ ▼: 5 min · LB / RB: chapter · "
            "X: subtitles · Y: audio language · Touch: tap for the controls, double tap left / right: 10 s")


def available(which: Callable[[str], str | None] = shutil.which) -> bool:
    return bool(which("mpv"))


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/gamingcrypt-{os.getuid()}"
    return Path(runtime) / SOCKET_NAME


def input_conf(data_dir: Path) -> Path:
    path = data_dir / "mpv-input.conf"
    if not path.exists() or path.read_text() != INPUT_CONF:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(INPUT_CONF)
    return path


def command(movie: Movie, reaper_path: Path, sock: Path, conf: Path, start: float = 0,
            languages: tuple[str, ...] = ("en", "de")) -> list[str]:
    args = [str(reaper_path), "SteamLaunch", f"AppId={movie.appid}", "--",
            "mpv", "--fs", "--force-window=immediate", "--keep-open=no", "--idle=no", "--no-terminal",
            "--hwdec=auto-safe", "--input-gamepad=no", f"--input-conf={conf}", f"--input-ipc-server={sock}",
            "--volume=100", "--volume-max=100", "--osc=no", f"--script={TOUCH_SCRIPT}",
            "--cursor-autohide=always",
            "--save-position-on-quit=no", f"--title={movie.title}", f"--force-media-title={movie.title}",
            f"--alang={','.join(languages)}",
            f"--slang={','.join(languages)}"]
    if start > 0:
        args.append(f"--start={start:.1f}")
    return [*args, "--", str(movie.path)]


def launch(movie: Movie, data_dir: Path, log_dir: Path, start: float = 0, popen=subprocess.Popen,
           which: Callable[[str], str | None] = shutil.which,
           languages: tuple[str, ...] = ("en", "de")) -> tuple[bool, str]:
    if not available(which):
        return False, "The movie player (mpv) isn't installed - run ./install.sh again"
    if not movie.path.exists():
        return False, "The movie file is gone"
    from gamingcrypt.emulation.retroarch import reaper

    sock = socket_path()
    sock.parent.mkdir(parents=True, exist_ok=True)
    sock.unlink(missing_ok=True)  # from a player that's gone
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_dir / LOG_NAME, "wb") as log:
            popen(command(movie, reaper(data_dir), sock, input_conf(data_dir), start, languages),
                  stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                  env=dict(os.environ))
    except OSError as exc:
        return False, f"The player didn't start: {exc}"
    return True, f"Playing {movie.title}"


def query(sock: Path, prop: str, timeout: float = 1.0):
    """A property of the running player (None: no player, or it doesn't know yet)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(sock))
            conn.sendall(json.dumps({"command": ["get_property", prop], "request_id": 1}).encode() + b"\n")
            buffer = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    return None
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        reply = json.loads(line)
                    except ValueError:
                        continue
                    if reply.get("request_id") == 1:  # the rest are mpv's events
                        return reply.get("data") if reply.get("error") == "success" else None
    except OSError:
        return None


def position(sock: Path) -> tuple[float, float] | None:
    """(seconds in, length) of the running movie."""
    now, length = query(sock, "time-pos"), query(sock, "duration")
    if not isinstance(now, (int, float)):
        return None
    return float(now), float(length) if isinstance(length, (int, float)) else 0.0


# --- the controller, read by GamingCrypt while a movie is in front ------------------------

def _codes():
    from gamingcrypt.input import evdev as e

    buttons = {e.BTN_SOUTH: "osd-msg cycle pause", e.BTN_START: "osd-msg cycle pause", e.BTN_EAST: "quit",
               e.BTN_NORTH: "osd-msg cycle sub", e.BTN_WEST: "osd-msg cycle audio",  # X, Y (xpad layout)
               e.BTN_SELECT: "show-progress", e.BTN_TL: "osd-msg-bar add chapter -1",
               e.BTN_TR: "osd-msg-bar add chapter 1"}
    hats = {(e.ABS_HAT0X, -1): "osd-msg-bar seek -10", (e.ABS_HAT0X, 1): "osd-msg-bar seek 30",
            (e.ABS_HAT0Y, -1): "osd-msg-bar seek 300", (e.ABS_HAT0Y, 1): "osd-msg-bar seek -300"}
    return e, buttons, hats


def remote_command(ev_type: int, code: int, value: int) -> str | None:
    """A controller event -> the mpv command for it (None: nothing to do)."""
    e, buttons, hats = _codes()
    if ev_type == e.EV_KEY and value == 1:
        return buttons.get(code)
    if ev_type == e.EV_ABS and value:
        return hats.get((code, value))
    return None


def send(sock: Path, text: str, timeout: float = 1.0) -> bool:
    """One command to the running player, as a line like in input.conf."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(str(sock))
            conn.sendall(text.encode() + b"\n")
        return True
    except OSError:
        return False

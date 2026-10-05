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
# Controller (mpv reads it through SDL) and touch. The keyboard keeps mpv's own keys.
INPUT_CONF = """\
GAMEPAD_ACTION_DOWN cycle pause
GAMEPAD_START cycle pause
GAMEPAD_ACTION_RIGHT quit
GAMEPAD_BACK show-progress
GAMEPAD_DPAD_LEFT seek -10
GAMEPAD_DPAD_RIGHT seek 30
GAMEPAD_DPAD_UP seek 300
GAMEPAD_DPAD_DOWN seek -300
GAMEPAD_LEFT_SHOULDER add chapter -1
GAMEPAD_RIGHT_SHOULDER add chapter 1
GAMEPAD_ACTION_LEFT cycle sub
GAMEPAD_ACTION_UP cycle audio
MBTN_LEFT cycle pause
MBTN_LEFT_DBL ignore
"""
CONTROLS = ("A / Start: pause · B: stop · ◀ ▶: 10 s back / 30 s on · ▲ ▼: 5 min · LB / RB: chapter · "
            "X: subtitles · Y: audio language · tap: pause")


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
            "--hwdec=auto-safe", "--input-gamepad=yes", f"--input-conf={conf}", f"--input-ipc-server={sock}",
            "--save-position-on-quit=no", f"--title={movie.title}", f"--alang={','.join(languages)}",
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

"""What starts a Linux game: the program itself, or Steam's runtime around it (the libraries of
Steam's Linux games - for older games that miss them on a current system)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.linux.library import LinuxGame, make_startable


@dataclass(frozen=True)
class Runner:
    id: str
    label: str
    prefix: tuple[str, ...] = field(default=())  # put before the start file


DIRECT = Runner("direct", "Directly")


def available(home: Path | None = None) -> list[Runner]:
    from gamingcrypt.wine.runners import steam_roots

    home = home or Path.home()
    found = [DIRECT]
    for root in steam_roots(home):
        script = root / "ubuntu12_32" / "steam-runtime" / "run.sh"
        if script.is_file():
            found.append(Runner("steam-runtime", "Steam Runtime (for older games)", (str(script),)))
            break
    return found


def pick(runners: list[Runner], wanted: str | None) -> Runner:
    return next((r for r in runners if r.id == wanted), DIRECT)


def command(runner: Runner, game: LinuxGame, exe: str) -> tuple[list[str], Path]:
    target = game.path / exe
    return [*runner.prefix, str(target)], target.parent


def launch(game: LinuxGame, exe: str, runner: Runner, data_dir: Path, log_dir: Path, popen=subprocess.Popen,
           more_env: dict[str, str] | None = None) -> tuple[bool, str]:
    """Start it like a Steam game (the "reaper" wrapper: gamescope, quick menu, Force quit)."""
    from gamingcrypt.emulation.retroarch import reaper

    if not (game.path / exe).is_file():
        return False, f"{exe} isn't in the game's folder any more - pick the start file in Options"
    make_startable(game)
    args, cwd = command(runner, game, exe)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_dir / "linux.log", "wb") as log:
            popen([str(reaper(data_dir)), "SteamLaunch", f"AppId={game.appid}", "--", *args],
                  cwd=str(cwd), env={**os.environ, **(more_env or {})}, stdin=subprocess.DEVNULL, stdout=log,
                  stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        return False, f"It didn't start: {exc}"
    return True, f"Starting {game.name}…"

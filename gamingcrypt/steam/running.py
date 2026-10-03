"""Which Steam games are running right now, and whether they already draw.

On Linux Steam starts every game through its ``reaper`` process with
``SteamLaunch AppId=<id>`` on the command line, so /proc tells us reliably.
A game is about to show its window once one of its processes opened the GPU
(``/dev/dri/*`` or ``/dev/nvidia*``) - that works on X11 and Wayland alike.
"""

from __future__ import annotations

import os
from pathlib import Path

GPU_PREFIXES = ("/dev/dri/", "/dev/nvidia")


def _launchers(proc: Path) -> dict[int, int]:
    """pid of each Steam launcher (reaper) -> appid."""
    found: dict[int, int] = {}
    for cmdline in proc.glob("[0-9]*/cmdline"):
        try:
            args = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue  # process ended / not ours
        if b"SteamLaunch" not in args:
            continue
        for arg in args:
            if arg.startswith(b"AppId="):
                try:
                    found[int(cmdline.parent.name)] = int(arg[6:])
                except ValueError:
                    pass
    return found


def running_appids(proc: Path = Path("/proc")) -> set[int]:
    return set(_launchers(proc).values())


def _parents(proc: Path) -> dict[int, int]:
    parents = {}
    for stat in proc.glob("[0-9]*/stat"):
        try:
            text = stat.read_text()
            # "pid (comm with spaces) S ppid ..." - comm may contain ')'
            ppid = int(text[text.rindex(")") + 2:].split()[1])
            parents[int(stat.parent.name)] = ppid
        except (OSError, ValueError, IndexError):
            continue
    return parents


def game_processes(appid: int, proc: Path = Path("/proc")) -> set[int]:
    """The launcher of ``appid`` and everything it started."""
    roots = {pid for pid, app in _launchers(proc).items() if app == appid}
    if not roots:
        return set()
    children: dict[int, list[int]] = {}
    for pid, ppid in _parents(proc).items():
        children.setdefault(ppid, []).append(pid)
    result, todo = set(), list(roots)
    while todo:
        pid = todo.pop()
        if pid in result:
            continue
        result.add(pid)
        todo.extend(children.get(pid, []))
    return result


def uses_gpu(pids: set[int], proc: Path = Path("/proc")) -> bool:
    for pid in pids:
        try:
            fds = list((proc / str(pid) / "fd").iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith(GPU_PREFIXES):
                return True
    return False


RUNTIME_NAMES = {"pressure-vessel-wrap", "pressure-vessel-adverb", "pv-bwrap", "srt-bwrap",
                 "steam-runtime-launcher-service", "steam-runtime-launch-client"}
PROTON_NAMES = {"wineserver", "wine", "wine64", "wine-preloader", "wine64-preloader", "proton"}
SHADER_NAMES = {"fossilize_replay"}


def process_names(pids: set[int] | None, proc: Path = Path("/proc")) -> set[str]:
    """Short names (comm and argv[0] basename) of ``pids`` (all processes if None)."""
    names: set[str] = set()
    paths = [proc / str(p) for p in pids] if pids is not None else list(proc.glob("[0-9]*"))
    for path in paths:
        try:
            names.add((path / "comm").read_text().strip())
            argv0 = (path / "cmdline").read_bytes().split(b"\0", 1)[0].decode(errors="replace")
        except OSError:
            continue
        if argv0:
            names.add(argv0.replace("\\", "/").rsplit("/", 1)[-1])
    return names


def launch_phase(appid: int, root: Path | None = None, name: str = "the game",
                 proc: Path = Path("/proc"), progress=None) -> str:
    """Human readable "what is happening right now" while a game starts."""
    if progress is not None:
        p = progress(appid)
        if p.state == "downloading" and p.total:
            return f"Updating {name}… {p.percent:.0f}%"
    pids = game_processes(appid, proc)
    if not pids:
        everything = process_names(None, proc)
        if "steam" not in everything:
            return "Starting Steam…"
        if everything & SHADER_NAMES:
            return "Compiling shaders…"
        return f"Steam is preparing {name}…"
    names = process_names(pids, proc)
    if names & SHADER_NAMES:
        return "Compiling shaders…"
    if any(n.lower().endswith(".exe") for n in names):
        return f"Loading {name}…"
    if names & PROTON_NAMES or any(n.startswith("wine") for n in names):
        return "Starting Proton…"
    if names & RUNTIME_NAMES:
        return "Starting the Steam Linux Runtime…"
    return f"Starting {name}…"

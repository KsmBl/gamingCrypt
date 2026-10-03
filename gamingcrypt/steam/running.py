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

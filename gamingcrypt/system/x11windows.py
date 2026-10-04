"""Titles of the open X11 windows (Steam is an X11 app, also under gamescope).

Under gamescope its root property GAMESCOPE_FOCUSABLE_WINDOWS lists the app
windows as (window, app id, pid) triples; on a normal desktop the window manager
keeps _NET_CLIENT_LIST. Titles come from ``xprop -id``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]


def _xprop(args: list[str], runner: Runner) -> str:
    try:
        result = runner(["xprop", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def available(which: Callable[[str], str | None] = shutil.which) -> bool:
    return which("xprop") is not None


def window_ids(runner: Runner = subprocess.run) -> list[int]:
    root = _xprop(["-root", "GAMESCOPE_FOCUSABLE_WINDOWS", "_NET_CLIENT_LIST"], runner)
    for line in root.splitlines():
        if line.startswith("GAMESCOPE_FOCUSABLE_WINDOWS") and "=" in line:
            numbers = [int(n) for n in re.findall(r"\d+", line.split("=", 1)[1])]
            return list(dict.fromkeys(numbers[0::3]))  # (window, app id, pid) triples
    for line in root.splitlines():
        if line.startswith("_NET_CLIENT_LIST") and "#" in line:
            return [int(h, 16) for h in re.findall(r"0x[0-9a-fA-F]+", line)]
    return []


def window_titles(runner: Runner = subprocess.run) -> list[str]:
    titles = []
    for wid in window_ids(runner):
        out = _xprop(["-id", str(wid), "_NET_WM_NAME", "WM_NAME"], runner)
        match = re.search(r'= "(.*)"', out)
        if match:
            titles.append(match.group(1))
    return titles


def big_picture_open(runner: Runner = subprocess.run) -> bool:
    return any("big picture" in t.lower() for t in window_titles(runner))

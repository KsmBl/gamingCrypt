"""Upscaling: a game renders at a lower resolution and gamescope scales it up to the screen with
AMD's FSR (a sharpening upscaler - no AI, nearly free on any GPU). Fewer pixels: more FPS, or
less power with an FPS limit.

The game runs in a gamescope of its own ("nested", inside the session's): only that game is
smaller - GamingCrypt and the quick menu stay at the screen's size. The session's Vulkan layer
must not hook the nested gamescope's own window (it showed "Gamescope WSI Layer Error" on the
handheld); it sets up its own for the game.
"""

from __future__ import annotations

import shutil
from typing import Callable

# percent of the screen's width and height -> intensity
LEVELS = {85: "Light", 75: "Medium", 60: "Strong", 50: "Maximum"}
FILTER = "fsr"


def render_size(screen: tuple[int, int], percent: int) -> tuple[int, int]:
    """The game's resolution (even numbers - video encoders and some games want them)."""
    width, height = screen
    return max(2, round(width * percent / 200) * 2), max(2, round(height * percent / 200) * 2)


def describe(percent: int | None, screen: tuple[int, int]) -> str:
    if not percent or percent not in LEVELS:
        return "Off - full resolution"
    w, h = render_size(screen, percent)
    return f"{LEVELS[percent]} - {percent}% ({w}×{h})"


def command(percent: int | None, screen: tuple[int, int], fps: int = 0,
            which: Callable[[str], str | None] | None = None) -> list[str]:
    """What goes before the game's command: a nested gamescope that renders it smaller and
    scales it up ([] when off, or without gamescope)."""
    program = (which or shutil.which)("gamescope") if percent in LEVELS else None
    if program is None:
        return []
    w, h = render_size(screen, percent)
    args = ["env", "-u", "GAMESCOPE_WAYLAND_DISPLAY", "ENABLE_GAMESCOPE_WSI=0", program,
            "-w", str(w), "-h", str(h), "-W", str(screen[0]), "-H", str(screen[1]), "-F", FILTER, "-f"]
    if fps:
        args += ["-r", str(fps)]  # the game's frame limit inside, too: it renders no frames for nothing
    return [*args, "--"]

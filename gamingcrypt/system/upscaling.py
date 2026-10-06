"""Upscaling: a game renders at a lower resolution and gamescope scales it up to the screen with
AMD's FSR (a sharpening upscaler - no AI). Fewer pixels: more FPS, or less power with an FPS limit.

As Steam does it on the Deck: the game starts on gamescope's second X server (the gaming session
runs two), which offers it the smaller size (GAMESCOPE_XWAYLAND_MODE_CONTROL); gamescope's
scaling filter is FSR while it's on screen. GamingCrypt stays on the first server at full size.
Both are put back when the game ends.

(The first way - a gamescope of its own around the game - counted ~120 FPS, ignored the FPS
limit and cost more GPU on the handheld.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gamingcrypt.system import gamescope_ctl

# percent of the screen's width and height -> intensity
LEVELS = {85: "Light", 75: "Medium", 60: "Strong", 50: "Maximum"}
SERVER = 1  # gamescope's second X server
DISPLAY = ":1"
X11_DIR = Path("/tmp/.X11-unix")


def render_size(screen: tuple[int, int], percent: int) -> tuple[int, int]:
    """The game's resolution (even numbers - video encoders and some games want them)."""
    width, height = screen
    return max(2, round(width * percent / 200) * 2), max(2, round(height * percent / 200) * 2)


def describe(percent: int | None, screen: tuple[int, int]) -> str:
    if not percent or percent not in LEVELS:
        return "Off - full resolution"
    w, h = render_size(screen, percent)
    return f"{LEVELS[percent]} - {percent}% ({w}×{h})"


def available(x11_dir: Path = X11_DIR) -> bool:
    """The second X server is there (the gaming session starts gamescope with two)."""
    return (Path(x11_dir) / f"X{DISPLAY.lstrip(':')}").exists()


def start(percent: int | None, screen: tuple[int, int], runner=subprocess.run,
          x11_dir: Path = X11_DIR) -> dict[str, str]:
    """Ready the second server at the smaller size, FSR on: the game's environment ({} when off)."""
    if percent not in LEVELS or not available(x11_dir):
        return {}
    w, h = render_size(screen, percent)
    if not gamescope_ctl.set_xwayland_mode(SERVER, w, h, runner):
        return {}
    gamescope_ctl.set_scaling_filter(gamescope_ctl.FILTER_FSR, runner)
    return {"DISPLAY": DISPLAY}


def stop(screen: tuple[int, int], runner=subprocess.run) -> None:
    """The second server at the screen's size again, the usual scaling."""
    gamescope_ctl.set_xwayland_mode(SERVER, *screen, runner)
    gamescope_ctl.set_scaling_filter(gamescope_ctl.FILTER_LINEAR, runner)

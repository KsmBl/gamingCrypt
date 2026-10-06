"""Runtime controls of the running gamescope (X11 root window properties).

GAMESCOPE_DYNAMIC_REFRESH changes the refresh rate of the internal screen
without restarting gamescope (so a running game keeps running). Whether a rate
is possible depends on the panel - hence the keep/revert question in the UI.

Which app gamescope shows is steered like Steam does it on the Steam Deck: every
window carries an app id (STEAM_GAME; games launched by Steam get theirs from
gamescope), and GAMESCOPECTRL_BASELAYER_APPID on the root lists the app ids in
the order they should be on screen. GamingCrypt gives itself its own id and puts
it first - so Steam's Big Picture never pops up in front of it by itself.
"""

from __future__ import annotations

import re
import subprocess
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
DYNAMIC_REFRESH = "GAMESCOPE_DYNAMIC_REFRESH"
FOCUS_ORDER = "GAMESCOPECTRL_BASELAYER_APPID"
FPS_LIMIT = "GAMESCOPE_FPS_LIMIT"
TOUCH_MODE = "STEAM_TOUCH_CLICK_MODE"  # how gamescope hands on touches (Steam sets it the same way)
TOUCH_PASSTHROUGH = 4  # real touches (Qt: GamingCrypt; the session's --default-touch-mode)
TOUCH_LEFT_CLICK = 1  # touches as left clicks at the finger (the movie player can't read touches)
SCREENSHOT = "GAMESCOPECTRL_REQUEST_SCREENSHOT"
SCREENSHOT_FILE = "/tmp/gamescope.png"  # where gamescope writes it
FULL_COMPOSITION = 2  # what's on screen, overlays included
WINDOW_APPID = "STEAM_GAME"
BIG_PICTURE_APPID = 769  # Steam's own UI windows
LAUNCHER_APPID = 4293000000  # GamingCrypt's window - no real Steam app has this id


def _xprop(args: list[str], runner: Runner) -> subprocess.CompletedProcess | None:
    try:
        return runner(["xprop", "-root", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None


def dynamic_refresh(runner: Runner = subprocess.run) -> int:
    """Current dynamic refresh rate (0 = gamescope's default)."""
    result = _xprop([DYNAMIC_REFRESH], runner)
    if result is None or result.returncode != 0:
        return 0
    match = re.search(r"=\s*(\d+)", result.stdout)
    return int(match.group(1)) if match else 0


def set_dynamic_refresh(hz: int, runner: Runner = subprocess.run) -> bool:
    if hz:
        args = ["-f", DYNAMIC_REFRESH, "32c", "-set", DYNAMIC_REFRESH, str(int(hz))]
    else:
        args = ["-remove", DYNAMIC_REFRESH]  # back to the default
    result = _xprop(args, runner)
    return result is not None and result.returncode == 0


def set_window_appid(window: int, appid: int = LAUNCHER_APPID, runner: Runner = subprocess.run) -> bool:
    try:
        result = runner(["xprop", "-id", str(int(window)), "-f", WINDOW_APPID, "32c",
                         "-set", WINDOW_APPID, str(int(appid))], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def set_external_overlay(window: int, runner: Runner = subprocess.run) -> bool:
    """Draw this window over the game (gamescope stretches it to the whole screen; the
    window is transparent but for what it shows)."""
    try:
        result = runner(["xprop", "-id", str(int(window)), "-f", "GAMESCOPE_EXTERNAL_OVERLAY", "32c", "-set",
                         "GAMESCOPE_EXTERNAL_OVERLAY", "1"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def set_focus_order(appids: list[int], runner: Runner = subprocess.run) -> bool:
    """App ids, most wanted on screen first. Empty = gamescope decides by itself."""
    appids = [int(a) for a in dict.fromkeys(appids) if a]
    if appids:
        value = ",".join(str(a) for a in appids)
        args = ["-f", FOCUS_ORDER, "32c", "-set", FOCUS_ORDER, value]
    else:
        args = ["-remove", FOCUS_ORDER]
    result = _xprop(args, runner)
    return result is not None and result.returncode == 0


def set_fps_limit(fps: int, runner: Runner = subprocess.run) -> bool:
    """Frame limit for the game on screen (0 = none).

    Through gamescope's control protocol, as Steam does it: gamescope (3.16) resets a limit set
    with the GAMESCOPE_FPS_LIMIT property every frame - games ran at 60 with "30" on the
    handheld. The property stays as the way for older gamescopes. On a fixed 60 Hz screen only
    rates that divide 60 limit anything (30, 20 …)."""
    try:
        ctl = runner(["gamescopectl", "debug_set_fps_limit", str(int(fps))], capture_output=True, text=True,
                     timeout=5)
        ok = ctl.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if fps:
        args = ["-f", FPS_LIMIT, "32c", "-set", FPS_LIMIT, str(int(fps))]
    else:
        args = ["-remove", FPS_LIMIT]
    result = _xprop(args, runner)
    return ok or (result is not None and result.returncode == 0)


# --- upscaling: a game on gamescope's second X server, at a lower resolution ------------------

XWAYLAND_MODE = "GAMESCOPE_XWAYLAND_MODE_CONTROL"  # server index, width, height, allow bigger than the screen
SCALING_FILTER = "GAMESCOPE_NEW_SCALING_FILTER"
FILTER_LINEAR, FILTER_FSR = 0, 2  # gamescope's GamescopeUpscaleFilter


def set_xwayland_mode(server: int, width: int, height: int, runner: Runner = subprocess.run) -> bool:
    """The size an X server of gamescope offers its windows (games render at it)."""
    value = f"{int(server)},{int(width)},{int(height)},0"
    result = _xprop(["-f", XWAYLAND_MODE, "32c", "-set", XWAYLAND_MODE, value], runner)
    return result is not None and result.returncode == 0


def set_scaling_filter(value: int, runner: Runner = subprocess.run) -> bool:
    """How gamescope scales a smaller game up to the screen (FILTER_FSR, FILTER_LINEAR)."""
    result = _xprop(["-f", SCALING_FILTER, "32c", "-set", SCALING_FILTER, str(int(value))], runner)
    return result is not None and result.returncode == 0


def set_touch_mode(mode: int, runner: Runner = subprocess.run) -> bool:
    result = _xprop(["-f", TOUCH_MODE, "32c", "-set", TOUCH_MODE, str(int(mode))], runner)
    return result is not None and result.returncode == 0


def request_screenshot(runner: Runner = subprocess.run) -> bool:
    """gamescope writes SCREENSHOT_FILE and removes the property when it's done."""
    args = ["-f", SCREENSHOT, "32c", "-set", SCREENSHOT, str(FULL_COMPOSITION)]
    result = _xprop(args, runner)
    return result is not None and result.returncode == 0


def screenshot_pending(runner: Runner = subprocess.run) -> bool:
    result = _xprop([SCREENSHOT], runner)
    return result is not None and result.returncode == 0 and "=" in result.stdout


# --- performance overlay (mangoapp, started by the gaming session with --mangoapp) ---------

OVERLAY_ON = "fps\nframetime\ncpu_stats\ncpu_temp\ngpu_stats\ngpu_temp\nram\nbattery\nposition=top-left\n"
OVERLAY_OFF = "no_display\n"


def overlay_config(env: dict | None = None):
    from gamingcrypt.session.mode import config_dir

    return config_dir(env) / "mangohud.conf"


def overlay_available(which=None) -> bool:
    import shutil

    return bool((which or shutil.which)("mangoapp"))


def overlay_shown(env: dict | None = None) -> bool:
    try:
        return "no_display" not in overlay_config(env).read_text()
    except OSError:
        return False


def set_overlay(shown: bool, env: dict | None = None) -> bool:
    """mangoapp watches its config file: the change shows at once."""
    path = overlay_config(env)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(OVERLAY_ON if shown else OVERLAY_OFF)
    except OSError:
        return False
    return True


def _wanted_file(env: dict | None = None):
    return overlay_config(env).with_name("overlay-wanted")


def overlay_wanted(env: dict | None = None) -> bool:
    """The quick menu's switch - shown only while a game is in front (apply_overlay)."""
    try:
        return _wanted_file(env).read_text().strip() == "1"
    except OSError:
        return overlay_shown(env)  # from before there was a switch: what was on screen


def set_overlay_wanted(on: bool, env: dict | None = None) -> bool:
    try:
        path = _wanted_file(env)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n" if on else "0\n")
    except OSError:
        return False
    return True


def apply_overlay(game_in_front: bool, env: dict | None = None) -> bool:
    """On screen only over a game - not over GamingCrypt's own pages."""
    shown = overlay_wanted(env) and game_in_front
    if shown == overlay_shown(env) and overlay_config(env).exists():
        return True
    return set_overlay(shown, env)

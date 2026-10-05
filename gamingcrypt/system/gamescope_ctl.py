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
    """Frame limit for the game on screen (0 = none)."""
    if fps:
        args = ["-f", FPS_LIMIT, "32c", "-set", FPS_LIMIT, str(int(fps))]
    else:
        args = ["-remove", FPS_LIMIT]
    result = _xprop(args, runner)
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

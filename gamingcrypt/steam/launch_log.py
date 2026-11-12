"""Why didn't a Steam game start? Steam writes what it does when it starts one into
``<steam root>/logs/console_log.txt``:

    [2026-11-12 20:01:02] GameAction [AppID 620, ActionID 3] : LaunchApp changed task to ProcessingInstallScript with ""
    [2026-11-12 20:01:02] GameAction [AppID 620, ActionID 3] : LaunchApp waiting for user response to ShowEula ""

The lines about the game since it was started are read and the last thing that explains it is
said in plain words (app.game_didnt_start, game_detail.game_session_ended). None: nothing found -
the formats are Steam's own and change now and then, so unknown lines are only ever skipped.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

TAIL_BYTES = 256 * 1024  # (the log grows for days: only its end is read)
SLACK_S = 3  # (Steam's clock and ours: the same, give or take the launch itself)
_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$")

WAITING = {  # "LaunchApp waiting for user response to X"
    "showeula": "Steam wants you to accept the game's license first - open Steam once in Desktop mode, "
                "accept it, then start the game again.",
    "showcdkey": "Steam wants to show you the game's CD key first - open Steam once in Desktop mode.",
    "showlaunchoption": "Steam asks how to start the game - choose a launch option once in Steam (Desktop mode).",
    "cloudconflict": "Steam found two different saves in the cloud - choose which one to keep in Steam "
                     "(Desktop mode).",
    "syncconflict": "Steam found two different saves in the cloud - choose which one to keep in Steam "
                    "(Desktop mode).",
}
KEYWORDS = (  # (in the game's lines, case ignored) -> what's said; the first that matches counts
    ("missing executable", "Steam can't find the game's start file - check its files in Steam "
                           "(Properties → Installed Files → Verify)."),
    ("invalid platform", "There's no version of the game for this system - choose a Proton version in its "
                         "⚙ Options."),
    ("already running", "Steam thinks the game is still running - close it in the quick menu, or restart "
                        "gaming mode."),
    ("disk space", "There isn't enough room on the games drive for it - Settings → Storage shows what takes "
                   "the room."),
    ("update required", "The game needs an update first - let Steam download it, then start it again."),
    ("updaterequired", "The game needs an update first - let Steam download it, then start it again."),
    ("content still encrypted", "The game isn't released yet - Steam unlocks it on its release day."),
    ("no subscription", "This Steam account doesn't own the game."),
    ("missing app", "Steam doesn't know the game on this account - is the right Steam account logged in?"),
)
_WAITING = re.compile(r"waiting for user response to\s+(\w+)", re.IGNORECASE)
_FAILED = re.compile(r'changed task to Failed with\s+"([^"]*)"', re.IGNORECASE)


def _when(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        return None


def lines_for(text: str, appid: int, since: float) -> list[str]:
    """The game's own lines, written since it was started (without the time)."""
    tag = f"[AppID {appid},"
    found = []
    for line in text.splitlines():
        match = _LINE.match(line)
        if match is None or tag not in line:
            continue
        when = _when(match.group(1))
        if when is not None and when >= since - SLACK_S:
            found.append(match.group(2))
    return found


def reason(lines: list[str]) -> str | None:
    """The last line that explains it, in plain words."""
    for line in reversed(lines):
        low = line.lower()
        waiting = _WAITING.search(line)
        if waiting is not None:
            what = waiting.group(1)
            return WAITING.get(what.lower(), f"Steam waits for an answer on its own screen ({what}) - open "
                                             "Steam once in Desktop mode.")
        for word, said in KEYWORDS:
            if word in low:
                return said
        failed = _FAILED.search(line)
        if failed is not None and failed.group(1).strip():
            return f"Steam says: {failed.group(1).strip()}"
    return None


def read_tail(path: Path, size: int | None = None) -> str:
    size = size or TAIL_BYTES
    try:
        with open(path, "rb") as log:
            log.seek(0, 2)
            end = log.tell()
            log.seek(max(0, end - size))
            return log.read().decode("utf-8", "replace")
    except OSError:
        return ""


def explain(steam_root, appid: int, since: float) -> str | None:
    """Why the game didn't start, as far as Steam's log tells - None: it doesn't."""
    if not steam_root:
        return None
    text = read_tail(Path(steam_root) / "logs" / "console_log.txt")
    return reason(lines_for(text, appid, since)) if text else None

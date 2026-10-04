"""Gaming mode (GamingCrypt on gamescope) <-> desktop mode, and gamescope display settings.

The session script ``gamingcrypt-session`` reads ``next-mode`` (in the runtime
dir, so a reboot never inherits a stale request) whenever gaming mode ends:
"desktop" starts the desktop session once, "gaming" (or nothing after a crash)
starts gaming mode again.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
GAMESCOPE_NAMES = ("gamescope", "gamescope-wl")
RESUME_MAX_AGE_S = 180
PENDING_MAX_AGE_S = 600


def _env(env: dict | None) -> dict:
    return os.environ if env is None else env


def state_dir(env: dict | None = None) -> Path:
    env = _env(env)
    base = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".local" / "state")
    return Path(base) / "gamingcrypt"


def runtime_dir(env: dict | None = None) -> Path:
    """Cleared on every boot (tmpfs) - for one-shot requests."""
    env = _env(env)
    base = env.get("XDG_RUNTIME_DIR")
    return Path(base) / "gamingcrypt" if base else state_dir(env) / "run"


def config_dir(env: dict | None = None) -> Path:
    env = _env(env)
    base = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".config")
    return Path(base) / "gamingcrypt"


def in_gaming_session(env: dict | None = None) -> bool:
    return _env(env).get("GAMINGCRYPT_SESSION") == "1"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def request_desktop_mode(env: dict | None = None) -> Path:
    return _write(runtime_dir(env) / "next-mode", "desktop\n")


def request_restart(env: dict | None = None) -> Path:
    """Gaming mode again (e.g. to apply new display settings)."""
    return _write(runtime_dir(env) / "next-mode", "gaming\n")


# --- skip the lock screen after our own restart ------------------------------------

def write_resume_token(env: dict | None = None) -> Path:
    path = _write(runtime_dir(env) / "resume", str(time.time()))
    path.chmod(0o600)
    return path


def consume_resume_token(env: dict | None = None, now: Callable[[], float] = time.time) -> bool:
    """True once, shortly after GamingCrypt restarted itself while unlocked."""
    path = runtime_dir(env) / "resume"
    try:
        created = float(path.read_text())
        path.unlink()
    except (OSError, ValueError):
        return False
    return 0 <= now() - created <= RESUME_MAX_AGE_S


# --- ending gamescope ----------------------------------------------------------------

def gamescope_pid(pid: int | None = None, proc: Path = Path("/proc")) -> int | None:
    """The gamescope GamingCrypt runs in (walking up the parent processes)."""
    pid = os.getpid() if pid is None else pid
    for _ in range(32):
        try:
            stat = (proc / str(pid) / "stat").read_text()
        except OSError:
            return None
        comm = stat[stat.index("(") + 1:stat.rindex(")")]
        if comm in GAMESCOPE_NAMES:
            return pid
        ppid = int(stat[stat.rindex(")") + 2:].split()[1])
        if ppid <= 1:
            return None
        pid = ppid
    return None


def end_gamescope(kill: Callable[[int, int], None] = os.kill, proc: Path = Path("/proc")) -> bool:
    """gamescope waits for *every* program started in it (Steam!) - end it directly."""
    pid = gamescope_pid(proc=proc)
    if pid is None:
        return False
    try:
        kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def leave_desktop(runner: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which) -> bool:
    """From the desktop back to gaming mode: end the desktop compositor (the session
    script then starts gaming mode again)."""
    for tool in ("tilewinmsg", "swaymsg"):
        if which(tool):
            try:
                if runner([tool, "exit"], capture_output=True, timeout=10).returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
    return False


# --- gamescope display settings ---------------------------------------------------------

DEFAULT_ARGS = "-f --xwayland-count 2 --default-touch-mode 4 --hide-cursor-delay 3000"
REFRESH_RATES = [40, 45, 50, 55, 60]


def args_file(env: dict | None = None) -> Path:
    return config_dir(env) / "gamescope-args"


def read_args(env: dict | None = None) -> str:
    try:
        text = args_file(env).read_text().strip()
    except OSError:
        text = ""
    return text or DEFAULT_ARGS


def parse_display(args: str) -> dict:
    """Render size (-w/-h) and refresh (-r) from gamescope arguments."""
    found: dict = {}
    for key, flag in (("width", r"(?:-w|--nested-width)"), ("height", r"(?:-h|--nested-height)"),
                      ("refresh", r"(?:-r|--nested-refresh)")):
        match = re.search(rf"(?:^|\s){flag}[ =](\d+)", args)
        if match:
            found[key] = int(match.group(1))
    return found


def with_display(args: str, width: int | None, height: int | None, refresh: int | None) -> str:
    """``args`` with our render size / refresh options replaced (None = gamescope default)."""
    tokens = args.split()
    out, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in ("-w", "-h", "-r", "--nested-width", "--nested-height", "--nested-refresh",
                     "--generate-drm-mode"):
            skip = True
            continue
        if re.match(r"--(nested-width|nested-height|nested-refresh|generate-drm-mode)=", token):
            continue
        out.append(token)
    if width and height:
        out += ["-w", str(width), "-h", str(height)]
    if refresh:
        # a matching screen mode is generated for the internal panel
        out += ["--generate-drm-mode", "fixed", "-r", str(refresh)]
    return " ".join(out)


def pending_file(env: dict | None = None) -> Path:
    return config_dir(env) / "gamescope-args.pending"


def apply_display(width: int | None, height: int | None, refresh: int | None,
                  env: dict | None = None, now: Callable[[], float] = time.time) -> str:
    """Write new options, remember the old ones until the user confirms."""
    current = args_file(env)
    previous = read_args(env) if current.exists() else ""
    new = with_display(read_args(env), width, height, refresh)
    _write(current.with_name("gamescope-args.previous"), previous)
    _write(pending_file(env), str(now()))
    _write(current, new + "\n")
    return new


def display_pending(env: dict | None = None, now: Callable[[], float] = time.time) -> bool:
    try:
        started = float(pending_file(env).read_text())
    except (OSError, ValueError):
        return False
    if now() - started > PENDING_MAX_AGE_S:
        confirm_display(env)  # leftover from long ago - don't ask anymore
        return False
    return True


def confirm_display(env: dict | None = None) -> None:
    for path in (pending_file(env), args_file(env).with_name("gamescope-args.previous")):
        try:
            path.unlink()
        except OSError:
            pass


def revert_display(env: dict | None = None) -> None:
    """Back to the options from before the change."""
    current = args_file(env)
    previous = current.with_name("gamescope-args.previous")
    try:
        text = previous.read_text().strip()
    except OSError:
        text = None
    if text:
        _write(current, text + "\n")
    elif text is not None:
        try:
            current.unlink()  # there were no own options before
        except OSError:
            pass
    confirm_display(env)


def actual_mode(env: dict | None = None) -> str | None:
    """What gamescope really chose, from its log (e.g. "800x1280@60Hz")."""
    try:
        text = (state_dir(env) / "session.log").read_text(errors="replace")
    except OSError:
        return None
    modes = re.findall(r"selecting mode (\d+x\d+@\d+Hz)", text)
    return modes[-1] if modes else None


def panel_size(sys_root: Path = Path("/sys")) -> tuple[int, int] | None:
    """Native size of the connected internal panel, landscape (gamescope rotates portrait panels)."""
    for status in sorted(sys_root.glob("class/drm/card*-eDP-*/status")) + \
            sorted(sys_root.glob("class/drm/card*-*/status")):
        try:
            if status.read_text().strip() != "connected":
                continue
            first = (status.parent / "modes").read_text().split()[0]
        except (OSError, IndexError):
            continue
        w, h = (int(v) for v in first.split("x"))
        return max(w, h), min(w, h)
    return None


def render_sizes(native: tuple[int, int]) -> list[tuple[int, int]]:
    """Native plus smaller sizes with the same aspect ratio."""
    w, h = native
    sizes = []
    for scale in (1.0, 0.9, 0.75, 0.6, 0.5):
        size = (int(w * scale) // 2 * 2, int(h * scale) // 2 * 2)
        if size not in sizes:
            sizes.append(size)
    return sizes

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "gamingcrypt" / "session" / "gamingcrypt-session"

FAKE_GAMESCOPE = """#!/bin/sh
n=$(cat "$FAKE_DIR/count" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$FAKE_DIR/count"
echo "gaming $GAMINGCRYPT_SESSION $QT_QPA_PLATFORM $XDG_CURRENT_DESKTOP | $*" >> "$FAKE_DIR/calls"
action=$(echo "$FAKE_ACTIONS" | cut -d, -f$n)
case "$action" in
  desktop) echo desktop > "$XDG_RUNTIME_DIR/gamingcrypt/next-mode"; exit 0 ;;
  crash) exit 1 ;;
  *) exit 0 ;;
esac
"""


def run_session(tmp_path, actions, extra_env=None, timeout=30):
    fake = tmp_path / "fake"
    fake.mkdir()
    gamescope = fake / "gamescope"
    gamescope.write_text(FAKE_GAMESCOPE)
    gamescope.chmod(gamescope.stat().st_mode | stat.S_IEXEC)
    env = dict(os.environ, HOME=str(tmp_path), XDG_STATE_HOME=str(tmp_path / "state"),
               XDG_RUNTIME_DIR=str(tmp_path / "run"),
               XDG_CONFIG_HOME=str(tmp_path / "config"), FAKE_DIR=str(fake), FAKE_ACTIONS=actions,
               GC_GAMESCOPE=str(gamescope), GC_LAUNCHER="/opt/gamingcrypt",
               GC_DESKTOP_EXEC=f'echo desktop >> "{fake}/calls"', GC_QUICK_EXIT_S="15")
    env.update(extra_env or {})
    result = subprocess.run(["sh", str(SCRIPT)], env=env, timeout=timeout, capture_output=True, text=True)
    calls = (fake / "calls").read_text().splitlines()
    return result.returncode, calls


def test_gaming_mode_runs_gamingcrypt_on_gamescope(tmp_path):
    code, calls = run_session(tmp_path, "exit0")
    assert code == 0 and len(calls) == 1
    assert calls[0].startswith("gaming 1 xcb gamescope | ")  # session flag + Qt on gamescope's Xwayland
    assert calls[0].endswith("-- /opt/gamingcrypt") and "--default-touch-mode 4" in calls[0]


def test_desktop_mode_and_back(tmp_path):
    code, calls = run_session(tmp_path, "desktop,exit0")
    assert code == 0
    assert [c.split(" ")[0] for c in calls] == ["gaming", "desktop", "gaming"]
    assert not (tmp_path / "run/gamingcrypt/next-mode").exists()  # one-shot


def test_crashing_gamingcrypt_is_restarted(tmp_path):
    code, calls = run_session(tmp_path, "crash,exit0", {"GC_QUICK_EXIT_S": "0"})
    assert [c.split(" ")[0] for c in calls] == ["gaming", "gaming"]


def test_falls_back_to_desktop_if_gaming_mode_cannot_start(tmp_path):
    """e.g. gamescope missing: never leave the user on a black screen."""
    code, calls = run_session(tmp_path, "crash,crash,crash,exit0")
    assert [c.split(" ")[0] for c in calls] == ["gaming", "gaming", "gaming", "desktop", "gaming"]
    assert "failed 3 times" in (tmp_path / "state/gamingcrypt/session.log").read_text()


def test_own_gamescope_options(tmp_path):
    conf = tmp_path / "config" / "gamingcrypt"
    conf.mkdir(parents=True)
    (conf / "gamescope-args").write_text("-f -W 1280 -H 800 -r 60\n")
    code, calls = run_session(tmp_path, "exit0")
    assert "| -f -W 1280 -H 800 -r 60 -- /opt/gamingcrypt" in calls[0]


def test_installed_files_are_templated():
    text = SCRIPT.read_text()
    assert "@LAUNCHER@" in text and "@DESKTOP_EXEC@" in text  # filled in by install.sh
    entry = (ROOT / "gamingcrypt/session/gamingcrypt.desktop").read_text()
    assert "Exec=/usr/local/bin/gamingcrypt-session" in entry


def test_install_script_offers_session():
    help_text = subprocess.run(["bash", str(ROOT / "install.sh"), "--help"], capture_output=True, text=True,
                               env=dict(os.environ, HOME="/nonexistent")).stdout
    assert "--session" in help_text and "set -euo" not in help_text


# --- python side ------------------------------------------------------------------

from gamingcrypt.session import mode  # noqa: E402


def test_mode_helpers(tmp_path):
    env = {"XDG_RUNTIME_DIR": str(tmp_path)}
    assert not mode.in_gaming_session({}) and mode.in_gaming_session({"GAMINGCRYPT_SESSION": "1"})
    path = mode.request_desktop_mode(env)
    # runtime dir: cleared on reboot, so a stale request can't send the next boot to the desktop
    assert path == tmp_path / "gamingcrypt" / "next-mode" and path.read_text().strip() == "desktop"
    assert mode.request_restart(env).read_text().strip() == "gaming"
    assert mode.state_dir({"HOME": "/home/x"}) == Path("/home/x/.local/state/gamingcrypt")
    assert mode.runtime_dir({"HOME": "/home/x"}) == Path("/home/x/.local/state/gamingcrypt/run")


def test_leave_desktop():
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0 if cmd[0] == "tilewinmsg" else 1)

    assert mode.leave_desktop(runner, which=lambda t: f"/usr/bin/{t}")
    assert calls == [["tilewinmsg", "exit"]]
    assert not mode.leave_desktop(runner, which=lambda t: None)


def test_desktop_mode_button(qtbot, monkeypatch, tmp_path):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.show()
    window.show_shell()
    closed = []
    monkeypatch.setattr(window, "close", lambda: closed.append(1))
    monkeypatch.delenv("GAMINGCRYPT_SESSION", raising=False)
    window.shell.power_menu.desktop_button.click()  # normal desktop: just quit
    assert closed == [1] and not (tmp_path / "gamingcrypt/next-mode").exists()
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(mode, "end_gamescope", lambda: False)  # not running inside gamescope here
    window.shell.power_menu.desktop_button.click()  # gaming session: switch to the desktop
    assert (tmp_path / "gamingcrypt/next-mode").read_text().strip() == "desktop"
    qtbot.waitUntil(lambda: closed == [1, 1])


def test_display_settings_left_to_gamescope():
    from gamingcrypt.system import display

    assert display.detect({"XDG_CURRENT_DESKTOP": "gamescope", "DISPLAY": ":1"}, lambda t: "/usr/bin/x") is None
    assert display.detect({"GAMESCOPE_WAYLAND_DISPLAY": "gamescope-0", "WAYLAND_DISPLAY": "w"},
                          lambda t: "/usr/bin/x") is None


def test_gaming_mode_cli(monkeypatch, tmp_path):
    from gamingcrypt import app

    monkeypatch.setattr(mode, "leave_desktop", lambda: True)
    assert app.main(["--config", str(tmp_path / "c.json"), "--gaming-mode"]) == 0
    monkeypatch.setattr(mode, "leave_desktop", lambda: False)
    assert app.main(["--config", str(tmp_path / "c.json"), "--gaming-mode"]) == 1

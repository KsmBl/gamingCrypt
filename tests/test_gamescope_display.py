import copy
import signal

import pytest

from gamingcrypt.session import mode
from tests.test_session import run_session


def env(tmp_path):
    return {"XDG_CONFIG_HOME": str(tmp_path / "config"), "XDG_RUNTIME_DIR": str(tmp_path / "run"),
            "XDG_STATE_HOME": str(tmp_path / "state"), "HOME": str(tmp_path)}


def test_parse_and_replace_display_options():
    args = "-f --xwayland-count 2 -w 960 -h 600 --generate-drm-mode fixed -r 50 --hide-cursor-delay 3000"
    assert mode.parse_display(args) == {"width": 960, "height": 600, "refresh": 50}
    assert mode.parse_display(mode.DEFAULT_ARGS) == {}
    new = mode.with_display(args, 1280, 800, None)
    assert mode.parse_display(new) == {"width": 1280, "height": 800}
    assert "--generate-drm-mode" not in new and "--xwayland-count 2" in new and "-f" in new.split()
    assert mode.with_display(args, None, None, 45).endswith("--generate-drm-mode fixed -r 45")


def test_apply_keep(tmp_path):
    e = env(tmp_path)
    mode.apply_display(960, 600, 50, e)
    assert mode.parse_display(mode.read_args(e)) == {"width": 960, "height": 600, "refresh": 50}
    assert mode.display_pending(e)
    mode.confirm_display(e)
    assert not mode.display_pending(e)
    assert mode.parse_display(mode.read_args(e))["refresh"] == 50  # kept


def test_apply_revert_to_defaults_and_to_previous(tmp_path):
    e = env(tmp_path)
    mode.apply_display(None, None, 40, e)
    mode.revert_display(e)
    assert not mode.args_file(e).exists() and mode.read_args(e) == mode.DEFAULT_ARGS
    mode.apply_display(960, 600, None, e)
    mode.confirm_display(e)
    mode.apply_display(None, None, 45, e)
    mode.revert_display(e)
    assert mode.parse_display(mode.read_args(e)) == {"width": 960, "height": 600}


def test_old_pending_change_is_dropped(tmp_path):
    e = env(tmp_path)
    mode.apply_display(None, None, 40, e, now=lambda: 1000.0)
    assert not mode.display_pending(e, now=lambda: 1000.0 + mode.PENDING_MAX_AGE_S + 1)


def test_actual_mode_and_panel(tmp_path):
    e = env(tmp_path)
    log = tmp_path / "state/gamingcrypt/session.log"
    log.parent.mkdir(parents=True)
    log.write_text("[gamescope] drm: selecting mode 800x1280@60Hz\n...\n[gamescope] drm: selecting mode 800x1280@50Hz\n")
    assert mode.actual_mode(e) == "800x1280@50Hz"
    drm = tmp_path / "sys/class/drm"
    for name, status, modes in (("card1-DP-1", "disconnected", ""), ("card1-eDP-1", "connected", "800x1280\n800x600\n")):
        (drm / name).mkdir(parents=True)
        (drm / name / "status").write_text(status + "\n")
        (drm / name / "modes").write_text(modes)
    assert mode.panel_size(tmp_path / "sys") == (1280, 800)  # portrait panel, gamescope shows it landscape
    assert mode.render_sizes((1280, 800))[:3] == [(1280, 800), (1152, 720), (960, 600)]


def test_resume_token(tmp_path):
    e = env(tmp_path)
    assert not mode.consume_resume_token(e)
    mode.write_resume_token(e)
    assert oct(mode.runtime_dir(e).joinpath("resume").stat().st_mode)[-3:] == "600"
    assert mode.consume_resume_token(e)
    assert not mode.consume_resume_token(e)  # only once
    mode.write_resume_token(e)
    import time

    assert not mode.consume_resume_token(e, now=lambda: time.time() + mode.RESUME_MAX_AGE_S + 5)


def test_find_and_end_gamescope(tmp_path):
    proc = tmp_path / "proc"
    for pid, ppid, comm in ((1, 0, "systemd"), (50, 1, "gamescope-wl"), (60, 50, "gamescopereaper"),
                            (70, 60, "python3")):
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1\n")
    assert mode.gamescope_pid(70, proc) == 50
    assert mode.gamescope_pid(1, proc) is None
    killed = []
    import os

    real = os.getpid
    os.getpid = lambda: 70
    try:
        assert mode.end_gamescope(lambda pid, sig: killed.append((pid, sig)), proc)
    finally:
        os.getpid = real
    assert killed == [(50, signal.SIGTERM)]


# --- session script ---------------------------------------------------------------------

def test_script_reverts_display_when_gamescope_cannot_start(tmp_path):
    conf = tmp_path / "config/gamingcrypt"
    conf.mkdir(parents=True)
    (conf / "gamescope-args").write_text("-f -r 30\n")
    (conf / "gamescope-args.previous").write_text("-f -r 60\n")
    (conf / "gamescope-args.pending").write_text("1")
    code, calls = run_session(tmp_path, "crash,exit0")
    assert calls[0].endswith("| -f -r 30 -- /opt/gamingcrypt")
    assert calls[1].endswith("| -f -r 60 -- /opt/gamingcrypt")  # reverted right away
    assert not (conf / "gamescope-args.pending").exists()
    assert "reverted" in (tmp_path / "state/gamingcrypt/session.log").read_text()


def test_script_restart_request_and_stale_old_request(tmp_path):
    old = tmp_path / "state/gamingcrypt/next-mode"
    old.parent.mkdir(parents=True)
    old.write_text("desktop\n")  # left over from before 0.5.2 - must not send us to the desktop
    code, calls = run_session(tmp_path, "exit0")
    assert [c.split(" ")[0] for c in calls] == ["gaming"]
    assert not old.exists()


# --- UI -------------------------------------------------------------------------------------

def test_confirm_dialog_counts_down_and_reverts(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui import display_confirm
    from gamingcrypt.ui.display_confirm import DisplayConfirm

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(800, 600)
    host.show()
    dialog = DisplayConfirm(host)
    events = []
    dialog.kept.connect(lambda: events.append("kept"))
    dialog.reverted.connect(lambda: events.append("reverted"))
    dialog.ask("Resolution native, refresh rate 40 Hz")
    assert dialog.countdown.text() == "Reverting in 15 s" and host.focusWidget() is dialog.revert_button
    for _ in range(display_confirm.SECONDS - 1):
        dialog.tick()
    assert events == [] and dialog.countdown.text() == "Reverting in 1 s"
    dialog.tick()
    assert events == ["reverted"] and not dialog.isVisible()
    dialog.ask("again")
    dialog.keep_button.click()
    assert events == ["reverted", "kept"]


def test_main_window_asks_after_display_change(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    mode.apply_display(960, 600, 45)
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.show()
    restarts = []
    monkeypatch.setattr(window, "restart_gaming_mode", lambda: restarts.append(1))
    window.check_display_change()
    assert window.display_confirm.isVisible()
    assert "960×600" in window.display_confirm.mode.text() and "45 Hz" in window.display_confirm.mode.text()
    assert window.nav_root() is window.display_confirm
    window.display_confirm.revert_button.click()
    assert restarts == [1] and not mode.display_pending()
    assert mode.parse_display(mode.read_args()) == {}


def test_no_question_outside_gaming_mode(qtbot):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    mode.apply_display(960, 600, 45)
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.check_display_change()
    assert getattr(window, "display_confirm", None) is None


def test_restart_skips_lock_screen_when_still_unlocked(qtbot, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.unlock.veracrypt import UnlockResult

    volume = tmp_path / "games.vc"
    volume.write_text("")
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method="pin", volume=str(volume))

    class Unlocker:
        configured = True

        def __init__(self, cfg, mounted=True):
            self.mounted = mounted

        def is_mounted(self):
            return self.mounted

        def unlock(self, secret):
            return UnlockResult(False)

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    mode.write_resume_token()
    window = MainWindow(copy.deepcopy(cfg), lambda c: None, Unlocker)
    qtbot.addWidget(window)
    assert window.screen_name == "shell"
    second = MainWindow(copy.deepcopy(cfg), lambda c: None, Unlocker)  # token used up
    qtbot.addWidget(second)
    assert second.screen_name == "lock"
    mode.write_resume_token()
    locked = MainWindow(copy.deepcopy(cfg), lambda c: None, lambda c: Unlocker(c, mounted=False))
    qtbot.addWidget(locked)
    assert locked.screen_name == "lock"  # drive no longer mounted -> lock screen


def test_settings_gamescope_controls(qtbot, monkeypatch):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system.controls import SystemControls
    from gamingcrypt.ui.settings_tab import SettingsTab

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(mode, "panel_size", lambda *a: (1280, 800))
    restarts = []
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, system=SystemControls(),
                      restart_gaming=lambda: restarts.append(1))
    qtbot.addWidget(tab)
    d = tab.display_section
    assert d.gs_resolution.currentText() == "1280×800 (native)" and d.gs_refresh.currentText() == "Default (screen)"
    d.gs_resolution.setCurrentIndex(d.gs_resolution.findData("960x600"))
    d.gs_refresh.setCurrentIndex(d.gs_refresh.findData(50))
    d.gs_apply.click()
    assert restarts == [1] and mode.display_pending()
    assert mode.parse_display(mode.read_args()) == {"width": 960, "height": 600, "refresh": 50}
    assert "15 s" in d.status.text()

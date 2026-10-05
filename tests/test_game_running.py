import copy
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import Qt

from gamingcrypt.steam.client import SteamClient
from gamingcrypt.steam.running import running_appids
from gamingcrypt.ui import game_watcher
from gamingcrypt.ui.game_watcher import GameWatcher


def fake_proc(tmp_path, processes):
    proc = tmp_path / "proc"
    for pid, args in processes.items():
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
    (proc / "self").mkdir(parents=True, exist_ok=True)
    return proc


def test_running_appids_from_proc(tmp_path):
    proc = fake_proc(tmp_path, {
        10: ["/home/me/.steam/steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=1145360", "--", "proton", "run"],
        11: ["/usr/bin/bash"],
        12: ["vim", "AppId=999"],  # not launched by Steam
        13: ["reaper", "SteamLaunch", "AppId=notanumber"],
    })
    assert running_appids(proc) == {1145360}


def test_running_appids_real_process():
    # two commands so sh doesn't exec() into sleep and keep its own (Steam-like) arguments
    process = subprocess.Popen(["sh", "-c", "sleep 30; true", "SteamLaunch", "AppId=4242"])
    try:
        time.sleep(0.1)
        assert 4242 in running_appids()
    finally:
        process.kill()
        process.wait()
    assert 4242 not in running_appids()


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Game:
    """Scripted game: processes appear, open the GPU, exit."""

    def __init__(self):
        self.pids: set[int] = set()
        self.drawing = False

    def processes(self, appid):
        return set(self.pids)

    def gpu(self, pids):
        return self.drawing


def watcher_for(game, clock):
    w = GameWatcher(processes=game.processes, gpu=game.gpu, clock=clock)
    events = []
    for name in ("started", "visible", "finished", "failed"):
        getattr(w, name).connect(lambda appid, n=name: events.append(n))
    return w, events


def test_watcher_phases(qtbot):
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    w.watch(620)
    w.poll()
    assert events == [] and w.phase == "launching"
    game.pids = {10, 11}
    w.poll()
    assert events == ["started"] and w.phase == "starting"  # process there, not drawing yet
    clock.now += 10
    w.poll()
    assert events == ["started"]  # still no window -> launcher stays (no desktop flash)
    game.drawing = True
    w.poll()
    assert events == ["started"]  # GPU just opened, give the window a moment
    clock.now += game_watcher.WINDOW_DELAY_S
    w.poll()
    assert events == ["started", "visible"] and w.phase == "playing"
    w.poll()
    assert events == ["started", "visible"]
    game.pids = set()
    w.poll()
    assert events == ["started", "visible", "finished"] and not w.active


def test_watcher_steps_aside_without_gpu_after_fallback():
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    w.watch(1)
    game.pids = {5}
    w.poll()
    clock.now += game_watcher.NO_GPU_FALLBACK_S
    w.poll()
    assert events == ["started", "visible"]


def test_watcher_game_exits_before_drawing():
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    w.watch(1)
    game.pids = {5}
    w.poll()
    game.pids = set()
    w.poll()
    assert events == ["started", "finished"]


def test_watcher_gives_up_if_game_never_starts():
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    w.watch(620)
    clock.now = game_watcher.LAUNCH_TIMEOUT_S + 1
    w.poll()
    assert events == ["failed"] and not w.active


# --- process tree / GPU ---------------------------------------------------------------

def fake_tree(tmp_path):
    proc = fake_proc(tmp_path, {
        100: ["reaper", "SteamLaunch", "AppId=1557740", "--", "wrapper"],
        101: ["steam-launch-wrapper"],
        102: ["Rounds.exe"],
        200: ["reaper", "SteamLaunch", "AppId=999"],
        300: ["firefox"],
    })
    for pid, ppid, comm in ((100, 1, "reaper"), (101, 100, "wrapper"), (102, 101, "Rounds (x) .exe"),
                            (200, 1, "reaper"), (300, 1, "firefox")):
        (proc / str(pid) / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1 0 -1\n")
        (proc / str(pid) / "fd").mkdir()
    return proc


def test_game_processes_whole_tree(tmp_path):
    from gamingcrypt.steam.running import game_processes

    proc = fake_tree(tmp_path)
    assert game_processes(1557740, proc) == {100, 101, 102}
    assert game_processes(999, proc) == {200}
    assert game_processes(5, proc) == set()


def test_uses_gpu(tmp_path):
    from gamingcrypt.steam.running import uses_gpu

    proc = fake_tree(tmp_path)
    (proc / "102/fd/3").symlink_to("/dev/null")
    assert not uses_gpu({100, 101, 102}, proc)
    (proc / "102/fd/7").symlink_to("/dev/dri/renderD128")
    assert uses_gpu({100, 101, 102}, proc)
    assert not uses_gpu({300}, proc)


def test_real_process_tree_and_gpu():
    from gamingcrypt.steam.running import game_processes, uses_gpu

    process = subprocess.Popen(["sh", "-c", "sleep 30; true", "SteamLaunch", "AppId=4243"])
    try:
        deadline = time.time() + 3
        while time.time() < deadline and len(game_processes(4243)) < 2:
            time.sleep(0.05)
        tree = game_processes(4243)
        assert process.pid in tree and len(tree) >= 2  # sh and its sleep child
        assert not uses_gpu(tree)
    finally:
        process.kill()
        process.wait()


def test_client_play_reports_launch():
    launched = []
    client = SteamClient(["steam"], launcher=lambda cmd, **kw: None)
    client.on_play = launched.append
    client.play(620)
    assert launched == [620]

    def broken(cmd, **kw):
        raise OSError("no steam")

    failing = SteamClient(["steam"], launcher=broken)
    failing.on_play = launched.append
    assert not failing.play(1) and launched == [620]


def test_service_hands_play_hook_to_client(tmp_path):
    from gamingcrypt.steam.service import SteamService

    svc = SteamService({"command": "steam"}, tmp_path)
    hook = lambda appid: None  # noqa: E731
    svc.on_game_launch = hook
    assert svc.client.on_play is hook


def make_window(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    service = FakeService()
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(service)})
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    window.show_shell()
    window.shell.pages["Games"].games.update({g.appid: g for g in service.games})
    calls = []
    monkeypatch.setattr(window, "step_aside", lambda *a: calls.append("aside"))
    monkeypatch.setattr(window, "bring_to_front", lambda: calls.append("back"))
    return window, service, calls


def test_launcher_waits_for_the_game_window_then_steps_aside(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    assert service.on_game_launch == window.game_launched
    game, clock = Game(), Clock()
    window.game_watcher.processes, window.game_watcher.gpu, window.game_watcher.clock = game.processes, game.gpu, clock
    window.game_launched(620)
    # stays visible with a "Starting …" screen - no desktop flash while Steam/Proton start
    assert calls == [] and window.launch_overlay.isVisible()
    assert window.launch_overlay.label.text() == "Starting Portal 2…"
    game.pids = {1}
    window.game_watcher.poll()
    assert calls == []
    game.drawing = True
    window.game_watcher.poll()
    clock.now += game_watcher.WINDOW_DELAY_S
    window.game_watcher.poll()
    assert calls == ["aside"]
    game.pids = set()
    window.game_watcher.poll()
    assert calls == ["aside", "back"] and not window.launch_overlay.isVisible()


def test_launcher_comes_back_if_game_never_starts(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    clock = Clock()
    window.game_watcher.processes, window.game_watcher.clock = (lambda appid: set()), clock
    window.game_launched(620)
    clock.now += game_watcher.LAUNCH_TIMEOUT_S + 1
    window.game_watcher.poll()
    assert calls == ["back"] and not window.launch_overlay.isVisible()


def test_back_button_on_overlay(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    window.game_watcher.processes = lambda appid: set()
    window.game_launched(400)
    assert window.launch_overlay.label.text() == "Starting Portal…"
    window.launch_overlay.back_button.click()
    assert not window.launch_overlay.isVisible() and not window.game_watcher.active


def test_step_aside_hides_and_comes_back_without_unminimising(qtbot):
    """Wayland: a minimised app can't restore itself - so hide and show a fresh window."""
    import copy as _copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    window = MainWindow(_copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    window.step_aside()
    assert window.isHidden()
    window.bring_to_front()
    assert window.isVisible() and not window.isMinimized()
    window.showMinimized()
    window.bring_to_front()
    assert window.isVisible() and not window.isMinimized()
    window.minimize_for_steam()
    assert window.isHidden()


def test_log_file(tmp_path):
    import logging

    from gamingcrypt.log import setup

    path = setup(tmp_path)
    logging.getLogger("gamingcrypt.games").info("app 620 started")
    for handler in logging.getLogger("gamingcrypt").handlers:
        handler.flush()
    assert "app 620 started" in path.read_text()
    logging.getLogger("gamingcrypt").handlers.clear()


def test_loading_screen_has_cover_and_spinner(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    window.game_watcher.processes = lambda appid: set()
    overlay = window.launch_overlay
    window.game_launched(620)
    assert overlay.isVisible() and overlay.spinner.timer.isActive()
    assert not overlay.cover.pixmap().isNull()
    before = overlay.spinner.angle
    qtbot.waitUntil(lambda: overlay.spinner.angle != before)  # it animates
    overlay.back_button.click()
    assert not overlay.spinner.timer.isActive()  # no animation in the background


def test_game_page_forgets_starting_message_after_the_game(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    games = window.shell.pages["Games"]
    games.open_game(620)
    page = games.currentWidget()
    game = Game()
    window.game_watcher.processes, window.game_watcher.gpu = game.processes, game.gpu
    service.client.play = lambda appid: window.game_launched(appid) or True
    page.main_button.click()
    assert page.status.text() == "Starting Portal 2…"
    game.pids = {1}
    window.game_watcher.poll()
    game.pids = set()
    window.game_watcher.poll()  # game exited
    assert page.status.text() == ""


def test_game_page_says_when_game_did_not_start(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    games = window.shell.pages["Games"]
    games.open_game(620)
    page = games.currentWidget()
    clock = Clock()
    window.game_watcher.processes, window.game_watcher.clock = (lambda appid: set()), clock
    service.client.play = lambda appid: window.game_launched(appid) or True
    page.main_button.click()
    clock.now += game_watcher.LAUNCH_TIMEOUT_S + 1
    window.game_watcher.poll()
    assert "didn't start" in page.status.text() and page.status.property("error")


def test_back_button_on_loading_screen_clears_message_and_other_games_untouched(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    games = window.shell.pages["Games"]
    games.open_game(620)
    page = games.currentWidget()
    window.game_watcher.processes = lambda appid: set()
    service.client.play = lambda appid: window.game_launched(appid) or True
    page.main_button.click()
    window.game_over(1145360)  # another game's end doesn't touch this page
    assert page.status.text() == "Starting Portal 2…"
    window.launch_overlay.back_button.click()
    assert page.status.text() == ""


def test_steps_aside_when_steam_waits_for_a_click(qtbot, monkeypatch):
    """E.g. a license agreement in a Steam window that would be hidden behind GamingCrypt."""
    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    window.game_launched(620)
    clock.now += game_watcher.STALL_S - 1
    w.poll()
    assert calls == []  # normal start-up time: stay
    clock.now += 2
    w.poll()
    assert calls == ["aside"]  # Steam's window is visible now
    w.poll()
    assert calls == ["aside"]  # only once
    game.pids = {1}  # user accepted, the game starts
    game.drawing = True
    w.poll()
    clock.now += game_watcher.WINDOW_DELAY_S
    w.poll()
    game.pids = set()
    w.poll()
    assert calls == ["aside", "aside", "back"]  # back after the game


def test_quick_starts_never_stall(qtbot, monkeypatch):
    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    window.game_launched(620)
    clock.now += 3
    game.pids = {1}
    w.poll()
    clock.now += game_watcher.STALL_S * 2  # game running but not drawing yet: no stall
    w.poll()
    assert calls == [] and w.stall_reported is False


def test_gamescope_focus_order(qtbot, monkeypatch):
    """Gaming mode: GamingCrypt first, the game while playing, Big Picture only on purpose."""
    import copy as _copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system import gamescope_ctl as gs

    calls = []
    monkeypatch.setattr(gs, "set_focus_order", lambda order: calls.append(order))
    monkeypatch.setattr(gs, "set_window_appid", lambda wid: calls.append("appid"))
    window = MainWindow(_copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    assert calls == []  # not in gaming mode: nothing to steer
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    window.hide()
    window.show()
    assert calls == ["appid", [gs.LAUNCHER_APPID]]
    window.game_watcher.appid = 620
    window.step_aside("game")
    assert calls[-1] == [620, gs.LAUNCHER_APPID]
    window.bring_to_front()  # e.g. the quick menu
    assert calls[-1] == [gs.LAUNCHER_APPID]
    window.big_picture_opened()
    assert calls[-1] == [gs.BIG_PICTURE_APPID, gs.LAUNCHER_APPID]
    window.big_picture.stop()
    window.minimize_for_steam()
    assert calls[-1] == []  # a Steam dialog: gamescope picks


def test_focus_order_xprop():
    import subprocess

    from gamingcrypt.system import gamescope_ctl as gs

    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert gs.set_focus_order([620, None, 620, gs.LAUNCHER_APPID], run)
    assert seen[-1][-1] == f"620,{gs.LAUNCHER_APPID}" and "-root" in seen[-1]
    assert gs.set_focus_order([], run) and seen[-1][-2:] == ["-remove", gs.FOCUS_ORDER]
    assert gs.set_window_appid(0x1200007, runner=run)
    assert seen[-1][:3] == ["xprop", "-id", str(0x1200007)] and seen[-1][-1] == str(gs.LAUNCHER_APPID)


def test_no_cursor_in_gaming_mode(qtbot, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from gamingcrypt.app import hide_cursor_in_gaming_mode

    app = QApplication.instance()
    assert not hide_cursor_in_gaming_mode(app)
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    try:
        assert hide_cursor_in_gaming_mode(app)
        assert app.overrideCursor().shape() == Qt.CursorShape.BlankCursor
    finally:
        app.restoreOverrideCursor()

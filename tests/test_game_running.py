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


def test_watcher_started_then_finished(qtbot, monkeypatch):
    monkeypatch.setattr(game_watcher, "POLL_MS", 10)
    running = set()
    watcher = GameWatcher(running=lambda: running)
    events = []
    watcher.started.connect(lambda a: events.append(("started", a)))
    watcher.finished.connect(lambda a: events.append(("finished", a)))
    watcher.watch(620)
    watcher.poll()
    assert events == [] and watcher.active  # still launching
    running.add(620)
    qtbot.waitUntil(lambda: events == [("started", 620)])
    running.clear()
    qtbot.waitUntil(lambda: events[-1] == ("finished", 620))
    assert not watcher.active


def test_watcher_gives_up_if_game_never_starts(qtbot):
    clock = Clock()
    watcher = GameWatcher(running=set, clock=clock)
    failed = []
    watcher.failed.connect(failed.append)
    watcher.watch(620)
    watcher.poll()
    assert failed == []
    clock.now = game_watcher.LAUNCH_TIMEOUT_S + 1
    watcher.poll()
    assert failed == [620] and not watcher.active


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


def test_launcher_steps_aside_while_game_runs(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(game_watcher, "POLL_MS", 10)
    service = FakeService()
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(service)})
    qtbot.addWidget(window)
    window.windowed = True
    window.show()
    window.show_shell()
    assert service.on_game_launch == window.game_launched
    # The headless test platform has no window manager, so check what GamingCrypt asks for.
    calls = []
    monkeypatch.setattr(window, "showMinimized", lambda: calls.append("minimize"))
    monkeypatch.setattr(window, "bring_to_front", lambda: calls.append("restore"))
    running = set()
    window.game_watcher.running = lambda: running
    window.game_launched(620)
    assert calls == ["minimize"]  # the game is on top, windowed or not
    running.add(620)
    qtbot.waitUntil(lambda: window.game_watcher.seen)
    window.game_watcher.poll()
    assert calls == ["minimize"]  # stays out of the way while playing
    running.clear()
    qtbot.waitUntil(lambda: calls == ["minimize", "restore"])  # back after the game
    assert not window.game_watcher.active


def test_launcher_comes_back_if_game_never_starts(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(window, "showMinimized", lambda: calls.append("minimize"))
    monkeypatch.setattr(window, "bring_to_front", lambda: calls.append("restore"))
    clock = Clock()
    window.game_watcher.running = set
    window.game_watcher.clock = clock
    window.game_launched(620)
    clock.now += game_watcher.LAUNCH_TIMEOUT_S + 1
    window.game_watcher.poll()
    assert calls == ["minimize", "restore"]

import os
import shutil
import subprocess
import time

from gamingcrypt.steam.installer import InstallProgress
from gamingcrypt.steam.running import launch_phase, process_names


def proc_tree(tmp_path, processes):
    """processes: pid -> (ppid, comm, argv)"""
    proc = tmp_path / "proc"
    for pid, (ppid, comm, argv) in processes.items():
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "comm").write_text(comm + "\n")
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1\n")
    return proc


STEAM = {1: (0, "steam", ["/home/u/.steam/steam/ubuntu12_32/steam"])}
REAPER = {10: (1, "reaper", ["reaper", "SteamLaunch", "AppId=42", "--", "x"])}


def test_starting_steam(tmp_path):
    assert launch_phase(42, proc=proc_tree(tmp_path, {})) == "Starting Steam…"


def test_preparing_and_shaders(tmp_path):
    assert launch_phase(42, name="ROUNDS", proc=proc_tree(tmp_path / "a", STEAM)) == "Steam is preparing ROUNDS…"
    proc = proc_tree(tmp_path / "b", {**STEAM, 5: (1, "fossilize_repla", ["/x/fossilize_replay", "--a"])})
    assert launch_phase(42, proc=proc) == "Compiling shaders…"


def test_update_before_start(tmp_path):
    progress = lambda appid: InstallProgress("downloading", 340, 1000)  # noqa: E731
    assert launch_phase(42, name="ROUNDS", proc=proc_tree(tmp_path, STEAM), progress=progress) == \
        "Updating ROUNDS… 34%"


def test_phases_inside_the_game_tree(tmp_path):
    base = {**STEAM, **REAPER}
    runtime = {**base, 11: (10, "pv-bwrap", ["/x/pv-bwrap"])}
    assert launch_phase(42, proc=proc_tree(tmp_path / "r", runtime)) == "Starting the Steam Linux Runtime…"
    proton = {**runtime, 12: (11, "wineserver", ["/x/wineserver"])}
    assert launch_phase(42, proc=proc_tree(tmp_path / "p", proton)) == "Starting Proton…"
    exe = {**proton, 13: (11, "Rounds.exe", ["Z:\\games\\ROUNDS\\Rounds.exe"])}
    assert launch_phase(42, name="ROUNDS", proc=proc_tree(tmp_path / "e", exe)) == "Loading ROUNDS…"
    native = {**base, 14: (10, "rounds", ["/games/rounds"])}
    assert launch_phase(42, name="ROUNDS", proc=proc_tree(tmp_path / "n", native)) == "Starting ROUNDS…"


def test_real_processes(tmp_path):
    """Processes named like Steam's are recognised in the real /proc."""
    sleep = shutil.which("sleep")
    fake = {}
    for name in ("steam", "fossilize_replay", "wineserver"):
        path = tmp_path / name
        shutil.copy(sleep, path)
        fake[name] = path
    procs = [subprocess.Popen([str(fake["steam"]), "30"])]
    try:
        time.sleep(0.1)
        assert launch_phase(424242) == "Steam is preparing the game…"
        procs.append(subprocess.Popen([str(fake["fossilize_replay"]), "30"]))
        time.sleep(0.1)
        assert launch_phase(424242) == "Compiling shaders…"
        procs.append(subprocess.Popen(["sh", "-c", f"{fake['wineserver']} 30; true", "SteamLaunch", "AppId=424242"]))
        time.sleep(0.2)
        assert launch_phase(424242) in ("Compiling shaders…", "Starting Proton…")
        procs[1].kill()
        procs[1].wait()
        assert launch_phase(424242) == "Starting Proton…"
        assert "wineserver" in process_names(None)
    finally:
        for p in procs:
            p.kill()
            p.wait()


def test_loading_screen_shows_phases(qtbot, monkeypatch):
    from tests.test_game_running import Clock, Game, make_window

    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    phases = iter(["Starting Steam…", "Compiling shaders…", "Starting Proton…"])
    window.game_launched(620)
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    w.describe = lambda appid: next(phases)
    overlay = window.launch_overlay
    assert overlay.phase.text() == "Asking Steam to start the game…"
    w.poll()
    assert overlay.phase.text() == "Starting Steam…"
    w.poll()
    assert overlay.phase.text() == "Compiling shaders…"
    game.pids = {1}
    game.drawing = True
    w.poll()
    assert overlay.phase.text() == "Almost there…"


def test_broken_phase_detection_never_breaks_launching(qtbot, monkeypatch):
    from tests.test_game_running import Clock, Game, make_window

    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    window.game_launched(620)
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock

    def boom(appid):
        raise RuntimeError("weird /proc")

    w.describe = boom
    game.pids = {1}
    w.poll()
    assert w.phase == "starting"

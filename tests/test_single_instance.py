import os
import subprocess
import sys
import time
from pathlib import Path

from gamingcrypt.app import acquire_instance_lock, wait_and_activate

ROOT = Path(__file__).resolve().parent.parent


def test_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "cache" / "instance.lock"
    first = acquire_instance_lock(path)
    assert first is not None and path.read_text().strip() == str(os.getpid())
    assert acquire_instance_lock(path) is None  # a second GamingCrypt is refused
    first.close()  # process ended -> lock is free again (also after a crash)
    again = acquire_instance_lock(path)
    assert again is not None
    again.close()


def test_wait_and_activate_retries_while_the_other_copy_starts(monkeypatch):
    import gamingcrypt.app as app

    answers = iter([False, False, True])
    monkeypatch.setattr(app, "activate_running_instance", lambda name: next(answers))
    sleeps = []
    assert wait_and_activate("x", timeout=5, sleep=sleeps.append)
    assert len(sleeps) == 2
    monkeypatch.setattr(app, "activate_running_instance", lambda name: False)
    assert not wait_and_activate("x", timeout=0, sleep=lambda s: None)


def test_real_simultaneous_starts_leave_exactly_one(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_CONFIG_HOME=str(tmp_path / "cfg"),
               XDG_CACHE_HOME=str(tmp_path / "cache"), HOME=str(tmp_path))
    procs = [subprocess.Popen([sys.executable, "-m", "gamingcrypt", "--windowed"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for _ in range(3)]
    try:
        deadline = time.time() + 15
        while time.time() < deadline and sum(p.poll() is None for p in procs) > 1:
            time.sleep(0.1)
        time.sleep(1)  # make sure nobody else is still "starting"
        running = [p for p in procs if p.poll() is None]
        assert len(running) == 1
        assert all(p.returncode == 0 for p in procs if p not in running)  # the others exited cleanly
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait()

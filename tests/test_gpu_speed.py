"""Per-game "Graphics: full speed" (fewer micro-stutters on AMD graphics)."""

import subprocess

import pytest

from gamingcrypt.helper import veracrypt_helper
from gamingcrypt.system import gpu_speed
from tests.test_game_profiles import window  # noqa: F401  (fixture)


def amd_gpu(root):
    level = root / "class/drm/card1/device/power_dpm_force_performance_level"
    level.parent.mkdir(parents=True)
    level.write_text("auto\n")
    return level


def test_helper_sets_full_and_auto(tmp_path):
    level = amd_gpu(tmp_path)
    assert veracrypt_helper.set_gpu_speed(["full"], sys_root=str(tmp_path)) == 0
    assert level.read_text() == "high"
    assert veracrypt_helper.set_gpu_speed(["auto"], sys_root=str(tmp_path)) == 0
    assert level.read_text() == "auto"


@pytest.mark.parametrize("args", [[], ["high"], ["manual"], ["full", "auto"], ["../x"]])
def test_helper_rejects_anything_else(tmp_path, args):
    level = amd_gpu(tmp_path)
    assert veracrypt_helper.set_gpu_speed(args, sys_root=str(tmp_path)) == 2
    assert level.read_text() == "auto\n"


def test_helper_without_amd_graphics(tmp_path):
    assert veracrypt_helper.set_gpu_speed(["full"], sys_root=str(tmp_path)) == 2


def test_helper_main_dispatches(monkeypatch):
    seen = []
    monkeypatch.setattr(veracrypt_helper, "set_gpu_speed", lambda args: seen.append(args) or 0)
    assert veracrypt_helper.main(["gpu-speed", "full"]) == 0 and seen == [["full"]]


def test_set_through_the_helper(tmp_path):
    helper = tmp_path / "helper"
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert gpu_speed.set_full(True, str(helper), run)[0] is False  # not installed
    helper.write_text("")
    assert gpu_speed.set_full(True, str(helper), run) == (True, "Graphics at full speed")
    assert gpu_speed.set_full(False, str(helper), run)[0]
    assert calls == [["sudo", "-n", str(helper), "gpu-speed", "full"], ["sudo", "-n", str(helper), "gpu-speed", "auto"]]
    old = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "Error: gamingcrypt helper: unknown")  # noqa: E731
    assert gpu_speed.set_full(True, str(helper), old) == (False, "unknown")


def test_available_only_with_amd_graphics(tmp_path):
    assert not gpu_speed.available(tmp_path)
    amd_gpu(tmp_path)
    assert gpu_speed.available(tmp_path)


def test_full_speed_while_the_game_runs(qtbot, window, monkeypatch):  # noqa: F811
    sets = []
    monkeypatch.setattr(gpu_speed, "available", lambda *a: True)
    monkeypatch.setattr(gpu_speed, "set_full", lambda full, *a, **k: sets.append(full) or (True, ""))
    window.game_profiles.set(620, gpu_speed.PROFILE_KEY, True)
    window.game_watcher.appid = 620
    window.game_watcher.started.emit(620)
    qtbot.waitUntil(lambda: sets == [True])
    window.game_watcher._stop()
    window.game_watcher.finished.emit(620)
    qtbot.waitUntil(lambda: sets == [True, False])


def test_other_games_leave_the_graphics_alone(qtbot, window, monkeypatch):  # noqa: F811
    sets = []
    monkeypatch.setattr(gpu_speed, "available", lambda *a: True)
    monkeypatch.setattr(gpu_speed, "set_full", lambda full, *a, **k: sets.append(full) or (True, ""))
    window.game_watcher.appid = 1
    window.game_watcher.started.emit(1)
    window.game_watcher._stop()
    window.game_watcher.finished.emit(1)
    qtbot.wait(100)
    assert sets == []


def test_option_on_the_game_page(qtbot, monkeypatch):
    from tests.test_proton import proton_page

    monkeypatch.setattr(gpu_speed, "available", lambda *a: True)
    page, _ = proton_page(qtbot)
    assert page.gpu_combo.currentData() is False
    page.gpu_combo.setCurrentIndex(1)
    assert page.profiles.get(620) == {gpu_speed.PROFILE_KEY: True}
    assert "full speed" in page.status.text()
    page.gpu_combo.setCurrentIndex(0)
    assert page.profiles.get(620) == {}


def test_no_option_without_amd_graphics(qtbot, monkeypatch):
    from tests.test_proton import proton_page

    monkeypatch.setattr(gpu_speed, "available", lambda *a: False)
    page, _ = proton_page(qtbot)
    assert page.gpu_combo is None

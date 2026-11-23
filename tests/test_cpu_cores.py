"""Per-game "CPU cores: quiet" (keep a Windows game off the busy first core) and the FPS limit
of 32-bit games, which gamescope can't hold."""

from pathlib import Path

from gamingcrypt.system import cpu_cores
from gamingcrypt.wine import runners


def cpus(root: Path, online: str, siblings: dict[int, str]) -> Path:
    base = root / "devices/system/cpu"
    base.mkdir(parents=True)
    (base / "online").write_text(online + "\n")
    for cpu, text in siblings.items():
        (base / f"cpu{cpu}/topology").mkdir(parents=True)
        (base / f"cpu{cpu}/topology/thread_siblings_list").write_text(text + "\n")
    return root


def test_hyperthreading_off_every_core_but_the_first(tmp_path):
    root = cpus(tmp_path, "0,2,4,6,8,10,12,14", {c: f"{c}-{c + 1}" for c in range(0, 16, 2)})
    assert cpu_cores.quiet_cpus(root) == [2, 4, 6, 8, 10, 12, 14]
    assert cpu_cores.topology(cpu_cores.quiet_cpus(root)) == "7:2,4,6,8,10,12,14"


def test_hyperthreading_on_one_thread_per_core(tmp_path):
    root = cpus(tmp_path, "0-15", {c: f"{c},{c + 8}" if c < 8 else f"{c - 8},{c}" for c in range(16)})
    assert cpu_cores.quiet_cpus(root) == [1, 2, 3, 4, 5, 6, 7]  # their siblings 9-15 (and 0, 8) for the rest


def test_too_few_cores_or_unknown(tmp_path):
    assert cpu_cores.quiet_cpus(cpus(tmp_path / "a", "0-3", {c: str(c) for c in range(4)})) == []
    assert not cpu_cores.available(tmp_path / "nothing")


def pe(path: Path, machine: int) -> Path:
    head = bytearray(512)
    head[:2] = b"MZ"
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    head[0x80:0x84] = b"PE\0\0"
    head[0x84:0x86] = machine.to_bytes(2, "little")
    path.write_bytes(bytes(head))
    return path


class Game:
    def __init__(self, path):
        self.path, self.appid, self.name = path, 1424274181, "GTA IV"


def test_quiet_cores_and_fps_limit_in_the_command(tmp_path, monkeypatch):
    monkeypatch.setattr(runners, "prefix_dir", lambda game, user="": tmp_path / "prefix")
    game = Game(tmp_path)
    pe(tmp_path / "GTAIV.exe", 0x14C)
    pe(tmp_path / "new.exe", 0x8664)
    proton = runners.Runner("proton:x", "Proton", "proton", tmp_path / "proton")
    tools = {"umu-run": "/usr/bin/umu-run", "taskset": "/usr/bin/taskset"}
    args, env, _ = runners.command(proton, game, "GTAIV.exe", tmp_path, tools.get, cpus=[2, 4, 6, 8], fps=40)
    assert args == ["/usr/bin/taskset", "-c", "2,4,6,8", "/usr/bin/umu-run", str(tmp_path / "GTAIV.exe")]
    assert env["WINE_CPU_TOPOLOGY"] == "4:2,4,6,8"
    assert env["DXVK_CONFIG"] == "d3d9.maxFrameRate = 40; dxgi.maxFrameRate = 40"  # 32-bit: gamescope can't
    args, env, _ = runners.command(proton, game, "new.exe", tmp_path, tools.get, fps=40)
    assert args == ["/usr/bin/umu-run", str(tmp_path / "new.exe")]  # all cores
    assert "WINE_CPU_TOPOLOGY" not in env and "DXVK_CONFIG" not in env  # 64-bit: gamescope holds it
    args, env, _ = runners.command(proton, game, "GTAIV.exe", tmp_path, tools.get)
    assert "DXVK_CONFIG" not in env  # no limit chosen


def test_cores_option_saved(qtbot, tmp_path):
    from gamingcrypt.game_profiles import GameProfiles
    from gamingcrypt.ui.cpu_option import cpu_combo

    profiles = GameProfiles(tmp_path / "profiles.json")
    root = cpus(tmp_path / "sys", "0-7", {c: str(c) for c in range(8)})
    said = []
    combo = cpu_combo(profiles, 5, said.append, sys_root=root)
    qtbot.addWidget(combo)
    assert combo.currentIndex() == 0
    combo.setCurrentIndex(1)
    assert profiles.get(5).get(cpu_cores.PROFILE_KEY) is True and "next start" in said[-1]
    combo.setCurrentIndex(0)
    assert cpu_cores.PROFILE_KEY not in profiles.get(5)
    assert cpu_combo(profiles, 5, sys_root=tmp_path / "none") is None

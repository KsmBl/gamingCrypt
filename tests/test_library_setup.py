from pathlib import Path

import pytest

from gamingcrypt.steam import library, library_setup, vdf
from gamingcrypt.steam.client import SteamClient
from tests.conftest import write_manifest

MOUNTED = lambda p: True  # noqa: E731
NOT_RUNNING = lambda: False  # noqa: E731


def test_vdf_dumps_roundtrip():
    data = {"libraryfolders": {"0": {"path": '/a "b"', "apps": {}, "x": "1"}}, "k": "v\\w"}
    assert vdf.loads(vdf.dumps(data)) == data
    assert vdf.dumps({"a": {"b": "c"}}) == '"a"\n{\n\t"b"\t\t"c"\n}\n'


def test_register_adds_library_everywhere(steam_root, tmp_path):
    (steam_root / "config").mkdir()
    (steam_root / "config" / "libraryfolders.vdf").write_text(
        (steam_root / "steamapps" / "libraryfolders.vdf").read_text())
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    result = library_setup.ensure_library(steam_root, str(drive), is_running=NOT_RUNNING, is_mounted=MOUNTED)
    assert result.status == "added" and str(drive) in result.message
    for file in (steam_root / "config" / "libraryfolders.vdf", steam_root / "steamapps" / "libraryfolders.vdf"):
        folders = vdf.load(file)["libraryfolders"]
        assert folders["3"]["path"] == str(drive) and folders["3"]["label"] == "GamingCrypt"
        assert folders["0"]["path"] == str(steam_root)  # existing entries untouched
    assert (drive / "steamapps" / "common").is_dir()
    marker = vdf.load(drive / "libraryfolder.vdf")["libraryfolder"]
    assert marker["label"] == "GamingCrypt"
    assert marker["contentid"] == vdf.load(steam_root / "config" / "libraryfolders.vdf")["libraryfolders"]["3"]["contentid"]
    # GamingCrypt's own scan now finds games installed there
    write_manifest(drive, 413150, "Stardew Valley")
    assert 413150 in {g.appid for g in library.installed_games(steam_root)}


def test_second_run_is_a_noop(steam_root, tmp_path):
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    library_setup.ensure_library(steam_root, str(drive), is_running=NOT_RUNNING, is_mounted=MOUNTED)
    before = (steam_root / "steamapps" / "libraryfolders.vdf").read_text()
    result = library_setup.ensure_library(steam_root, str(drive), is_running=NOT_RUNNING, is_mounted=MOUNTED)
    assert result.status == "already"
    assert (steam_root / "steamapps" / "libraryfolders.vdf").read_text() == before


def test_registered_but_fresh_container_gets_steamapps(steam_root, tmp_path):
    drive = tmp_path / "crypt" / "SteamLibrary"  # already listed by the fixture
    import shutil
    shutil.rmtree(drive)
    drive.mkdir(parents=True)
    result = library_setup.ensure_library(steam_root, str(drive), is_running=NOT_RUNNING, is_mounted=MOUNTED)
    assert result.status == "already" and (drive / "steamapps").is_dir()


def test_not_mounted_never_touches_the_disk(steam_root, tmp_path):
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    result = library_setup.ensure_library(steam_root, str(drive), is_running=NOT_RUNNING,
                                          is_mounted=lambda p: False)
    assert result.status == "not_mounted"
    assert not (drive / "steamapps").exists()
    assert not library_setup.is_registered(steam_root, drive)


def test_no_steam():
    assert library_setup.ensure_library(None, "/x", is_mounted=MOUNTED).status == "no_steam"


class FakeClient:
    def __init__(self, ok=True):
        self.ok = ok
        self.shutdowns = 0

    def shutdown(self):
        self.shutdowns += 1
        return self.ok


def test_running_steam_is_closed_first(steam_root, tmp_path):
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    states = iter([True, True, True, False])
    client = FakeClient()
    result = library_setup.ensure_library(steam_root, str(drive), client, is_running=lambda: next(states),
                                          is_mounted=MOUNTED, sleep=lambda s: None)
    assert result.status == "added" and client.shutdowns == 1


def test_steam_that_wont_close(steam_root, tmp_path):
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    result = library_setup.ensure_library(steam_root, str(drive), FakeClient(), is_running=lambda: True,
                                          is_mounted=MOUNTED, sleep=lambda s: None, timeout=2)
    assert result.status == "failed" and "close" in result.message.lower()
    assert not library_setup.is_registered(steam_root, drive)
    result = library_setup.ensure_library(steam_root, str(drive), FakeClient(ok=False), is_running=lambda: True,
                                          is_mounted=MOUNTED)
    assert result.status == "failed"


def test_missing_vdf_is_created_with_steam_root_as_zero(tmp_path):
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    library_setup.register_library(root, drive, rng=lambda: 42)
    folders = vdf.load(root / "steamapps" / "libraryfolders.vdf")["libraryfolders"]
    assert folders["0"]["path"] == str(root)
    assert folders["1"] == {**folders["1"], "path": str(drive), "contentid": "42"}


def test_steam_running_detection(tmp_path):
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    (proc / "1" / "comm").write_text("bash\n")
    assert not library_setup.steam_running(proc)
    (proc / "42").mkdir()
    (proc / "42" / "comm").write_text("steamwebhelper\n")
    assert library_setup.steam_running(proc)


def test_client_shutdown():
    calls = []
    assert SteamClient(["steam"], launcher=lambda cmd, **kw: calls.append(cmd)).shutdown()
    assert calls == [["steam", "-shutdown"]]
    assert not SteamClient(["xdg-open"], launcher=lambda cmd, **kw: None).shutdown()

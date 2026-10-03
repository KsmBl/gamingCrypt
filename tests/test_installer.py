import os
from pathlib import Path

from gamingcrypt.steam import installer, library, library_setup, vdf
from gamingcrypt.steam.client import SteamClient
from gamingcrypt.steam.service import SteamService
from gamingcrypt.steam.webapi import SteamWebAPI
from tests.conftest import write_manifest
from tests.fakes import FakeSession


class Client:
    def __init__(self, shutdown_ok=True, start_ok=True):
        self.calls = []
        self.shutdown_ok, self.start_ok = shutdown_ok, start_ok

    def shutdown(self):
        self.calls.append("shutdown")
        return self.shutdown_ok

    def start_silent(self):
        self.calls.append("start_silent")
        return self.start_ok


def drive(tmp_path):
    path = tmp_path / "GamingCrypt"
    (path / "steamapps").mkdir(parents=True, exist_ok=True)
    return path


def test_install_dir_name():
    assert installer.install_dir_name('Half-Life 2: "Episode" One?', 1) == "Half-Life 2 Episode One"
    assert installer.install_dir_name("...", 7) == "app_7"


def test_write_manifest(tmp_path):
    path = installer.write_manifest(drive(tmp_path), 413150, "Stardew Valley", owner="7656")
    state = vdf.load(path)["AppState"]
    assert state["appid"] == "413150" and state["StateFlags"] == "1026"
    assert state["installdir"] == "Stardew Valley" and state["LastOwner"] == "7656"
    # GamingCrypt's own scanner treats it as "installed, update pending" -> not playable yet
    game = library.read_manifest(path, tmp_path / "GamingCrypt")
    assert game.update_pending
    path.write_text("custom")
    installer.write_manifest(tmp_path / "GamingCrypt", 413150, "x")
    assert path.read_text() == "custom"  # never overwritten


def test_install_restarts_steam_minimised(steam_root, tmp_path):
    target = drive(tmp_path)
    states = iter([True, True, False, False])
    client = Client()
    result = installer.install(steam_root, target, 413150, "Stardew Valley", client,
                               is_running=lambda: next(states), sleep=lambda s: None)
    assert result.ok and "background" in result.message
    assert client.calls == ["shutdown", "start_silent"]
    assert (target / "steamapps" / "appmanifest_413150.acf").exists()


def test_install_when_steam_not_running(steam_root, tmp_path):
    client = Client()
    assert installer.install(steam_root, drive(tmp_path), 1, "X", client, is_running=lambda: False).ok
    assert client.calls == ["start_silent"]


def test_install_failures(steam_root, tmp_path):
    assert not installer.install(None, tmp_path, 1, "X", Client()).ok
    result = installer.install(steam_root, tmp_path / "locked", 1, "X", Client(), is_running=lambda: False)
    assert not result.ok and "unlocked" in result.message
    result = installer.install(steam_root, drive(tmp_path), 2, "X", Client(shutdown_ok=False),
                               is_running=lambda: True)
    assert not result.ok and "close" in result.message
    result = installer.install(steam_root, drive(tmp_path), 3, "X", Client(start_ok=False), is_running=lambda: False)
    assert not result.ok and "start Steam" in result.message


def test_existing_manifest_elsewhere_is_reused(steam_root, tmp_path):
    target = drive(tmp_path)
    write_manifest(steam_root, 999, "Already queued", flags=1026)
    assert installer.install(steam_root, target, 999, "Already queued", Client(), is_running=lambda: False).ok
    assert not (target / "steamapps" / "appmanifest_999.acf").exists()


def test_progress_states(steam_root):
    assert installer.progress(steam_root, 12345).state == "missing"
    assert installer.progress(None, 1).state == "missing"
    path = steam_root / "steamapps" / "appmanifest_5.acf"

    def manifest(flags, done, total):
        path.write_text(vdf.dumps({"AppState": {"appid": "5", "name": "G", "StateFlags": str(flags),
                                                "BytesDownloaded": str(done), "BytesToDownload": str(total)}}))

    manifest(1026, 0, 0)
    assert installer.progress(steam_root, 5).state == "queued"
    manifest(1026, 250, 1000)
    p = installer.progress(steam_root, 5)
    assert p.state == "downloading" and p.percent == 25.0
    manifest(4, 1000, 1000)
    assert installer.progress(steam_root, 5).state == "installed"
    path.write_text('"AppState" {')
    assert installer.progress(steam_root, 5).state == "queued"


def test_client_start_silent():
    calls = []
    assert SteamClient(["steam"], launcher=lambda cmd, **kw: calls.append(cmd)).start_silent()
    assert calls == [["steam", "-silent"]]
    assert not SteamClient(["xdg-open"], launcher=lambda cmd, **kw: None).start_silent()


def test_service_prefers_mounted_encrypted_library(steam_root, tmp_path, monkeypatch):
    svc = SteamService({"root": str(steam_root)}, tmp_path / "c", api=SteamWebAPI(session=FakeSession({})))
    target = drive(tmp_path)
    svc.install_library = str(target)
    monkeypatch.setattr(os.path, "ismount", lambda p: False)
    assert svc.target_library() == steam_root.resolve()  # not mounted -> Steam's own library
    monkeypatch.setattr(os.path, "ismount", lambda p: p == str(target))
    assert svc.target_library() == steam_root.resolve()  # mounted but not a Steam library yet
    library_setup.register_library(steam_root, target)
    assert svc.target_library() == Path(target)
    assert svc.silent_install

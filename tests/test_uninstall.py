import os

from gamingcrypt.steam import installer
from gamingcrypt.steam.client import SteamClient
from gamingcrypt.steam.installer import InstallResult
from tests.conftest import write_manifest


class Client:
    def __init__(self):
        self.calls = []

    def shutdown(self):
        self.calls.append("shutdown")
        return True

    def start_silent(self):
        self.calls.append("start_silent")
        return True


def installed_game(library, appid=620, name="Portal 2"):
    write_manifest(library, appid, name)
    game = library / "steamapps/common" / name.replace(" ", "")
    (game / "bin").mkdir(parents=True)
    (game / "bin/game.so").write_text("x")
    for extra in (f"workshop/content/{appid}/mod", f"shadercache/{appid}/cache", f"downloading/{appid}",
                  f"compatdata/{appid}/pfx/drive_c/users/steamuser/Saved Games"):
        (library / "steamapps" / extra).mkdir(parents=True, exist_ok=True)
    (library / "steamapps/workshop" / f"appworkshop_{appid}.acf").write_text("")
    return game


def test_uninstall_removes_files_but_keeps_saves(steam_root):
    game = installed_game(steam_root)
    client = Client()
    result = installer.uninstall(steam_root, 620, client, is_running=lambda: False)
    assert result == InstallResult(True, "Portal 2 was uninstalled")
    apps = steam_root / "steamapps"
    assert not game.exists() and not (apps / "appmanifest_620.acf").exists()
    assert not (apps / "workshop/content/620").exists() and not (apps / "workshop/appworkshop_620.acf").exists()
    assert not (apps / "shadercache/620").exists() and not (apps / "downloading/620").exists()
    assert (apps / "compatdata/620/pfx/drive_c/users/steamuser/Saved Games").is_dir()  # saves stay
    assert client.calls == []  # Steam wasn't running -> not started either
    assert 620 not in {g.appid for g in __import__("gamingcrypt.steam.library", fromlist=["x"]).installed_games(steam_root)}


def test_uninstall_on_encrypted_library_restarts_running_steam(steam_root):
    library = steam_root.parent / "crypt" / "SteamLibrary"
    installed_game(library, 1145360, "Hades")
    client = Client()
    states = iter([True, True, False])
    result = installer.uninstall(steam_root, 1145360, client, is_running=lambda: next(states, False),
                                 sleep=lambda s: None)
    assert result.ok and client.calls == ["shutdown", "start_silent"]
    assert not (library / "steamapps/common/Hades").exists()


def test_uninstall_refuses_strange_install_dirs(steam_root):
    victim = steam_root / "steamapps" / "keep-me"
    victim.mkdir()
    for appid, installdir in ((11, ".."), (12, ""), (13, "a/b")):
        path = steam_root / "steamapps" / f"appmanifest_{appid}.acf"
        path.write_text(f'"AppState" {{ "appid" "{appid}" "name" "Evil" "installdir" "{installdir}" }}')
        result = installer.uninstall(steam_root, appid, Client(), is_running=lambda: False)
        assert not result.ok and "Refusing" in result.message
        assert path.exists()
    assert victim.exists()


def test_uninstall_symlinked_game_only_removes_the_link(steam_root, tmp_path):
    write_manifest(steam_root, 70, "Half Life")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "important").write_text("keep")
    (steam_root / "steamapps/common").mkdir(exist_ok=True)
    (steam_root / "steamapps/common/HalfLife").symlink_to(elsewhere)
    assert installer.uninstall(steam_root, 70, Client(), is_running=lambda: False).ok
    assert (elsewhere / "important").read_text() == "keep"
    assert not (steam_root / "steamapps/common/HalfLife").exists()


def test_uninstall_failures(steam_root):
    assert not installer.uninstall(steam_root, 999, Client(), is_running=lambda: False).ok
    assert not installer.uninstall(None, 620, Client()).ok
    installed_game(steam_root)

    class Stubborn(Client):
        def shutdown(self):
            return False

    result = installer.uninstall(steam_root, 620, Stubborn(), is_running=lambda: True)
    assert not result.ok and (steam_root / "steamapps/common/Portal2").exists()

    def broken(path):
        raise PermissionError(13, "Permission denied", str(path))

    client = Client()
    states = iter([True, True, False])
    result = installer.uninstall(steam_root, 620, client, is_running=lambda: next(states, False),
                                 sleep=lambda s: None, remove_tree=broken)
    assert not result.ok and "Permission denied" in result.message
    assert client.calls == ["shutdown", "start_silent"]  # Steam comes back even on errors


# --- Steam windows must not hide behind the launcher -----------------------------

def test_client_reports_steam_windows():
    seen = []
    client = SteamClient(["steam"], launcher=lambda cmd, **kw: None)
    client.on_ui = lambda: seen.append(1)
    client.play(1)
    client.start_silent()
    assert seen == []
    client.install(1)
    client.open_store(1)
    client.uninstall(1)
    assert seen == [1, 1, 1]


def test_service_hands_hook_to_client(tmp_path):
    from gamingcrypt.steam.service import SteamService

    svc = SteamService({"command": "steam"}, tmp_path)
    hook = lambda: None  # noqa: E731
    svc.on_steam_ui = hook
    assert svc.client.on_ui is hook


def test_main_window_minimises_for_steam(qtbot):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    service = FakeService()
    service.on_steam_ui = None
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(service)})
    qtbot.addWidget(window)
    window.show_shell()
    assert service.on_steam_ui == window.minimize_for_steam


def test_single_instance_activation(qtbot):
    from gamingcrypt.app import activate_running_instance, listen_for_activation

    name = f"gamingcrypt-test-{os.getpid()}"
    assert not activate_running_instance(name)  # nobody running
    calls = []
    server = listen_for_activation(lambda: calls.append(1), name)
    assert activate_running_instance(name)
    qtbot.waitUntil(lambda: calls == [1])
    server.close()

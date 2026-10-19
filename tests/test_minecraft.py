"""Minecraft: instances on the drive, portablemc driven through its machine output (signing in,
installing, starting), the library and an instance's page."""

import copy
import io
import subprocess
from types import SimpleNamespace

import pytest

from gamingcrypt.linux.library import is_linux_appid
from gamingcrypt.minecraft import library, portable
from gamingcrypt.minecraft.library import MinecraftInstance
from gamingcrypt.wine.library import WindowsGame, is_wine_appid


@pytest.fixture
def root(tmp_path):
    return tmp_path / "GamingCrypt" / "Minecraft"


def test_instances_are_folders_of_their_own(root):
    first = library.create(root, "Survival")
    second = library.create(root, "Survival", "1.21.4")
    assert first.path.name == "Survival" and second.path.name == "Survival 2"  # the name taken: a folder of its own
    assert (first.path / "options.txt").read_text().startswith("fullscreen:true")
    found = library.scan(root)
    assert [(i.name, i.version, i.installed) for i in found] == [("Survival", "release", ""),
                                                                 ("Survival", "1.21.4", "")]
    assert isinstance(found[0], WindowsGame) and found[0].KIND == "minecraft"  # a PC game like a Linux one
    assert library.is_minecraft_appid(first.appid) and not is_linux_appid(first.appid)
    assert not is_wine_appid(first.appid) and first.appid != second.appid
    found[0].installed = "26.3"
    library.save(found[0])
    assert library.scan(root)[0].installed == "26.3"
    library.remove(found[0])
    assert [i.path.name for i in library.scan(root)] == ["Survival 2"]
    assert library.scan(root / "missing") == []
    assert library.folder_name("a/b:*") == "ab" and library.folder_name("///") == "Minecraft"


def test_rated_and_filtered_as_minecraft(root):
    from gamingcrypt import game_facts, ratings

    instance = library.create(root, "World")
    tab = SimpleNamespace(service=SimpleNamespace(stored_metadata=lambda appid: {}), minecraft_covers=None)
    assert ratings.automatic(instance, tab) == 6
    assert game_facts.facts_of(instance, tab) == game_facts.Facts("Minecraft", ("Adventure", "Simulation"), 2011)


# --- portablemc's machine output -------------------------------------------------------------

def test_parse_rows_and_errors():
    assert portable.parse("auth_device_code\thttps://www.microsoft.com/link\tAB12\n") == (
        "auth_device_code", ["https://www.microsoft.com/link", "AB12"])
    assert portable.parse("log_raw\ta\\tb\\nc") == ("log_raw", ["a\tb\nc"])
    lines = ["row\tusername\tuuid", "sep", "row\tSteve\t1234", "row\tAlex\t5678"]
    assert portable.rows(lines) == [["Steve", "1234"], ["Alex", "5678"]]
    assert "doesn't own" in portable.error_text("error_auth_does_not_own_game", [])
    assert portable.error_text("error_weird_thing", ["x"]) == "Minecraft: weird thing (x)"


def fake_run(stdout, code=0):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, code, stdout, "")

    return run, calls


def test_accounts_and_releases(tmp_path):
    paths = portable.Paths(tmp_path / "Minecraft", "u1")
    run, calls = fake_run("row\tusername\tuuid\nsep\nrow\tSteve\t1234\n")
    assert portable.accounts(paths, run=run) == [portable.Account("Steve", "1234")]
    args = calls[0]
    assert args[args.index("--msa-db-file") + 1] == str(tmp_path / "Minecraft" / ".accounts" / "u1.json")
    assert args[args.index("--main-dir") + 1] == str(tmp_path / "Minecraft" / "Shared")  # shared by all instances
    assert args[-2:] == ["auth", "list"] and "machine" in args
    assert portable.Paths(tmp_path, "").accounts.name == "admin.json"
    run, _calls = fake_run("row\tname\tchannel\trelease_date\nsep\nrow\t26.4-snapshot-1\tsnapshot\tx\n"
                           "row\t26.3\trelease*\tx\nrow\t26.2\trelease\tx\n")
    assert portable.releases(paths, run=run) == ["26.3", "26.2"]


class FakeProcess:
    def __init__(self, lines, code=0):
        self.stdout = io.StringIO("".join(f"{line}\n" for line in lines))
        self.code, self.terminated = code, False

    def wait(self):
        return self.code

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def test_login_reports_the_code_and_the_end(tmp_path):
    paths = portable.Paths(tmp_path, "")
    got = []
    login = portable.Login(paths, lambda link, code: got.append(("code", link, code)),
                           lambda ok, message: got.append(("done", ok, message)),
                           popen=lambda *a, **k: FakeProcess(["auth_request_device_code",
                                                              "auth_device_code\thttps://www.microsoft.com/link\tXY9",
                                                              "auth_wait", "auth_account\tSteve"]))
    login._run()
    assert got == [("code", "https://www.microsoft.com/link", "XY9"), ("done", True, "Signed in")]
    got.clear()
    login.popen = lambda *a, **k: FakeProcess(["error_auth_does_not_own_game"], code=1)
    login._run()
    assert got[-1][:2] == ("done", False) and "doesn't own" in got[-1][2]


def test_install_reports_progress_and_the_version(root):
    instance = library.create(root, "Survival")
    progress = []
    calls = []

    def popen(args, **kwargs):
        calls.append(args)
        return FakeProcess(["load_hierarchy\t26.3", "loaded_hierarchy\t26.3", "download\t1/4\t0/0\t0.1\t1",
                            "download\t2/4\t500/1000\t0.2\t1", "load_jvm\t21", "jvm_args\tx"])

    ok, message, version = portable.install(portable.Paths(root, ""), instance, lambda f, t: progress.append(f),
                                            popen=popen)
    assert ok and version == "26.3"
    assert progress[:2] == [0.25, 0.5]
    assert "--dry" in calls[0] and calls[0][calls[0].index("--mc-dir") + 1] == str(instance.path)
    ok, message, _v = portable.install(portable.Paths(root, ""), instance, lambda *a: None,
                                       popen=lambda *a, **k: FakeProcess(["error_version_not_found\t9.9"], 1))
    assert not ok and message == "This Minecraft version doesn't exist"


def test_launch_command(root):
    instance = library.create(root, "Survival")
    instance.installed = "26.3"
    args = portable.launch_command(portable.Paths(root, ""), instance, portable.Account("Steve", "1"))
    assert args[-4:] == ["-a", "-u", "Steve", "26.3"]
    assert "--dry" not in args and args[args.index("--jvm-policy") + 1] == portable.JVM_POLICY


def test_portablemc_comes_on_demand(monkeypatch):
    monkeypatch.setattr(portable, "available", lambda: False)
    run, calls = fake_run("", code=1)
    ok, message = portable.ensure(run=run)
    assert not ok and "could not be installed" in message
    assert calls[0][1:4] == ["-m", "pip", "install"] and portable.PACKAGE in calls[0]


# --- the Games tab ---------------------------------------------------------------------------

@pytest.fixture
def window(qtbot, root, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    library.create(root, "Survival")
    monkeypatch.setattr(portable, "available", lambda: True)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], minecraft_root=str(root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show()
    w.show_shell()
    games = pages["Games"]
    games.minecraft_accounts = [portable.Account("Steve", "1")]
    qtbot.waitUntil(lambda: len(games.minecraft_games) == 1)
    w._games = games
    return w


def test_library_card_and_page(qtbot, window):
    from gamingcrypt.ui.minecraft_pages import MinecraftInstancePage, MinecraftLibraryPage

    games = window._games
    home = games.home
    assert home.minecraft_card.isVisible() and home.minecraft_card.subtitle.text() == "1 instance"
    home.minecraft_card.tapped.emit()
    page = games.currentWidget()
    assert isinstance(page, MinecraftLibraryPage) and page.account_label.text() == "Signed in as Steve"
    instance = games.minecraft_games[0]
    page.cards[instance.appid].clicked.emit(instance)
    assert isinstance(games.currentWidget(), MinecraftInstancePage)
    assert games.windows_by_appid(instance.appid) is instance  # Continue playing, the loading screen …
    assert window.game_name(instance.appid) == "Survival"


def test_first_play_installs_then_starts(qtbot, window, monkeypatch):
    from gamingcrypt.ui.minecraft_pages import MinecraftInstancePage

    games = window._games
    instance = games.minecraft_games[0]
    started = []
    games.minecraft_launcher = lambda game: started.append(game.installed) or (True, "Starting")

    def installer(paths, game, progress):
        progress(0.5, "Downloading Minecraft…")
        return True, "Installed", "26.3"

    page = MinecraftInstancePage(games, instance, installer=installer)
    games.push(page)
    page.main_button.click()
    qtbot.waitUntil(lambda: started == ["26.3"])
    assert library.scan(games.minecraft_root)[0].installed == "26.3"  # kept
    assert "Minecraft 26.3 · installed" in page.facts.text()
    page.main_button.click()  # installed: straight on
    assert started == ["26.3", "26.3"]


def test_not_signed_in_opens_signing_in(qtbot, window, monkeypatch):
    from gamingcrypt.ui import minecraft_pages
    from gamingcrypt.ui.minecraft_pages import SignInPage

    games = window._games
    games.minecraft_accounts = []
    logins = []

    class FakeLogin:
        def __init__(self, paths, on_code, on_done):
            self.on_code, self.on_done = on_code, on_done
            logins.append(self)

        def start(self):
            self.on_code("https://www.microsoft.com/link", "XY9")

        def cancel(self):
            pass

    monkeypatch.setattr(minecraft_pages.portable, "Login", FakeLogin)
    games.open_minecraft_game(games.minecraft_games[0])
    games.currentWidget().main_button.click()
    page = games.currentWidget()
    assert isinstance(page, SignInPage) and page.code.text() == "XY9" and not page.qr.pixmap().isNull()
    monkeypatch.setattr(portable, "accounts", lambda paths: [portable.Account("Alex", "2")])
    logins[0].on_done(True, "Signed in")
    assert games.currentWidget() is not page and games.minecraft_account().username == "Alex"


def test_new_instance(qtbot, window):
    from gamingcrypt.ui.minecraft_pages import MinecraftInstancePage, NewInstancePage

    games = window._games
    page = NewInstancePage(games, versions=lambda: ["26.3", "26.2"])
    games.push(page)
    qtbot.waitUntil(lambda: page.version.count() == 3)
    assert page.name.text() == "Survival 2"  # (Survival is taken)
    page.version.setCurrentIndex(2)
    page.create_button.click()
    qtbot.waitUntil(lambda: isinstance(games.currentWidget(), MinecraftInstancePage))
    assert games.currentWidget().game.version == "26.2"
    qtbot.waitUntil(lambda: len(games.minecraft_games) == 2)


def test_app_starts_it_through_the_reaper(qtbot, window, monkeypatch, root):
    import subprocess as sp

    games = window._games
    instance = games.minecraft_games[0]
    assert window.launch_minecraft(instance)[0] is False  # not installed yet
    instance.installed = "26.3"
    started = []
    monkeypatch.setattr(sp, "Popen", lambda args, **k: started.append(args))
    ok, _message = window.launch_minecraft(instance)
    assert ok and started[0][1:3] == ["SteamLaunch", f"AppId={instance.appid}"]
    assert started[0][-4:] == ["-a", "-u", "Steve", "26.3"]
    assert window.game_watcher.appid == instance.appid

"""Native Linux games outside Steam: a folder each, a start file, started directly or in Steam's
runtime - library, launch, pages (the Windows games' pages, without Proton / Wine)."""

import copy
import os
import stat

import pytest

from gamingcrypt.linux import library, runners
from gamingcrypt.linux.library import LinuxGame
from gamingcrypt.wine import covers as covers_mod
from gamingcrypt.wine.library import WindowsGame, is_wine_appid

ELF = b"\x7fELF\x02\x01\x01" + bytes(9) + b"\x02\x00" + bytes(40)  # an executable (e_type 2)
PIE = b"\x7fELF\x02\x01\x01" + bytes(9) + b"\x03\x00" + bytes(40)  # position independent (e_type 3)


def make_game(root, name, files):
    folder = root / name
    for rel, content in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)  # copied over the network share: not executable
    return folder


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "GamingCrypt" / "Linux Games"
    make_game(root, "Celeste", {"Celeste.x86_64": PIE + b"x" * 500, "Celeste.x86": PIE, "Celeste.dll": b"MZ",
                                "lib64/libSDL2-2.0.so.0": ELF + b"x" * 900, "Content/level.bin": b"data",
                                "README": b"#!not really", "UnityCrashHandler64": ELF})
    make_game(root, "Stardew Valley", {"start.sh": b"#!/bin/bash\ncd game && ./StardewValley\n",
                                       "game/StardewValley": ELF + b"x" * 3000,
                                       "support/postinst.sh": b"#!/bin/sh\n", "uninstall-Stardew.sh": b"#!/bin/sh\n"})
    (root / ".covers").mkdir()
    return root


def test_every_folder_is_a_game(root):
    games = library.scan(root)
    assert [g.name for g in games] == ["Celeste", "Stardew Valley"]
    celeste = games[0]
    assert isinstance(celeste, LinuxGame) and isinstance(celeste, WindowsGame)  # the same, without Wine
    assert celeste.KIND == "linux" and celeste.LABEL == "Linux"
    assert library.is_linux_appid(celeste.appid) and not is_wine_appid(celeste.appid)
    windows = WindowsGame(celeste.path, celeste.name)
    assert windows.appid != celeste.appid  # the same folder name in both libraries: two games
    assert celeste.appid > 4_000_000  # far above any Steam app
    assert library.scan(root / "missing") == []


def test_the_likeliest_start_file_first(root):
    celeste, stardew = library.scan(root)
    exes = library.executables(celeste)
    assert exes[0] == "Celeste.x86_64"  # 64-bit first; not the crash handler
    assert "Celeste.x86" in exes and "UnityCrashHandler64" in exes
    assert not {"lib64/libSDL2-2.0.so.0", "Celeste.dll", "README", "Content/level.bin"} & set(exes)
    exes = library.executables(stardew)
    assert exes[0] == "start.sh"  # GOG's start script, before the program it starts
    assert "game/StardewValley" in exes and "support/postinst.sh" not in exes  # support/ isn't looked into
    assert exes[-1] == "uninstall-Stardew.sh"


def test_start_files_get_executable_again(root):
    celeste = library.scan(root)[0]
    library.make_startable(celeste)
    assert os.stat(celeste.path / "Celeste.x86_64").st_mode & stat.S_IXUSR
    assert not os.stat(celeste.path / "Content" / "level.bin").st_mode & stat.S_IXUSR  # data stays data


def test_runners(tmp_path):
    home = tmp_path / "home"
    assert runners.available(home) == [runners.DIRECT]
    script = home / ".local" / "share" / "Steam" / "ubuntu12_32" / "steam-runtime" / "run.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n")
    found = runners.available(home)
    assert [r.id for r in found] == ["direct", "steam-runtime"] and found[1].prefix == (str(script),)
    assert runners.pick(found, "steam-runtime") is found[1] and runners.pick(found, None) is runners.DIRECT
    assert runners.pick(found, "gone") is runners.DIRECT


def test_launch_like_a_steam_game(root, tmp_path):
    stardew = library.scan(root)[1]
    started = []
    ok, message = runners.launch(stardew, "start.sh", runners.DIRECT, tmp_path / "data", tmp_path / "logs",
                                 popen=lambda args, **kw: started.append((args, kw)),
                                 more_env={"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"})
    assert ok and message == "Starting Stardew Valley…"
    args, kw = started[0]
    assert args[1:4] == ["SteamLaunch", f"AppId={stardew.appid}", "--"] and args[4] == str(stardew.path / "start.sh")
    assert kw["cwd"] == str(stardew.path) and kw["start_new_session"]
    assert kw["env"]["SDL_GAMECONTROLLER_IGNORE_DEVICES"] == "0x045e/0x028e"  # only the virtual pad, as for Wine
    assert os.stat(stardew.path / "game" / "StardewValley").st_mode & stat.S_IXUSR  # what start.sh runs, too
    in_runtime = runners.Runner("steam-runtime", "Steam Runtime", ("/steam/run.sh",))
    runners.launch(stardew, "game/StardewValley", in_runtime, tmp_path / "data", tmp_path / "logs",
                   popen=lambda args, **kw: started.append((args, kw)))
    args, kw = started[-1]
    assert args[4:] == ["/steam/run.sh", str(stardew.path / "game" / "StardewValley")]
    assert kw["cwd"] == str(stardew.path / "game")
    ok, message = runners.launch(stardew, "gone.sh", runners.DIRECT, tmp_path, tmp_path, popen=lambda *a, **k: None)
    assert not ok and "gone.sh" in message

    def fails(*a, **k):
        raise OSError("no reaper")

    ok, message = runners.launch(stardew, "start.sh", runners.DIRECT, tmp_path / "d", tmp_path / "l", popen=fails)
    assert not ok and "no reaper" in message


# --- the Games tab ------------------------------------------------------------------------------
@pytest.fixture
def window(qtbot, root, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    launched = []
    monkeypatch.setattr(runners, "launch", lambda game, exe, runner, *a, **k: launched.append(
        (game.name, exe, runner.id, k.get("more_env"))) or (True, "Starting"))
    monkeypatch.setattr(covers_mod.Covers, "fetch", lambda self, game: None)
    windows_root = tmp_path / "GamingCrypt" / "Windows Games"
    (windows_root / "Hollow Knight").mkdir(parents=True)
    (windows_root / "Hollow Knight" / "hollow_knight.exe").write_bytes(b"MZ")
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], windows_root=str(windows_root),
                                  linux_root=str(root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show()
    w.show_shell()
    games = pages["Games"]
    games._linux_runners = [runners.DIRECT, runners.Runner("steam-runtime", "Steam Runtime (for older games)",
                                                           ("/run.sh",))]
    qtbot.waitUntil(lambda: len(games.linux_games) == 2 and len(games.windows_games) == 1)
    w._games, w._launched = games, launched
    return w


def test_library_card_and_installed_list(qtbot, window):
    home = window._games.home
    assert home.linux_card.isVisible() and home.linux_card.subtitle.text() == "2 games"
    assert home.windows_card.isVisible() and home.windows_card.subtitle.text() == "1 game"
    from gamingcrypt.ui.wine_pages import WindowsCard

    cards = sorted((c for c in home.cards.values() if isinstance(c, WindowsCard)), key=lambda c: c.game.name)
    assert [(c.game.name, c.meta.text().split(" · ")[0]) for c in cards] == [
        ("Celeste", "Linux"), ("Hollow Knight", "Windows"), ("Stardew Valley", "Linux")]
    window._games.library_settings["hidden"] = ["linux"]
    home.apply_libraries()
    assert not home.linux_card.isVisible() and home.windows_card.isVisible()  # Settings can hide each
    from gamingcrypt.ui.games_tab import LIBRARIES

    assert LIBRARIES["linux"] == "Linux games"


def test_library_page(qtbot, window):
    from gamingcrypt.ui.wine_pages import LinuxGamePage, LinuxLibraryPage

    games = window._games
    games.home.linux_card.tapped.emit()
    page = games.currentWidget()
    assert isinstance(page, LinuxLibraryPage) and page.shown
    qtbot.waitUntil(lambda: window.focusWidget() is page.cards[page.shown[0]])
    page.search.setText("star")
    assert [games.windows_by_appid(a).name for a in page.shown] == ["Stardew Valley"]
    page.cards[page.shown[0]].clicked.emit(games.windows_by_appid(page.shown[0]))
    assert isinstance(games.currentWidget(), LinuxGamePage)
    games.reload_windows()  # the Windows library reloading doesn't swap a Linux page for its own
    qtbot.wait(100)
    assert isinstance(games.currentWidget(), LinuxGamePage)


def test_game_page_options_and_play(qtbot, window):
    games = window._games
    stardew = next(g for g in games.linux_games if g.name == "Stardew Valley")
    games.open_linux_game(stardew)
    page = games.currentWidget()
    qtbot.waitUntil(lambda: page.exe_combo.count() == 3)
    assert page.exe_combo.currentData() == "start.sh"
    assert window.game_profiles.get(stardew.appid)["exe"] == "start.sh"
    assert [page.runner_combo.itemText(i) for i in range(page.runner_combo.count())] == [
        "Directly", "Steam Runtime (for older games)"]
    assert page.facts.text().startswith("Linux game\nStarts start.sh\nRuns directly")
    assert "home folder" in page.prefix_note.text()
    page.runner_combo.setCurrentIndex(1)
    assert window.game_profiles.get(stardew.appid)["runner"] == "steam-runtime"
    assert "Runs in Steam's runtime" in page.facts.text()
    page.main_button.click()
    assert window._launched[-1][:3] == ("Stardew Valley", "start.sh", "steam-runtime")
    assert window.game_watcher.appid == stardew.appid and window.game_name(stardew.appid) == "Stardew Valley"
    assert window.launch_overlay.phase.text() == "Starting Stardew Valley…"


def test_remove_deletes_the_folder(qtbot, window, root):
    games = window._games
    celeste = next(g for g in games.linux_games if g.name == "Celeste")
    games.open_linux_game(celeste)
    page = games.currentWidget()
    page.options_button.click()
    page.remove_button.click()
    assert not page.confirm.saves_button.isVisible()  # no Wine prefix: nothing else to ask
    page.confirm.remove_button.click()
    qtbot.waitUntil(lambda: not (root / "Celeste").exists())
    qtbot.waitUntil(lambda: [g.name for g in games.linux_games] == ["Stardew Valley"])


def test_play_time_continue_recent_and_favorites(qtbot, window, monkeypatch):
    import time as time_mod

    games = window._games
    stardew = next(g for g in games.linux_games if g.name == "Stardew Valley")
    now = [1_750_000_000.0]
    monkeypatch.setattr(time_mod, "time", lambda: now[0])
    window.launch_linux(stardew)
    now[0] += 45 * 60
    window.game_ended(stardew.appid)
    profile = window.game_profiles.get(stardew.appid)
    assert profile["minutes"] == 45 and profile["last_played"] == 1_750_002_700
    qtbot.waitUntil(lambda: games.home.continue_card.game is not None
                    and games.home.continue_card.game.name == "Stardew Valley")
    assert games.home.continue_card.meta.text().startswith("Linux · last played")
    games.home.continue_card.play_button.click()
    assert window._launched[-1][0] == "Stardew Valley"
    games.home.continue_card.details_button.click()
    from gamingcrypt.ui.wine_pages import LinuxGamePage

    assert isinstance(games.currentWidget(), LinuxGamePage)
    games.currentWidget().favorite_button.click()
    games.back()
    assert games.home.favorites_card.subtitle.text() == "1 game"
    games.open_favorites()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: stardew.appid in page.cards)
    games.back()
    games.open_recent()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: stardew.appid in page.cards)


def test_launch_gives_the_controller_and_says_what_is_missing(qtbot, window, root):
    games = window._games

    class Pads:
        def game_env(self):
            return {"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"}

        def stop(self):
            pass

    window.input_service = Pads()
    stardew = next(g for g in games.linux_games if g.name == "Stardew Valley")
    assert window.launch_linux(stardew)[0]
    assert window._launched[-1][3] == {"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"}
    empty = make_game(root, "Empty", {"data.pak": b"x"})
    ok, message = window.launch_linux(LinuxGame(empty, "Empty"))
    assert not ok and "program or start script" in message
    window.game_watcher.phase = "playing"
    window.launch_linux(stardew)
    window.hide()
    assert window.emulated_game_in_front()  # GamingCrypt's volume indicator over it


def test_upload_offers_each_game_folder(root):
    from gamingcrypt.ui.wine_pages import LinuxUploadPage, upload_folders

    assert upload_folders(root, "linux") == {"linux/Celeste": ("Game: Celeste", root / "Celeste"),
                                             "linux/Stardew Valley": ("Game: Stardew Valley", root / "Stardew Valley")}
    assert LinuxUploadPage.TITLE == "Add Linux games" and "Linux Games folder" in LinuxUploadPage.HINT


def test_upload_page_opens_and_reloads(qtbot, window, root):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    games = window._games

    class FakeUpload(QWidget):
        closed = Signal()

        def __init__(self, folder):
            super().__init__()
            self.folder = folder

    games.upload_page_factory = FakeUpload
    games.open_linux_library()
    games.currentWidget().add_button.click()
    page = games.currentWidget()
    assert isinstance(page, FakeUpload) and page.folder == root
    make_game(root, "Another Game", {"another.sh": b"#!/bin/sh\n"})
    page.closed.emit()
    qtbot.waitUntil(lambda: len(games.linux_games) == 3)

"""Windows games outside Steam: a folder each, a start file, Proton or Wine - library, launch, pages."""

import copy
import os

import pytest

from gamingcrypt.wine import covers as covers_mod
from gamingcrypt.wine import library, runners
from gamingcrypt.wine.library import WindowsGame


def make_game(root, name, files):
    folder = root / name
    for rel, size in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
    return folder


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "GamingCrypt" / "Windows Games"
    make_game(root, "Hollow Knight", {"hollow_knight.exe": 600, "UnityCrashHandler64.exe": 900,
                                      "unins000.exe": 1000, "data/level1.dat": 5000})
    make_game(root, "Big Adventure", {"Binaries/Win64/BigAdventure-Win64-Shipping.exe": 2000,
                                      "BigAdventure.exe": 300, "_CommonRedist/vcredist_x64.exe": 9000,
                                      "Engine/Extras/Redist/en-us/UE4PrereqSetup_x64.exe": 8000})
    (root / ".prefixes" / "Hollow Knight" / "pfx").mkdir(parents=True)
    (root / ".covers").mkdir()
    return root


def test_every_folder_is_a_game(root):
    games = library.scan(root)
    assert [g.name for g in games] == ["Big Adventure", "Hollow Knight"]  # not the prefixes, not the covers
    knight = games[1]
    assert knight.size == 600 + 900 + 1000 + 5000
    assert library.is_wine_appid(knight.appid) and knight.appid == library.scan(root)[1].appid
    assert len({g.appid for g in games}) == 2
    from gamingcrypt.emulation.library import EMU_APPID_BASE
    from gamingcrypt.movies.library import MOVIE_APPID_BASE, is_movie_appid

    assert knight.appid < MOVIE_APPID_BASE < EMU_APPID_BASE and not is_movie_appid(knight.appid)
    assert library.scan(root / "missing") == []


def test_the_likeliest_start_file_first(root):
    knight = next(g for g in library.scan(root) if g.name == "Hollow Knight")
    exes = library.executables(knight)
    assert exes[0] == "hollow_knight.exe"  # not the bigger crash handler or uninstaller
    assert set(exes) == {"hollow_knight.exe", "UnityCrashHandler64.exe", "unins000.exe"}
    adventure = next(g for g in library.scan(root) if g.name == "Big Adventure")
    exes = library.executables(adventure)
    assert exes[0] == "BigAdventure.exe"  # named like the game, near the top
    assert "_CommonRedist/vcredist_x64.exe" not in exes  # redistributables' folders aren't looked into
    assert exes == ["BigAdventure.exe", "Binaries/Win64/BigAdventure-Win64-Shipping.exe"]  # no prerequisites


def test_remove_keeps_saves_unless_asked(root):
    knight = next(g for g in library.scan(root) if g.name == "Hollow Knight")
    (library.prefix_dir(knight) / "pfx" / "save.dat").write_bytes(b"s" * 10)
    freed = library.remove(knight, with_saves=False)
    assert freed == 7500 and not knight.path.exists() and library.prefix_dir(knight).exists()
    adventure = next(g for g in library.scan(root) if g.name == "Big Adventure")
    library.prefix_dir(adventure).mkdir(parents=True)
    library.remove(adventure, with_saves=True)
    assert not adventure.path.exists() and not library.prefix_dir(adventure).exists()


# --- what runs them ---------------------------------------------------------------------------
@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    steam = home / ".local" / "share" / "Steam"
    for name in ("Proton - Experimental", "Proton 9.0 (Beta)"):
        (steam / "steamapps" / "common" / name).mkdir(parents=True)
        (steam / "steamapps" / "common" / name / "proton").write_text("#!/bin/sh")
    (steam / "steamapps" / "common" / "Half-Life").mkdir()
    (steam / "compatibilitytools.d" / "GE-Proton9-20").mkdir(parents=True)
    (steam / "compatibilitytools.d" / "GE-Proton9-20" / "proton").write_text("#!/bin/sh")
    drive = tmp_path / "drive"
    (drive / "steamapps" / "common" / "Proton 8.0").mkdir(parents=True)
    (drive / "steamapps" / "common" / "Proton 8.0" / "proton").write_text("#!/bin/sh")
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n "0"\n {{\n  "path" "{steam}"\n }}\n "1"\n {{\n  "path" "{drive}"\n }}\n}}\n')
    wine = home / ".local" / "share" / "lutris" / "runners" / "wine" / "wine-ge-8-26" / "bin"
    wine.mkdir(parents=True)
    (wine / "wine").write_text("#!/bin/sh")
    return home


def test_every_proton_and_wine(home):
    found = runners.available(home, which=lambda n: "/usr/bin/wine" if n == "wine" else None)
    labels = [r.label for r in found]
    assert labels[0] == "Proton - Experimental"  # the newest Proton is the default
    assert set(labels) == {"Proton - Experimental", "GE-Proton9-20", "Proton 9.0 (Beta)", "Proton 8.0",
                           "Wine (system)", "Wine wine-ge-8-26"}
    assert labels.index("Proton 8.0") < labels.index("Wine (system)")  # Protons before Wines
    assert runners.pick(found, "wine:system").label == "Wine (system)"
    assert runners.pick(found, "proton:gone") is found[0] and runners.pick([], None) is None


def test_proton_with_umu_without_and_wine(root, home):
    knight = next(g for g in library.scan(root) if g.name == "Hollow Knight")
    proton = runners.Runner("proton:GE", "GE", "proton", home / "GE")
    args, env, cwd = runners.command(proton, knight, "hollow_knight.exe", home, which=lambda n: "/usr/bin/umu-run")
    assert args == ["/usr/bin/umu-run", str(knight.path / "hollow_knight.exe")] and cwd == knight.path
    assert env["PROTONPATH"] == str(home / "GE") and env["WINEPREFIX"] == str(library.prefix_dir(knight) / "pfx")
    args, env, _ = runners.command(proton, knight, "hollow_knight.exe", home, which=lambda n: None)
    assert args == [str(home / "GE" / "proton"), "run", str(knight.path / "hollow_knight.exe")]
    assert env["STEAM_COMPAT_DATA_PATH"] == str(library.prefix_dir(knight))
    wine = runners.Runner("wine:system", "Wine", "wine", home / "wine")
    args, env, _ = runners.command(wine, knight, "hollow_knight.exe", home)
    assert args == [str(home / "wine"), str(knight.path / "hollow_knight.exe")]
    assert env["WINEPREFIX"].endswith("Hollow Knight/pfx")


def test_launch_like_a_steam_game(root, home, tmp_path):
    knight = next(g for g in library.scan(root) if g.name == "Hollow Knight")
    started = []
    proton = runners.Runner("proton:GE", "GE-Proton9-20", "proton", home / "GE")
    ok, message = runners.launch(knight, "hollow_knight.exe", proton, tmp_path / "data", tmp_path / "logs",
                                 popen=lambda args, **kw: started.append((args, kw)), home=home, which=lambda n: None)
    assert ok and message == "Starting Hollow Knight with GE-Proton9-20…"
    args, kw = started[0]
    assert args[1:4] == ["SteamLaunch", f"AppId={knight.appid}", "--"]  # gamescope, quick menu, Force quit
    assert kw["cwd"] == str(knight.path) and kw["start_new_session"]
    assert kw["env"].get("SDL_GAMECONTROLLER_IGNORE_DEVICES") == os.environ.get("SDL_GAMECONTROLLER_IGNORE_DEVICES")
    runners.launch(knight, "hollow_knight.exe", proton, tmp_path / "data", tmp_path / "logs",
                   popen=lambda args, **kw: started.append((args, kw)), home=home, which=lambda n: None,
                   more_env={"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"})
    assert started[-1][1]["env"]["SDL_GAMECONTROLLER_IGNORE_DEVICES"] == "0x045e/0x028e"
    ok, message = runners.launch(knight, "gone.exe", proton, tmp_path / "d", tmp_path / "l",
                                 popen=lambda *a, **k: None, home=home)
    assert not ok and "gone.exe" in message


# --- covers -------------------------------------------------------------------------------------
class Response:
    def __init__(self, data=None, content=b"", status=200):
        self.data, self.content, self.status_code = data, content, status

    def json(self):
        return self.data


def test_cover_from_steams_store(root):
    asked = []

    def get(url, params=None):
        asked.append((url, params))
        if url == covers_mod.SEARCH:
            return Response({"items": [{"id": 367520, "name": "Hollow Knight", "type": "app"}]})
        if "367520/library_600x900" in url:
            return Response(content=b"\xff\xd8\xff\xe0jpeg")
        return Response(status=404)

    covers = covers_mod.Covers(root, get=get, now=lambda: 1000)
    knight = WindowsGame(root / "Hollow_Knight-v1.5.78 [GOG]", "Hollow_Knight-v1.5.78 [GOG]")
    path = covers.fetch(knight)
    assert path == root / ".covers" / "Hollow_Knight-v1.5.78 [GOG].jpg" and path.read_bytes().startswith(b"\xff\xd8")
    assert asked[0][1]["term"] == "Hollow Knight"  # the folder's name, cleaned
    assert covers.fetch(knight) == path and len(asked) == 2  # kept


def test_no_cover_found_is_remembered(root):
    calls = []
    covers = covers_mod.Covers(root, get=lambda url, params=None: calls.append(url) or Response({"items": [
        {"id": 1, "name": "Something Else Entirely", "type": "app"}]}), now=lambda: 1000)
    game = WindowsGame(root / "My Homebrew", "My Homebrew")
    assert covers.fetch(game) is None and covers.fetch(game) is None and len(calls) == 1


def test_offline_tries_again(root):
    import requests

    def offline(url, params=None):
        raise requests.ConnectionError("no")

    covers = covers_mod.Covers(root, get=offline)
    assert covers.fetch(WindowsGame(root / "X", "X")) is None
    assert not (root / ".covers" / "X.nomatch").exists()


@pytest.mark.parametrize("folder, name", [("Hollow_Knight-v1.5.78 [GOG]", "Hollow Knight"),
                                          ("Fallout.New.Vegas", "Fallout New Vegas"),
                                          ("Doom 3 BFG v1.0.2", "Doom 3 BFG"), ("Celeste (Portable)", "Celeste")])
def test_search_names(folder, name):
    assert covers_mod.search_name(folder) == name


# --- the Games tab ------------------------------------------------------------------------------
@pytest.fixture
def window(qtbot, root, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    launched = []
    monkeypatch.setattr(runners, "launch", lambda game, exe, runner, *a, **k: launched.append(
        (game.name, exe, runner.id)) or (True, "Starting"))
    monkeypatch.setattr(covers_mod.Covers, "fetch", lambda self, game: None)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], windows_root=str(root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show()
    w.show_shell()
    games = pages["Games"]
    games._runners = [runners.Runner("proton:Proton - Experimental", "Proton - Experimental", "proton", root),
                      runners.Runner("wine:system", "Wine (system)", "wine", root)]
    qtbot.waitUntil(lambda: len(games.windows_games) == 2)
    w._games, w._launched = games, launched
    return w


def test_library_card_and_installed_list(qtbot, window):
    home = window._games.home
    assert home.windows_card.isVisible() and home.windows_card.subtitle.text() == "2 games"
    from gamingcrypt.ui.wine_pages import WindowsCard

    cards = [c for c in home.cards.values() if isinstance(c, WindowsCard)]
    assert sorted(c.game.name for c in cards) == ["Big Adventure", "Hollow Knight"]
    assert all(c.meta.text().startswith("Windows · ") for c in cards)
    window._games.library_settings["hidden"] = ["windows"]
    home.apply_libraries()
    assert not home.windows_card.isVisible()  # Settings -> Games -> Libraries can hide it


def test_library_page_opens_on_its_first_game(qtbot, window):
    games = window._games
    games.home.windows_card.tapped.emit()
    page = games.currentWidget()
    from gamingcrypt.ui.wine_pages import WindowsLibraryPage

    assert isinstance(page, WindowsLibraryPage) and page.shown
    qtbot.waitUntil(lambda: window.focusWidget() is page.cards[page.shown[0]])
    page.search.setText("hollow")
    assert [games.windows_by_appid(a).name for a in page.shown] == ["Hollow Knight"]


def test_game_page_options_and_play(qtbot, window):
    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    games.open_windows_game(knight)
    page = games.currentWidget()
    qtbot.waitUntil(lambda: page.exe_combo.count() == 3)
    assert page.exe_combo.currentData() == "hollow_knight.exe"
    assert window.game_profiles.get(knight.appid)["exe"] == "hollow_knight.exe"  # remembered once found
    assert [page.runner_combo.itemText(i) for i in range(page.runner_combo.count())] == [
        "Proton - Experimental", "Wine (system)"]
    page.options_button.click()
    page.runner_combo.setCurrentIndex(1)
    assert window.game_profiles.get(knight.appid)["runner"] == "wine:system"
    assert "Runs with Wine (system)" in page.facts.text() and "Starts hollow_knight.exe" in page.facts.text()
    page.main_button.click()
    assert window._launched == [("Hollow Knight", "hollow_knight.exe", "wine:system")]
    assert window.game_watcher.appid == knight.appid and window.game_name(knight.appid) == "Hollow Knight"
    assert window.launch_overlay.phase.text() == "Starting Hollow Knight…"


def test_play_time_and_continue(qtbot, window, monkeypatch):
    import time as time_mod

    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    now = [1_750_000_000.0]
    monkeypatch.setattr(time_mod, "time", lambda: now[0])
    window.launch_windows(knight)
    now[0] += 30 * 60
    window.game_ended(knight.appid)
    profile = window.game_profiles.get(knight.appid)
    assert profile["minutes"] == 30 and profile["last_played"] == 1_750_001_800
    qtbot.waitUntil(lambda: games.home.continue_card.game is not None
                    and games.home.continue_card.game.name == "Hollow Knight")
    assert games.home.continue_card.meta.text().startswith("Windows · last played")
    games.home.continue_card.play_button.click()
    assert window._launched[-1][0] == "Hollow Knight"


def test_wine_skips_the_grabbed_controller(qtbot, window, monkeypatch):
    # Wine finds the grabbed (silent) real pad first - GTA's GInput listened to it as player 1
    seen = []
    monkeypatch.setattr(runners, "launch", lambda *a, **k: seen.append(k.get("more_env")) or (True, "Starting"))

    class Pads:
        def game_env(self):
            return {"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"}

        def stop(self):
            pass

    window.input_service = Pads()
    assert window.launch_windows(window._games.windows_games[0])[0]
    assert seen == [{"SDL_GAMECONTROLLER_IGNORE_DEVICES": "0x045e/0x028e"}]


def test_no_runner_says_what_to_do(qtbot, window):
    games = window._games
    games._runners = []
    ok, message = window.launch_windows(games.windows_games[0])
    assert not ok and "Proton" in message and "Wine" in message


def test_remove_asks_about_saves(qtbot, window, root):
    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    games.open_windows_game(knight)
    page = games.currentWidget()
    page.options_button.click()
    page.remove_button.click()
    confirm = page.confirm
    assert "Really remove Hollow Knight?" in confirm.question.text() and confirm.saves_button.isVisible()
    confirm.remove_button.click()
    qtbot.waitUntil(lambda: games.currentWidget() is games.home)
    assert not (root / "Hollow Knight").exists() and (root / ".prefixes" / "Hollow Knight").exists()
    qtbot.waitUntil(lambda: [g.name for g in games.windows_games] == ["Big Adventure"])
    assert "its saves are kept" in games.home.notice.text()


def test_favorite_shows_in_favorites(qtbot, window):
    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    games.open_windows_game(knight)
    games.currentWidget().favorite_button.click()
    games.back()
    games.open_favorites()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: knight.appid in page.cards)


def test_upload_offers_each_game_folder(root):
    from gamingcrypt.ui.wine_pages import upload_folders

    assert upload_folders(root) == {"windows/Big Adventure": ("Game: Big Adventure", root / "Big Adventure"),
                                    "windows/Hollow Knight": ("Game: Hollow Knight", root / "Hollow Knight")}


def test_volume_popup_over_windows_games(qtbot, window):
    games = window._games
    knight = games.windows_games[0]
    window.launch_windows(knight)
    window.game_watcher.phase = "playing"
    window.hide()
    assert window.emulated_game_in_front()  # nobody else shows the volume over it


def test_install_script_installs_umu():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "install.sh").read_text()
    assert "install_windows_games() {" in script and "umu-launcher" in script
    assert "\n    install_windows_games\n" in script


def test_runner_launch_failure(root, home, tmp_path):
    knight = next(g for g in library.scan(root) if g.name == "Hollow Knight")

    def fails(*a, **k):
        raise OSError("no reaper")

    ok, message = runners.launch(knight, "hollow_knight.exe", runners.Runner("wine:x", "W", "wine", home),
                                 tmp_path / "d", tmp_path / "l", popen=fails, home=home)
    assert not ok and "no reaper" in message


# --- 32-bit games need a 32-bit Vulkan driver (GTA San Andreas quit after 2 s on the handheld) ----
def pe(machine: int) -> bytes:
    head = bytearray(512)
    head[:2] = b"MZ"
    head[0x3C:0x40] = (0x80).to_bytes(4, "little")
    head[0x80:0x84] = b"PE\0\0"
    head[0x84:0x86] = machine.to_bytes(2, "little")
    return bytes(head)


def test_32bit_programs_are_recognised(tmp_path):
    (tmp_path / "gta_sa.exe").write_bytes(pe(0x14C))
    (tmp_path / "game64.exe").write_bytes(pe(0x8664))
    (tmp_path / "not.exe").write_bytes(b"hello")
    assert runners.is_32bit(tmp_path / "gta_sa.exe")
    assert not runners.is_32bit(tmp_path / "game64.exe") and not runners.is_32bit(tmp_path / "not.exe")
    assert not runners.is_32bit(tmp_path / "missing.exe")


def test_32bit_vulkan_driver(tmp_path):
    icd = tmp_path / "icd.d"
    icd.mkdir()
    lib32 = tmp_path / "lib32"
    lib32.mkdir()
    amd = {"0x1002"}
    # as on the handheld: AMD's 64-bit driver (a bare name), NVIDIA's for both - but no NVIDIA GPU
    (icd / "radeon_icd.json").write_text('{"ICD": {"library_path": "libvulkan_radeon.so"}}')
    (icd / "nvidia_icd.json").write_text('{"ICD": {"library_path": "libGLX_nvidia.so.0"}}')
    (lib32 / "libGLX_nvidia.so.0").write_text("x")
    assert not runners.vulkan_32bit([icd], lib32, amd)
    assert runners.vulkan_32bit([icd], lib32, {"0x10de"})  # with an NVIDIA GPU it would be the one
    (icd / "radeon_icd.i686.json").write_text('{"ICD": {"library_path": "/usr/lib32/libvulkan_radeon.so"}}')
    assert runners.vulkan_32bit([icd], lib32, amd)  # lib32-vulkan-radeon installed
    (icd / "radeon_icd.i686.json").unlink()
    (lib32 / "libvulkan_radeon.so").write_text("x")
    assert runners.vulkan_32bit([icd], lib32, amd)  # bare name, its 32-bit library there
    (icd / "lvp_icd.json").write_text('{"ICD": {"library_path": "/usr/lib32/libvulkan_lvp.so"}}')
    (icd / "broken.json").write_text("{")
    assert not runners.vulkan_32bit([icd], tmp_path / "none", amd)  # software rendering doesn't count


def test_gpu_vendors(tmp_path):
    (tmp_path / "card1" / "device").mkdir(parents=True)
    (tmp_path / "card1" / "device" / "vendor").write_text("0x1002\n")
    assert runners.gpu_vendors(tmp_path) == {"0x1002"}


def test_a_32bit_game_without_the_driver_says_why(qtbot, window, root, monkeypatch):
    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    (knight.path / "hollow_knight.exe").write_bytes(pe(0x14C))
    window.game_profiles.set(knight.appid, "exe", "hollow_knight.exe")
    monkeypatch.setattr(runners, "vulkan_32bit", lambda *a, **k: False)
    ok, message = window.launch_windows(knight)
    assert not ok and "32-bit" in message and "lib32-vulkan-radeon" in message and "install.sh" in message
    assert window._launched == []
    window.game_profiles.set(knight.appid, "runner", "wine:system")  # Wine draws with OpenGL: no need
    assert window.launch_windows(knight)[0]
    monkeypatch.setattr(runners, "vulkan_32bit", lambda *a, **k: True)
    window.game_profiles.set(knight.appid, "runner", None)
    assert window.launch_windows(knight)[0]


def test_install_script_installs_the_32bit_vulkan_driver():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "install.sh").read_text()
    assert "lib32-vulkan-radeon" in script and "lib32-vulkan-intel" in script and "0x1002" in script


def test_loading_screen_shows_the_games_cover(qtbot, window, monkeypatch, tmp_path):
    """Not the drawn letter: the same picture as on the game's card."""
    from tests.fakes import cover_color, solid_image

    picture = solid_image(tmp_path / "knight.jpg")
    monkeypatch.setattr(covers_mod.Covers, "cached", lambda self, game: picture if game.name == "Hollow Knight" else None)
    games = window._games
    knight = next(g for g in games.windows_games if g.name == "Hollow Knight")
    games.open_windows_game(knight)
    page = games.currentWidget()
    qtbot.waitUntil(lambda: page.exe_combo.count() == 3)
    page.main_button.click()
    assert window.launch_overlay.isVisible() and cover_color(window.launch_overlay.cover) == "#d03020"

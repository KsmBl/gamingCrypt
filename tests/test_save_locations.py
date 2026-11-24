"""Where a Windows game saves: from Ludusavi's list, or found while it was played - only those files."""

import gzip
import json
import os
import time

import pytest

from gamingcrypt import save_locations as places
from gamingcrypt import save_manifest, saves
from gamingcrypt.save_locations import LISTED, PLAYED, SETTINGS, Location
from gamingcrypt.wine import library
from gamingcrypt.wine.library import WindowsGame

LIST = """---
"Hollow Knight":
  files:
    "<base>/hollow_knight_Data/Config.ini":
      tags:
        - config
      when:
        - os: windows
        - os: linux
    "<home>/AppData/LocalLow/Team Cherry/Hollow Knight/*.dat":
      tags:
        - save
      when:
        - os: windows
    "<home>/Library/Application Support/unity.Team Cherry.Hollow Knight":
      tags:
        - save
      when:
        - os: mac
    "<winLocalAppData>/Packages/TeamCherry/SystemAppData/wgs":
      tags:
        - save
      when:
        - os: windows
          store: microsoft
    "<xdgConfig>/unity3d/Team Cherry/Hollow Knight/*.dat":
      tags:
        - save
      when:
        - os: linux
  installDir:
    Hollow Knight: {}
  steam:
    id: 367520
"Stardew Valley":
  files:
    "<winAppData>/StardewValley/Saves":
      tags:
        - save
      when:
        - os: windows
    "<root>/userdata/<storeUserId>/413150/remote":
      tags:
        - save
  installDir:
    Stardew Valley: {}
  steam:
    id: 413150
"Only Linux":
  files:
    "<xdgData>/OnlyLinux":
      tags:
        - save
"Somebody's Game":
  files:
    "<winDocuments>/My Games/Somebody/<storeUserId>/save.sav": {}
  installDir:
    SBGAME: {}
"""


@pytest.fixture
def game(tmp_path):
    folder = tmp_path / "Windows Games" / "Hollow Knight"
    folder.mkdir(parents=True)
    (folder / "game.exe").write_text("x")
    return WindowsGame(folder, "Hollow Knight")


def home(game, user=""):
    folder = library.prefix_dir(game, user) / "pfx" / "drive_c" / "users" / "steamuser"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def write(path, text="x", age=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if age:
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
    return path


# --- finding the files -------------------------------------------------------------------------

def test_places_match_ignoring_case_with_wildcards(game):
    folder = home(game)
    write(folder / "AppData/LocalLow/team cherry/Hollow Knight/user1.dat")
    write(folder / "AppData/LocalLow/team cherry/Hollow Knight/user1.dat.bak")
    write(folder / "Documents/My Games/X/123/deep/save.sav")
    assert [p.name for p in places.matches(folder, "AppData/LocalLow/Team Cherry/Hollow Knight/*.dat")] == ["user1.dat"]
    assert [p.name for p in places.matches(folder, "Documents/my games/X/**/*.sav")] == ["save.sav"]
    assert places.matches(folder, "AppData/Roaming/Nothing") == []


def test_links_are_not_followed(game, tmp_path):
    folder = home(game)
    outside = write(tmp_path / "real home" / "Documents" / "private.txt").parent
    (folder / "Documents").symlink_to(outside)  # plain Wine links Documents to the real home
    assert places.files(game, "", [Location("home", "Documents")]) == []


def test_files_and_size_of_the_saves_only(game):
    folder = home(game)
    write(folder / "AppData/Roaming/StardewValley/Saves/Farm_1/Farm_1", "12345")
    write(folder / "AppData/Roaming/StardewValley/Saves/Farm_1/SaveGameInfo", "123")
    write(library.prefix_dir(game) / "pfx/drive_c/windows/system32/big.dll", "x" * 1000)
    write(game.path / "Saves" / "slot1.sav", "ab")
    found = [Location("home", "AppData/Roaming/StardewValley/Saves"), Location("game", "Saves")]
    assert len(places.files(game, "", found)) == 3
    size, newest = places.measure(game, "", found)
    assert size == 10 and newest > 0
    assert places.measure(game, "someone else", found)[0] == 2  # the game's folder is everybody's


# --- learning from playing ---------------------------------------------------------------------

def test_what_the_game_wrote_while_it_ran_is_learned(game):
    folder = home(game)
    write(folder / "AppData/LocalLow/Team Cherry/Hollow Knight/old.txt", age=3600)  # from before
    started = time.time()
    write(folder / "AppData/LocalLow/Team Cherry/Hollow Knight/user1.dat")
    write(folder / "AppData/Roaming/StardewValley/Saves/Farm/Farm")
    write(folder / "Documents/My Games/Skyrim/Saves/save1.ess")
    write(game.path / "Saves" / "slot1.sav")
    new = places.learn(game, "", started)
    assert {(p.root, p.path) for p in new} == {
        ("home", "AppData/LocalLow/Team Cherry/Hollow Knight"), ("home", "AppData/Roaming/StardewValley"),
        ("home", "Documents/My Games/Skyrim"), ("game", "Saves")}
    assert all(p.source == PLAYED for p in places.learned(game))
    assert places.learn(game, "", started) == []  # known now
    assert (library.library_root(game) / places.FILE).is_file()  # on the drive, with the prefixes


def test_caches_logs_and_wine_itself_are_not_saves(game):
    folder = home(game)
    started = time.time()
    write(folder / "AppData/Local/Temp/abc.tmp")
    write(folder / "AppData/Local/D3DSCache/x/y.idx")
    write(folder / "AppData/Roaming/Microsoft/Windows/whatever")
    write(folder / "AppData/LocalLow/Unity/Analytics/values")
    write(folder / "AppData/Local/Game/Logs/game.txt")
    write(folder / "AppData/Local/Game/crash.dmp")
    write(folder / "AppData/LocalLow/Company/Game/Player.log")
    write(folder / "some.reg")
    write(game.path / "game.dxvk-cache")
    write(game.path / "shadercache" / "a.bin")
    write(game.path / "output_log.txt")
    assert places.learn(game, "", started) == []


def test_a_game_that_updated_itself_doesnt_teach_its_whole_folder(game, monkeypatch):
    monkeypatch.setattr(places, "MAX_GAME_FILES", 5)
    started = time.time()
    for n in range(10):
        write(game.path / "Data" / f"part{n}.pak")
    assert places.learn(game, "", started) == []


def test_an_outer_folder_replaces_one_learned_inside_it(game):
    started = time.time()
    write(game.path / "Saves" / "1" / "a.sav")
    assert [p.path for p in places.learn(game, "", started)] == ["Saves/1"]
    write(game.path / "Saves" / "b.sav")
    assert [p.path for p in places.learn(game, "", started)] == ["Saves"]
    assert [p.path for p in places.learned(game)] == ["Saves"]


def test_removed_places_are_not_shown_nor_learned_again(game):
    folder = home(game)
    started = time.time()
    write(folder / "AppData/Roaming/Launcher/state.json")
    [place] = places.learn(game, "", started)
    places.remove(game, place)
    assert places.known(game) == []
    assert places.learn(game, "", started) == []
    places.bring_back(game)
    assert places.known(game) == [] and places.removed(game) == set()  # (learned anew)
    assert [p.path for p in places.learn(game, "", started)] == ["AppData/Roaming/Launcher"]


def test_learned_places_inside_the_lists_are_not_shown_twice(game):
    started = time.time()
    write(game.path / "Saves" / "slot1.sav")
    listed = [Location("game", "Saves", LISTED)]
    assert places.learn(game, "", started, listed) == []
    assert places.known(game, listed) == listed


def test_no_learned_folder_around_the_lists_files(game):
    folder = home(game)
    write(folder / "AppData/LocalLow/Team Cherry/Hollow Knight/user1.dat")
    listed = [Location("home", "AppData/LocalLow/Team Cherry/Hollow Knight/*.dat", LISTED)]
    assert places.learn(game, "", time.time() - 60, listed) == []  # the list knows which files are saves
    places.learn(game, "", time.time() - 60)  # (learned before the list was there)
    assert places.known(game, listed) == listed


# --- the list ----------------------------------------------------------------------------------

def test_the_list_boiled_down_to_windows_places():
    data = save_manifest.boil_down(LIST.splitlines(keepends=True))
    assert set(data["games"]) == {"Hollow Knight", "Stardew Valley", "Somebody's Game"}  # no Windows places: out
    assert data["games"]["Hollow Knight"] == {"steam": 367520, "files": [
        ["game", "hollow_knight_Data/Config.ini", SETTINGS],
        ["home", "AppData/LocalLow/Team Cherry/Hollow Knight/*.dat", "save"]]}  # not the Mac's, nor the Store's
    assert data["games"]["Stardew Valley"]["files"] == [["home", "AppData/Roaming/StardewValley/Saves", "save"]]
    assert data["games"]["Somebody's Game"]["files"] == [["home", "Documents/My Games/Somebody/*/save.sav", "save"]]


@pytest.mark.parametrize("place, expected", [
    ("<winAppData>/A/B", ("home", "AppData/Roaming/A/B")),
    ("<winProgramData>/A", ("drive_c", "ProgramData/A")),
    ("<base>/save", ("game", "save")),
    ("<home>/.config/a", None),
    ("<root>/userdata", None),
    ("<base>/../escape", None),
    ("<base>", None),
])
def test_translating_the_lists_places(place, expected):
    assert save_manifest.translate(place) == expected


def fake_get(text, calls=None):
    class Response:
        def raise_for_status(self):
            if text is None:
                raise OSError("offline")

        def iter_content(self, size):
            yield text.encode()

    def get(url):
        if calls is not None:
            calls.append(url)
        return Response()

    return get


def test_fetched_once_kept_and_found_by_folder_name_or_steam_game(tmp_path, game):
    calls = []
    assert save_manifest.fetch(tmp_path, fake_get(LIST, calls))
    assert save_manifest.fetch(tmp_path, fake_get(LIST, calls)) and len(calls) == 1  # fresh: not again
    with gzip.open(save_manifest.path(tmp_path), "rt") as file:
        assert "Hollow Knight" in json.load(file)["games"]
    title, found = save_manifest.for_game(game, tmp_path)
    assert title == "Hollow Knight" and [p.source for p in found] == [LISTED, LISTED]
    folder = tmp_path / "SBGAME_v1.0.2 [GOG]"
    folder.mkdir()
    assert save_manifest.for_game(WindowsGame(folder, folder.name), tmp_path)[0] == "Somebody's Game"
    other = tmp_path / "Farm thing"
    other.mkdir()
    assert save_manifest.for_game(WindowsGame(other, other.name), tmp_path, steam_appid=413150)[0] == "Stardew Valley"
    assert save_manifest.for_game(WindowsGame(other, other.name), tmp_path) == (None, [])


def test_without_the_list_offline_nothing_breaks(tmp_path, game):
    cache = tmp_path / "cache"
    assert not save_manifest.fetch(cache, fake_get(None), force=True)
    assert save_manifest.for_game(game, cache) == (None, [])
    assert save_manifest.fetch(cache, fake_get(LIST), force=True)
    assert os.listdir(cache) == [save_manifest.FILE]  # no leftovers
    assert save_manifest.fetch(cache, fake_get("<html>rate limited</html>"), force=True)  # the old one stays
    assert save_manifest.for_game(game, cache)[0] == "Hollow Knight"


# --- shown with the saves ----------------------------------------------------------------------

def test_the_overview_counts_the_saves_themselves(game):
    folder = home(game)
    write(folder / "AppData/LocalLow/Team Cherry/Hollow Knight/user1.dat", "x" * 100)
    write(library.prefix_dir(game) / "pfx/drive_c/windows/big.dll", "x" * 5000)
    box = saves.PrefixSaves(game)
    [row] = saves.overview(box, [""])
    assert row.own is None  # where it saves isn't known yet
    started = time.time() - 60
    places.learn(game, "", started)
    [row] = saves.overview(box, [""])
    assert row.own == 100 and row.size > 5000


def test_saves_page_shows_where_it_saves_and_the_admin_removes_a_place(qtbot, game):
    from gamingcrypt.users import User
    from tests.test_saves import confirm, open_page

    folder = home(game)
    write(folder / "AppData/Roaming/Thing/save.dat", "x" * 10)
    places.learn(game, "", time.time() - 60)
    people = [User("admin", "Admin", "pin", admin=True), User("u1", "Mia", "pin")]
    _tab, page = open_page(qtbot, game, saves.PrefixSaves(game), people, people[0])
    key = ("", "place", "home:AppData/Roaming/Thing")
    qtbot.waitUntil(lambda: key in page.buttons)
    assert next(r for r in page.found if r.user == "").own == 10
    page.buttons[key].click()
    confirm(qtbot, page, "isn't where Hollow Knight saves")
    qtbot.waitUntil(lambda: ("", "places back", "") in page.buttons)
    assert places.known(game) == [] and key not in page.buttons
    page.buttons[("", "places back", "")].click()
    qtbot.waitUntil(lambda: "are back" in page.status.text())


def test_a_user_sees_where_it_saves_but_cant_remove(qtbot, game):
    from gamingcrypt.users import User
    from tests.test_saves import open_page

    write(home(game, "u1") / "AppData/Roaming/Thing/save.dat")
    places.learn(game, "u1", time.time() - 60)
    people = [User("admin", "Admin", "pin", admin=True), User("u1", "Mia", "pin")]
    _tab, page = open_page(qtbot, game, saves.PrefixSaves(game), people, people[1])
    qtbot.waitUntil(lambda: bool(page.found) and page.found[0].own is not None)
    assert not any(what == "place" for _u, what, _w in page.buttons)

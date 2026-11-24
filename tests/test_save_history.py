"""Versions of a user's saves: which device made each, and which it came from - what to play with when
another device played on, and when both did."""

import shutil
import time

import pytest

from gamingcrypt import save_history as sh
from gamingcrypt import save_locations
from gamingcrypt.save_locations import SETTINGS, Location
from gamingcrypt.wine import library
from gamingcrypt.wine.library import WindowsGame

PLACES = [Location("home", "AppData/Roaming/Game"), Location("game", "Saves"),
          Location("home", "AppData/Roaming/Game/settings.ini", kind=SETTINGS)]


def make_game(root):
    folder = root / "Windows Games" / "Game"
    folder.mkdir(parents=True)
    (folder / "game.exe").write_text("x")
    return WindowsGame(folder, "Game")


@pytest.fixture
def game(tmp_path):
    return make_game(tmp_path / "deck")


@pytest.fixture
def other(tmp_path):
    return make_game(tmp_path / "desktop")


def home(game, user=""):
    return library.prefix_dir(game, user) / "pfx/drive_c/users/steamuser"


def save(game, name, text, user=""):
    path = home(game, user) / "AppData/Roaming/Game" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def read(game, name, user=""):
    path = home(game, user) / "AppData/Roaming/Game" / name
    return path.read_text() if path.exists() else None


def deck(game, keep=sh.KEEP):
    return sh.History(game, "", PLACES, ("deck", "Deck"), keep)


def desktop(game):
    return sh.History(game, "", PLACES, ("desktop", "Desktop"))


def exchange(a: sh.History, b: sh.History) -> None:
    """What a later sync will do: each one's versions and files copied to the other (not its state)."""
    for source, target in ((a, b), (b, a)):
        for part in ("versions", "objects"):
            if (source.folder / part).exists():
                shutil.copytree(source.folder / part, target.folder / part, dirs_exist_ok=True)


def test_a_version_only_when_something_changed(game):
    history = deck(game)
    assert history.record() is None  # no saves, never were
    save(game, "slot1.sav", "level 1")
    first = history.record()
    assert first.id == "deck-000001" and first.parents == [] and list(first.files) == [
        "home/AppData/Roaming/Game/slot1.sav"]
    assert history.record() is None and history.head == first.id
    save(game, "slot1.sav", "level 2")
    second = history.record()
    assert second.parents == [first.id] and second.counter == 2
    assert history.check() == (sh.SAME, [])


def test_settings_arent_saves(game):
    save(game, "settings.ini", "1280x800")
    save(game, "slot1.sav", "x")
    assert list(deck(game).record().files) == ["home/AppData/Roaming/Game/slot1.sav"]


def test_unchanged_files_are_stored_once_and_not_read_again(game, monkeypatch):
    history = deck(game)
    save(game, "big.sav", "x" * 1000)
    save(game, "slot1.sav", "a")
    history.record()
    hashed = []
    real = sh._hash
    monkeypatch.setattr(sh, "_hash", lambda path: hashed.append(path.name) or real(path))
    save(game, "slot1.sav", "b")
    history.record()
    assert "big.sav" not in hashed
    objects = [p for p in (history.folder / "objects").rglob("*") if p.is_file()]
    assert len(objects) == 3  # big once, a, b


def test_played_on_elsewhere_is_taken_before_playing(game, other):
    here, there = deck(game), desktop(other)
    save(game, "slot1.sav", "level 1")
    here.record()
    exchange(here, there)
    assert there.check()[0] == sh.NEWER  # none there yet: the deck's
    there.take(there.check()[1][0].id)
    assert read(other, "slot1.sav") == "level 1"
    save(other, "slot1.sav", "level 5")
    save(other, "slot2.sav", "new game")
    there.record()
    exchange(here, there)
    state, [newer] = here.check()
    assert state == sh.NEWER and newer.device_name == "Desktop"
    here.take(newer.id)
    assert read(game, "slot1.sav") == "level 5" and read(game, "slot2.sav") == "new game"
    assert here.check() == (sh.SAME, [])


def test_a_save_deleted_elsewhere_goes_here_too(game, other):
    here, there = deck(game), desktop(other)
    save(game, "slot1.sav", "a")
    save(game, "slot2.sav", "b")
    here.record()
    exchange(here, there)
    there.take(there.check()[1][0].id)
    (home(other) / "AppData/Roaming/Game/slot2.sav").unlink()
    there.record()
    exchange(here, there)
    here.take(here.check()[1][0].id)
    assert read(game, "slot1.sav") == "a" and read(game, "slot2.sav") is None


def test_played_on_in_both_places_the_user_chooses(game, other):
    here, there = deck(game), desktop(other)
    save(game, "slot1.sav", "start")
    here.record()
    exchange(here, there)
    there.take(there.check()[1][0].id)
    save(game, "slot1.sav", "deck went left")
    here.record()
    save(other, "slot1.sav", "desktop went right")
    there.record()
    exchange(here, there)
    state, versions = here.check()
    assert state == sh.CONFLICT and [v.device for v in versions] == ["deck", "desktop"]
    chosen = here.choose(versions[1].id)
    assert read(game, "slot1.sav") == "desktop went right"
    assert set(chosen.parents) == {versions[0].id, versions[1].id}  # decided, for every device
    assert here.check() == (sh.SAME, [])
    exchange(here, there)
    state, [newer] = there.check()
    assert state == sh.NEWER and newer.id == chosen.id  # the desktop doesn't ask again
    there.take(newer.id)
    assert there.check() == (sh.SAME, [])
    assert any(v.content() == versions[0].content() for v in here.versions().values())  # the other one stays


def test_saves_changed_outside_the_game_count_before_playing(game, other):
    here, there = deck(game), desktop(other)
    save(game, "slot1.sav", "a")
    here.record()
    exchange(here, there)
    save(other, "slot1.sav", "copied in by hand")  # never a version: the desktop played without GamingCrypt
    state, versions = there.check()
    assert state == sh.CONFLICT and versions[0].why == sh.FOUND  # not simply overwritten


def test_going_back_to_an_older_version(game):
    history = deck(game)
    save(game, "slot1.sav", "old")
    old = history.record()
    save(game, "slot1.sav", "new")
    save(game, "slot2.sav", "also new")
    new = history.record()
    back = history.go_back(old.id)
    assert read(game, "slot1.sav") == "old" and read(game, "slot2.sav") is None
    assert back.parents == [new.id] and back.why == sh.RESTORED and history.head == back.id
    with pytest.raises(sh.HistoryError):
        history.go_back(back.id)  # (already)
    history.go_back(new.id)
    assert read(game, "slot2.sav") == "also new"


def test_only_the_newest_keep_their_files(game):
    history = deck(game, keep=3)
    for n in range(6):
        save(game, "slot1.sav", f"version {n}")
        history.record()
    versions = history.newest_first()
    assert len(versions) == 6 and [v.kept for v in versions] == [True] * 3 + [False] * 3
    assert len([p for p in (history.folder / "objects").rglob("*") if p.is_file()]) == 3
    with pytest.raises(sh.HistoryError, match="aren't kept"):
        history.go_back(versions[-1].id)
    assert read(game, "slot1.sav") == "version 5"


def test_a_device_that_never_ran_the_game_gets_the_folder(game, other):
    here, there = deck(game), desktop(other)
    save(game, "slot1.sav", "a")
    here.record()
    exchange(here, there)
    assert not library.prefix_dir(other).exists()
    there.take(there.check()[1][0].id)
    assert read(other, "slot1.sav") == "a"


def test_users_have_their_own_history(game):
    save(game, "slot1.sav", "admin's")
    save(game, "slot1.sav", "mia's", user="u1")
    sh.History(game, "", PLACES, ("deck", "Deck")).record()
    mia = sh.History(game, "u1", PLACES, ("deck", "Deck"))
    assert mia.check() == (sh.SAME, []) and len(mia.versions()) == 1


def test_this_device_is_named_once(tmp_path):
    first = sh.device(tmp_path)
    assert sh.device(tmp_path) == first and len(first[0]) == 12 and first[1]


def test_the_game_folders_saves_too(game):
    (game.path / "Saves").mkdir()
    (game.path / "Saves" / "a.sav").write_text("x")
    assert list(deck(game).record().files) == ["game/Saves/a.sav"]


def test_for_game_uses_the_known_places(game):
    started = time.time() - 60
    save(game, "slot1.sav", "x")
    save_locations.learn(game, "", started)
    assert sh.for_game(game).record() is not None


def test_saves_page_shows_the_history_and_goes_back(qtbot, game):
    from gamingcrypt import saves
    from gamingcrypt.users import User
    from tests.test_saves import confirm, open_page

    started = time.time() - 60
    save(game, "slot1.sav", "old")
    save_locations.learn(game, "", started)
    history = sh.for_game(game)
    old = history.record()
    save(game, "slot1.sav", "new")
    new = history.record()
    people = [User("admin", "Admin", "pin", admin=True)]
    _tab, page = open_page(qtbot, game, saves.PrefixSaves(game), people, people[0])
    qtbot.waitUntil(lambda: ("", "version", old.id) in page.buttons)
    assert ("", "version", new.id) not in page.buttons  # (that's what's there now)
    page.buttons[("", "version", old.id)].click()
    confirm(qtbot, page, "Play on from the saves of")
    qtbot.waitUntil(lambda: "Those are the saves now" in page.status.text())
    assert read(game, "slot1.sav") == "old"
    qtbot.waitUntil(lambda: page.found and page.found[0].versions == 3)

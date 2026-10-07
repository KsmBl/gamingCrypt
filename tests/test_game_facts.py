"""Genres, release year and platform of the installed games - and the Games tab's filters."""

import calendar
import time

import pytest
import requests

from gamingcrypt import game_facts
from gamingcrypt.game_facts import Facts
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.wine import covers as pc_covers
from gamingcrypt.wine.library import WindowsGame
from tests.fakes import FakeService


def stamp(year: int) -> int:
    return calendar.timegm((year, 6, 1, 0, 0, 0))


class Response:
    def __init__(self, data=None, status=200, content=b""):
        self.data, self.status_code, self.content = data, status, content

    def json(self):
        return self.data


# --- the facts ------------------------------------------------------------------------------------

def test_choose_by_genre_platform_and_decade():
    games = [SteamGame(1, "Burnout"), SteamGame(2, "Asteroids"), SteamGame(3, "Celeste"), SteamGame(4, "Doom")]
    facts = {1: Facts("Steam", ("Racing",), 2008), 2: Facts("SNES", (), None),
             3: Facts("Windows", ("Platformer", "Indie"), 2018), 4: Facts("Steam", ("Action",), 1993)}
    names = lambda found: [g.name for g in found]  # noqa: E731
    assert names(game_facts.choose(games, facts)) == ["Asteroids", "Burnout", "Celeste", "Doom"]
    assert names(game_facts.choose(games, facts, genre="Indie")) == ["Celeste"]
    assert names(game_facts.choose(games, facts, platform="Steam")) == ["Burnout", "Doom"]
    assert names(game_facts.choose(games, facts, decade="2000")) == ["Burnout"]
    assert names(game_facts.choose(games, facts, decade="1990")) == ["Doom"]
    assert names(game_facts.choose(games, facts, decade="old")) == []  # (unknown years in none)
    assert names(game_facts.choose(games, facts, sort="newest")) == ["Celeste", "Burnout", "Doom", "Asteroids"]
    assert names(game_facts.choose(games, facts, sort="oldest")) == ["Doom", "Burnout", "Celeste", "Asteroids"]
    assert game_facts.all_genres(facts) == ["Action", "Indie", "Platformer", "Racing"]
    assert game_facts.all_platforms(facts) == ["Steam", "Windows", "SNES"]


def test_last_played_first():
    games = [SteamGame(1, "A", last_played=100), SteamGame(2, "B"), SteamGame(3, "C", last_played=300)]
    facts = {g.appid: Facts("Steam") for g in games}
    assert [g.name for g in game_facts.choose(games, facts, sort="played")] == ["C", "A", "B"]


# --- Windows / Linux games: the Steam game their cover was matched to -----------------------------------

@pytest.fixture
def root(tmp_path):
    root = tmp_path / "Windows Games"
    (root / "Hollow Knight").mkdir(parents=True)
    return root


def store(found=True, offline=False):
    asked = []

    def get(url, params=None):
        asked.append(url)
        if offline:
            import requests

            raise requests.ConnectionError("no network")
        if url == pc_covers.SEARCH:
            return Response({"items": [{"id": 367520, "name": "Hollow Knight"}] if found else []})
        return Response(content=b"\xff\xd8\xff\xe0jpeg")
    get.asked = asked
    return get


def test_the_match_is_kept(root):
    covers = pc_covers.Covers(root, get=store(), now=lambda: 1000)
    knight = WindowsGame(root / "Hollow Knight", "Hollow Knight")
    assert covers.known_appid(knight) is None
    covers.fetch(knight)
    assert covers.known_appid(knight) == 367520


def test_games_covered_before_are_matched_once(root):
    get = store()
    covers = pc_covers.Covers(root, get=get, now=lambda: 1000)
    knight = WindowsGame(root / "Hollow Knight", "Hollow Knight")
    assert covers.match_appid(knight) == 367520 and covers.match_appid(knight) == 367520
    assert get.asked == [pc_covers.SEARCH]
    assert pc_covers.Covers(root, get=store(offline=True)).match_appid(
        WindowsGame(root / "Other", "Other")) is None  # offline: not remembered
    homebrew = WindowsGame(root / "My Homebrew", "My Homebrew")
    assert pc_covers.Covers(root, get=store(found=False)).match_appid(homebrew) == 0


def test_facts_of_every_kind(root, tmp_path):
    from gamingcrypt.emulation.library import EmulationPaths, scan
    from gamingcrypt.emulation.systems import BY_ID

    service = FakeService(games=[], metadata={367520: {"genres": ["Metroidvania"], "release_date": stamp(2017)}})
    service.fetched.append(367520)

    class Tab:
        windows_covers = pc_covers.Covers(root)

    Tab.service = service
    knight = WindowsGame(root / "Hollow Knight", "Hollow Knight")
    Tab.windows_covers._remember(knight, 367520)
    assert game_facts.facts_of(knight, Tab) == Facts("Windows", ("Metroidvania",), 2017)
    assert game_facts.facts_of(WindowsGame(root / "x", "x"), Tab) == Facts("Windows")
    steam = SteamGame(5, "Racer", release_date=stamp(2004), genres=["Racing"])
    assert game_facts.facts_of(steam, Tab) == Facts("Steam", ("Racing",), 2004)
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms_for(BY_ID["snes"]) / "Mario.sfc").write_bytes(b"x")
    assert game_facts.facts_of(scan(paths, BY_ID["snes"])[0], Tab) == Facts("SNES")


# --- the Games tab ----------------------------------------------------------------------------------

def tab_with(qtbot, games, metadata=None, **kw):
    from gamingcrypt.ui.games_tab import GamesTab

    service = FakeService(games=games, metadata=metadata or {})
    tab = GamesTab(service, **kw)
    tab.FACTS_DELAY_MS = 1
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: len(tab.home.installed) == len([g for g in games if g.installed]))
    return tab


def shown(tab):
    return [tab.home.cards[a].game.name for a in tab.home.result_appids]


@pytest.mark.store_facts
def test_genres_are_fetched_and_filter_the_installed_games(qtbot):
    games = [SteamGame(1, "Burnout", installed=True), SteamGame(2, "Celeste", installed=True),
             SteamGame(3, "Doom", installed=True), SteamGame(4, "Not installed")]
    metadata = {1: {"genres": ["Racing"], "release_date": stamp(2008)},
                2: {"genres": ["Indie", "Platformer"], "release_date": stamp(2018)},
                3: {"genres": ["Action"], "release_date": stamp(1993)},
                4: {"genres": ["Strategy"]}}
    tab = tab_with(qtbot, games, metadata)
    home = tab.home
    qtbot.waitUntil(lambda: sorted(tab.service.fetched) == [1, 2, 3])  # the installed ones, by themselves
    qtbot.waitUntil(lambda: home.genre_combo.count() == 5)
    assert [home.genre_combo.itemText(i) for i in range(5)] == ["All genres", "Action", "Indie", "Platformer",
                                                                "Racing"]
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Indie"))
    assert shown(tab) == ["Celeste"] and home.results_heading.text() == "Installed games · 1 of 3"
    assert not home.sources.isVisible()  # the results first, as while searching
    home.genre_combo.setCurrentIndex(0)
    home.decade_combo.setCurrentIndex(home.decade_combo.findData("1990"))
    assert shown(tab) == ["Doom"]
    home.decade_combo.setCurrentIndex(0)
    home.sort_combo.setCurrentIndex(home.sort_combo.findData("newest"))
    assert shown(tab) == ["Celeste", "Burnout", "Doom"] and home.sources.isVisible()  # sorting isn't filtering
    home.decade_combo.setCurrentIndex(home.decade_combo.findData("2020"))
    assert shown(tab) == [] and "matches these filters" in home.empty_label.text()


@pytest.mark.store_facts
def test_platform_filter_with_emulated_and_windows_games(qtbot, tmp_path):
    from gamingcrypt.emulation.library import EmulationPaths
    from gamingcrypt.emulation.systems import BY_ID

    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    (paths.roms_for(BY_ID["snes"]) / "Super Mario World (USA).sfc").write_bytes(b"x")
    windows = tmp_path / "GamingCrypt" / "Windows Games"
    (windows / "Hollow Knight").mkdir(parents=True)
    (windows / "Hollow Knight" / "hk.exe").write_bytes(b"MZ")
    (windows / ".covers").mkdir()
    (windows / ".covers" / "Hollow Knight.appid").write_text("367520")
    tab = tab_with(qtbot, [SteamGame(1, "Burnout", installed=True)],
                   {1: {"genres": ["Racing"]}, 367520: {"genres": ["Metroidvania"], "release_date": stamp(2017)}},
                   emulation_root=str(paths.root), windows_root=str(windows))
    home = tab.home
    qtbot.waitUntil(lambda: home.platform_combo.count() == 4)
    assert [home.platform_combo.itemText(i) for i in range(4)] == ["All platforms", "Steam", "Windows", "SNES"]
    qtbot.waitUntil(lambda: 367520 in tab.service.fetched)  # the store page of the Steam game it matched
    qtbot.waitUntil(lambda: home.genre_combo.findData("Metroidvania") > 0)
    home.platform_combo.setCurrentIndex(home.platform_combo.findData("SNES"))
    assert shown(tab) == ["Super Mario World"]
    home.platform_combo.setCurrentIndex(0)
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Metroidvania"))
    assert shown(tab) == ["Hollow Knight"]


@pytest.mark.store_facts
def test_a_chosen_genre_stays_chosen_while_the_list_changes(qtbot):
    tab = tab_with(qtbot, [SteamGame(1, "Burnout", installed=True)], {1: {"genres": ["Racing"]}})
    home = tab.home
    qtbot.waitUntil(lambda: home.genre_combo.findData("Racing") > 0)
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Racing"))
    home.set_installed([])  # e.g. uninstalled
    assert home.genre_combo.currentData() == "Racing" and shown(tab) == []


@pytest.mark.store_facts
def test_the_list_isnt_redrawn_for_new_genres_unless_filtered(qtbot, monkeypatch):
    from gamingcrypt.ui.games_tab import GamesHome

    redrawn = []
    original = GamesHome.refresh_results
    monkeypatch.setattr(GamesHome, "refresh_results", lambda self: redrawn.append(1) or original(self))
    tab = tab_with(qtbot, [SteamGame(1, "Burnout", installed=True)], {1: {"genres": ["Racing"]}})
    qtbot.waitUntil(lambda: tab.home.genre_combo.findData("Racing") > 0)
    before = len(redrawn)
    qtbot.wait(30)
    assert len(redrawn) == before


# --- emulated games: libretro-database --------------------------------------------------------------

DAT = """clrmamepro (
\tname "Nintendo - Super Nintendo Entertainment System"
)

game (
\tcomment "Super Mario World (USA)"
\tgenre "Platform"
\trom ( crc B19ED489 )
)

game (
\tcomment "Super Mario Kart (USA)"
\tgenre "Racing / Action"
\trom ( crc CD80DB86 )
)
"""
YEARS = DAT.replace('genre "Platform"', 'releaseyear "1990"').replace('genre "Racing / Action"', 'releaseyear "1992"')


def libretro(asked=None, missing=False):
    def get(url):
        if asked is not None:
            asked.append(url)
        if missing:
            return Response(status=404)
        return Response(content=(DAT if "/genre/" in url else YEARS).encode())
    return get


@pytest.fixture
def emu(tmp_path):
    from gamingcrypt.emulation.library import EmulationPaths
    from gamingcrypt.emulation.systems import BY_ID

    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    for name in ("Super Mario World (USA).sfc", "Super Mario Kart (Europe) (Rev 1).sfc", "My Hack.sfc"):
        (paths.roms_for(BY_ID["snes"]) / name).write_bytes(b"x")
    return paths


def test_genres_and_years_of_emulated_games(emu):
    from gamingcrypt.emulation.library import scan
    from gamingcrypt.emulation.rom_facts import RomFacts, parse_dat
    from gamingcrypt.emulation.systems import BY_ID

    assert parse_dat(DAT, "genre") == {"Super Mario World (USA)": "Platform", "Super Mario Kart (USA)": "Racing / Action"}
    asked = []
    facts = RomFacts(emu, get=libretro(asked), now=lambda: 1000)
    games = {g.path.name: g for g in scan(emu, BY_ID["snes"])}
    assert facts.needs_fetch("snes") and facts.facts(games["Super Mario World (USA).sfc"]) == ((), None)
    assert facts.fetch("snes") and len(asked) == 2
    assert facts.facts(games["Super Mario World (USA).sfc"]) == (("Platform",), 1990)  # its exact name
    assert facts.facts(games["Super Mario Kart (Europe) (Rev 1).sfc"]) == (("Racing", "Action"), 1992)  # the title
    assert facts.facts(games["My Hack.sfc"]) == ((), None)
    again = RomFacts(emu, get=libretro(asked), now=lambda: 1000)  # kept on the drive
    assert not again.needs_fetch("snes") and again.facts(games["Super Mario World (USA).sfc"])[1] == 1990
    assert len(asked) == 2
    assert RomFacts(emu, now=lambda: 1000 + 31 * 86400).needs_fetch("snes")  # after a while: again


def test_systems_libretro_has_nothing_for(emu):
    from gamingcrypt.emulation.rom_facts import RomFacts

    facts = RomFacts(emu, get=libretro(missing=True), now=lambda: 1000)
    assert facts.fetch("ps2") and not facts.needs_fetch("ps2")  # (asked once, not again and again)

    def offline(url):
        raise requests.ConnectionError("no network")

    assert not RomFacts(emu, get=offline).fetch("snes") and RomFacts(emu).needs_fetch("snes")


@pytest.mark.store_facts
def test_emulated_games_in_the_genre_filter(qtbot, emu, monkeypatch):
    from gamingcrypt.emulation import rom_facts

    asked = []
    original = rom_facts.RomFacts.__init__
    monkeypatch.setattr(rom_facts.RomFacts, "__init__", lambda self, paths, get=None, now=time.time:
                        original(self, paths, get=libretro(asked), now=now))
    tab = tab_with(qtbot, [], emulation_root=str(emu.root))
    home = tab.home
    qtbot.waitUntil(lambda: home.genre_combo.findData("Platform") > 0)
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Racing"))
    assert shown(tab) == ["Super Mario Kart"]
    home.genre_combo.setCurrentIndex(0)
    home.decade_combo.setCurrentIndex(home.decade_combo.findData("1990"))
    assert sorted(shown(tab)) == ["Super Mario Kart", "Super Mario World"]

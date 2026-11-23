"""A user with an age sees only the games rated for it (gamingcrypt/ratings.py)."""

import copy
import os
import json

import pytest

from gamingcrypt import ratings, users
from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.steam.models import SteamGame
from tests.fakes import FakeService


def test_steps():
    assert [ratings.step_for(a) for a in (0, 3, 6, 7, 12, 13, 16, 17, 18, 21)] == [0, 6, 6, 12, 12, 16, 16, 18, 18, 18]
    assert ratings.step_for("16") == 16 and ratings.step_for("BANNED") is None and ratings.step_for(None) is None
    assert [ratings.from_esrb(c) for c in ("EC", "E", "KA", "E10+", "T", "M", "AO")] == [0, 6, 6, 12, 12, 16, 18]
    assert ratings.from_esrb("RP") is None and ratings.from_esrb(None) is None and ratings.from_esrb(" t ") == 12


def test_rating_from_the_store_page():
    assert ratings.from_store({"ratings": {"usk": {"rating": "16"}, "steam_germany": {"rating": "18"}}}) == 16
    assert ratings.from_store({"ratings": {"steam_germany": {"rating": "12"}}, "required_age": 0}) == 12
    assert ratings.from_store({"ratings": {"usk": {"rating": "0"}}}) == 0  # rated, for everybody
    assert ratings.from_store({"required_age": "18"}) == 18 and ratings.from_store({"required_age": 17}) == 18
    assert ratings.from_store({"required_age": 0}) is None  # no age gate isn't a rating
    assert ratings.from_store({"ratings": {"usk": {"rating": "BANNED"}}}) is None and ratings.from_store({}) is None
    assert ratings.from_store({"ratings": None, "required_age": None}) is None


def test_store_details_carry_the_rating():
    from gamingcrypt.steam.webapi import SteamWebAPI

    class Session:
        def get(self, url, params=None, timeout=None):
            data = {"620": {"success": True, "data": {"name": "Portal 2", "ratings": {"usk": {"rating": "12"}}}}}

            class Response:
                status_code = 200

                def json(self):
                    return data

                def raise_for_status(self):
                    pass

            return Response()

    assert SteamWebAPI(session=Session()).app_details(620)["age"] == 12


def test_metadata_from_before_is_fetched_again_for_its_rating(tmp_path):
    from gamingcrypt.steam.service import SteamService

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "steam_metadata.json").write_text(json.dumps({"620": {
        "storage_bytes": 1, "genres": ["Puzzle"], "fetched_at": 10 ** 10}}))  # no "age" yet
    service = SteamService(copy.deepcopy(DEFAULTS["steam"]), cache)
    assert service.needs_metadata(SteamGame(620, "Portal 2"))
    service.api.app_details = lambda appid: {"genres": ["Puzzle"], "storage_bytes": 1, "age": 12}
    service.api.latest_news_date = lambda appid: None
    assert service.fetch_metadata(620)["age"] == 12 and not service.needs_metadata(SteamGame(620, "Portal 2"))
    assert service.apply_metadata(SteamGame(620, "Portal 2")).age == 12


# --- the Games tab -------------------------------------------------------------------------------

DAT = "\n".join(f'game (\n\tcomment "{name}"\n\tesrb_rating "{code}"\n\trom ( crc 0 )\n)\n' for name, code in (
    ("Super Mario World (USA)", "KA"), ("Mortal Kombat (USA)", "M"), ("Chrono Trigger (USA)", "T")))


@pytest.fixture
def emu(tmp_path):
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    for name in ("Super Mario World (USA).sfc", "Mortal Kombat (USA).sfc", "Chrono Trigger (USA).sfc",
                 "Some Homebrew.sfc"):
        (paths.roms_for(BY_ID["snes"]) / name).write_bytes(b"x")
    (paths.config / "metadata").mkdir(parents=True)
    from gamingcrypt.emulation.rom_facts import parse_dat

    (paths.config / "metadata" / "snes.json").write_text(json.dumps({
        "fetched": 1000, "genre": {}, "releaseyear": {}, "esrb": parse_dat(DAT, "esrb_rating")}))
    return paths


def user(age):
    return users.User("u1", "Mia", "pin", age=age)


STEAM = [SteamGame(1, "Kids Game", installed=True, last_played=50), SteamGame(2, "Teen Game", installed=True),
         SteamGame(3, "Adult Game", installed=True, last_played=99), SteamGame(4, "Unrated Game", installed=True),
         SteamGame(5, "Owned Kids Game")]
AGES = {1: {"age": 0}, 2: {"age": 12}, 3: {"age": 18}, 5: {"age": 6}}


def tab_for(qtbot, emu, who, **kw):
    from gamingcrypt.ui.games_tab import GamesTab

    service = FakeService(games=copy.deepcopy(STEAM), metadata=copy.deepcopy(AGES))
    service.fetched = list(AGES)  # their store pages were looked at before (kept on disk in the app)
    tab = GamesTab(service, emulation_root=str(emu.root), user=who, **kw)
    tab.rom_facts.now = lambda: 2000
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: bool(tab._all_roms))
    qtbot.waitUntil(lambda: bool(tab.home.installed))
    return tab


def names(games):
    return sorted(g.name for g in games)


def test_the_esrb_list_rates_emulated_games(qtbot, emu):
    tab = tab_for(qtbot, emu, None)
    by_name = {g.name: g for g in tab.roms["snes"]}
    assert ratings.age_of(by_name["Super Mario World"], tab) == 6 and ratings.age_of(by_name["Mortal Kombat"], tab) == 16
    assert ratings.age_of(by_name["Chrono Trigger"], tab) == 12 and ratings.age_of(by_name["Some Homebrew"], tab) is None
    assert len(tab.roms["snes"]) == 4 and len(tab.home.installed) == 4  # the admin: everything
    assert ratings.allowed(by_name["Mortal Kombat"], tab)


@pytest.mark.parametrize("age,roms,steam", [
    (6, ["Super Mario World"], ["Kids Game"]),
    (12, ["Chrono Trigger", "Super Mario World"], ["Kids Game", "Teen Game"]),
    (18, ["Chrono Trigger", "Mortal Kombat", "Super Mario World"], ["Adult Game", "Kids Game", "Teen Game"]),
])
def test_a_user_with_an_age_sees_what_is_rated_for_it(qtbot, emu, age, roms, steam):
    tab = tab_for(qtbot, emu, user(age))
    assert names(tab.roms.get("snes", [])) == roms  # (not rated: not shown either)
    assert names(tab.home.installed) == steam
    assert names(tab.home.all_games()) == sorted(roms + steam)
    assert set(tab.rom_games) == {g.appid for g in tab.roms.get("snes", [])}
    assert len(tab._all_roms["snes"]) == 4  # (what's there is known: its ratings are looked up)


def test_nothing_older_in_continue_playing_or_the_library(qtbot, emu):
    from gamingcrypt import game_profiles

    game_profiles.for_user(user(6)).set(1, "last_played", 50)  # what Mia played herself
    game_profiles.for_user(user(6)).set(3, "last_played", 99)
    tab = tab_for(qtbot, emu, user(6))
    assert tab.home.continue_card.game.name == "Kids Game"  # not the adult game played last
    assert names(tab.service.load_library()) == ["Kids Game", "Owned Kids Game"]
    assert names(tab.service.unrated) == ["Unrated Game"]  # its store page is looked at next
    tab.service.metadata[4] = {"age": 6}  # (what the store will say)
    assert [g.name for kind, g in tab.facts_queue() if kind == "steam"] == ["Unrated Game"]
    tab.service.fetch_metadata(4)
    tab.refilter("steam")  # as after the look-up
    qtbot.waitUntil(lambda: "Unrated Game" in names(tab.home.installed))
    admin_tab = tab_for(qtbot, emu, None)
    assert admin_tab.home.continue_card.game.name == "Adult Game" and len(admin_tab.service.load_library()) == 5


def test_a_user_without_an_age_sees_everything(qtbot, emu):
    tab = tab_for(qtbot, emu, user(None))
    assert len(tab.roms["snes"]) == 4 and len(tab.home.installed) == 4 and tab.age_limit is None
    assert tab.service.unrated == []  # nothing is held back


def test_the_admins_own_rating_counts(qtbot, emu):
    admin_tab = tab_for(qtbot, emu, None, rate_games=True)
    homebrew = next(g for g in admin_tab.roms["snes"] if g.name == "Some Homebrew")
    kombat = next(g for g in admin_tab.roms["snes"] if g.name == "Mortal Kombat")
    admin_tab.open_rom(homebrew)
    page = admin_tab.currentWidget()
    combo = page.rating_row.combo
    assert "not rated" in combo.itemText(0) and [combo.itemData(i) for i in range(combo.count())] == [None, 0, 6, 12, 16, 18]
    combo.setCurrentIndex(combo.findData(0))  # for everybody ("0" is a rating too)
    assert ratings.age_of(homebrew, admin_tab) == 0
    admin_tab.back()
    admin_tab.open_rom(kombat)
    page = admin_tab.currentWidget()
    assert "from 16" in page.rating_row.combo.itemText(0)
    page.rating_row.combo.setCurrentIndex(page.rating_row.combo.findData(18))  # stricter than the list
    kid = tab_for(qtbot, emu, user(16))
    assert names(kid.roms["snes"]) == ["Chrono Trigger", "Some Homebrew", "Super Mario World"]
    admin_tab.currentWidget().rating_row.combo.setCurrentIndex(0)  # automatic again
    assert ratings.age_of(kombat, admin_tab) == 16
    steam_page_tab = tab_for(qtbot, emu, None, rate_games=True)
    steam_page_tab.open_game(4)
    steam_page_tab.currentWidget().rating_row.combo.setCurrentIndex(2)
    assert "Unrated Game" in names(tab_for(qtbot, emu, user(6)).home.installed)


def test_no_rating_row_unless_there_is_someone_to_rate_for(qtbot, emu):
    tab = tab_for(qtbot, emu, None)
    tab.open_rom(tab.roms["snes"][0])
    assert tab.currentWidget().rating_row is None
    kid = tab_for(qtbot, emu, user(18), rate_games=False)
    kid.open_rom(kid.roms["snes"][0])
    assert kid.currentWidget().rating_row is None


def test_the_app_tells_the_tab_who_and_whether_to_rate(monkeypatch):
    from gamingcrypt import app
    from gamingcrypt.ui import games_tab
    from gamingcrypt.unlock import kdf

    seen = {}

    class Probe:
        def __init__(self, service, **kw):
            seen.update(kw)

    monkeypatch.setattr(games_tab, "GamesTab", Probe)
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method="pin", volume=f"/tmp/gamingcrypt-test-{os.getpid()}.vc", kdf=kdf.new_params(n=16))
    app.default_pages(cfg)
    assert seen["user"].admin and seen["rate_games"] is False  # nobody with an age
    master = users.admin_master(cfg, "1234", lambda s: True)
    mia = users.add(cfg, "Mia", "pin", "1111", master, age=12)
    app.default_pages(cfg)
    assert seen["rate_games"] is True
    users.enter(cfg, mia.id)
    app.default_pages(cfg)
    assert seen["user"].id == mia.id and seen["user"].age == 12 and seen["rate_games"] is False

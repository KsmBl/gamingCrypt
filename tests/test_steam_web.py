import json

import pytest
import requests

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.service import SteamService
from gamingcrypt.steam.sorting import filter_games, sort_games
from gamingcrypt.steam.webapi import SteamAPIError, SteamWebAPI, format_price, parse_release_date
from tests.fakes import FakeResponse, FakeSession

OWNED = {"response": {"game_count": 3, "games": [
    {"appid": 620, "name": "Portal 2", "playtime_forever": 2000, "rtime_last_played": 1660000000},
    {"appid": 292030, "name": "The Witcher 3", "playtime_forever": 6000, "rtime_last_played": 0},
    {"appid": 1493710, "name": "Proton Experimental", "playtime_forever": 0},
]}}
DETAILS = {"620": {"success": True, "data": {
    "name": "Portal 2", "is_free": False, "short_description": "Puzzles",
    "release_date": {"coming_soon": False, "date": "18 Apr, 2011"},
    "price_overview": {"currency": "EUR", "initial": 975, "final": 195},
}}}
NEWS = {"appnews": {"newsitems": [{"date": 1720000000}]}}
SEARCH = {"items": [
    {"type": "app", "id": 620, "name": "Portal 2", "price": {"currency": "EUR", "initial": 975, "final": 195}, "tiny_image": "x.jpg"},
    {"type": "app", "id": 570, "name": "Dota 2", "tiny_image": "d.jpg"},
    {"type": "bundle", "id": 1, "name": "Bundle"},
]}


def api(routes, key="k", sid="1"):
    return SteamWebAPI(key, sid, session=FakeSession(routes))


# --- webapi ------------------------------------------------------------------

@pytest.mark.parametrize("text,year", [("18 Apr, 2011", 2011), ("Apr 18, 2011", 2011), ("Q3 2026", None),
                                       ("2020", 2020), ("", None), (None, None)])
def test_parse_release_date(text, year):
    ts = parse_release_date(text)
    if year is None:
        assert ts is None
    else:
        import datetime
        assert datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).year == year


def test_format_price():
    assert format_price(195, "EUR") == "1.95 €"
    assert format_price(999, "USD") == "$9.99"
    assert format_price(0) == "Free"
    assert format_price(None) == "-"


def test_owned_games():
    a = api({"GetOwnedGames": FakeResponse(OWNED)})
    owned = a.owned_games()
    assert owned[0] == {"appid": 620, "name": "Portal 2", "playtime": 2000, "last_played": 1660000000}
    _, params = a.session.requests[0]
    assert params["include_appinfo"] == 1 and params["key"] == "k"


def test_owned_games_requires_key():
    with pytest.raises(SteamAPIError):
        api({}, key="").owned_games()


def test_network_errors_become_api_errors():
    with pytest.raises(SteamAPIError):
        api({"GetOwnedGames": requests.ConnectionError("offline")}).owned_games()
    with pytest.raises(SteamAPIError):
        api({"GetOwnedGames": FakeResponse(status=500)}).owned_games()


def test_app_details():
    d = api({"appdetails": FakeResponse(DETAILS)}).app_details(620)
    assert d["price_cents"] == 195 and d["currency"] == "EUR"
    assert d["release_date"] == parse_release_date("18 Apr, 2011")
    assert d["description"] == "Puzzles"
    assert api({"appdetails": FakeResponse({"620": {"success": False}})}).app_details(620) == {}


def test_app_details_free_and_coming_soon():
    payload = {"1": {"success": True, "data": {"is_free": True, "release_date": {"coming_soon": True, "date": "Soon"}}}}
    d = api({"appdetails": FakeResponse(payload)}).app_details(1)
    assert d["price_cents"] == 0 and d["release_date"] is None


def test_latest_news_date():
    assert api({"GetNewsForApp": FakeResponse(NEWS)}).latest_news_date(620) == 1720000000
    assert api({"GetNewsForApp": FakeResponse({"appnews": {"newsitems": []}})}).latest_news_date(620) is None


def test_search_store():
    items = api({"storesearch": FakeResponse(SEARCH)}).search_store("portal")
    assert [i.appid for i in items] == [620, 570]
    assert items[0].price_cents == 195 and items[0].discounted
    assert items[1].price_cents == 0 and not items[1].discounted
    assert api({}).search_store("   ") == []


# --- sorting -----------------------------------------------------------------

def games():
    return [
        SteamGame(1, "beta", release_date=200, playtime_minutes=5, price_cents=1000, last_updated=None),
        SteamGame(2, "Alpha", release_date=None, playtime_minutes=50, price_cents=0, last_updated=300),
        SteamGame(3, "gamma", release_date=100, playtime_minutes=0, price_cents=None, last_updated=100, installed=True),
    ]


@pytest.mark.parametrize("key,expected", [
    ("name", [2, 1, 3]),
    ("release_date", [1, 3, 2]),
    ("playtime", [2, 1, 3]),
    ("price", [1, 2, 3]),
    ("last_update", [2, 3, 1]),
])
def test_sort_defaults(key, expected):
    assert [g.appid for g in sort_games(games(), key)] == expected


def test_sort_ascending_keeps_unknown_last():
    assert [g.appid for g in sort_games(games(), "release_date", descending=False)] == [3, 1, 2]
    assert [g.appid for g in sort_games(games(), "name", descending=True)] == [3, 1, 2]


def test_sort_unknown_key():
    with pytest.raises(ValueError):
        sort_games([], "size")


def test_filter_games():
    gs = games()
    assert [g.appid for g in filter_games(gs, "ALP")] == [2]
    assert [g.appid for g in filter_games(gs, "")] == [1, 2, 3]
    assert [g.appid for g in filter_games(gs, "", installed_only=True)] == [3]
    assert filter_games(gs, "a b c") == []


# --- service -----------------------------------------------------------------

def service(steam_root, tmp_path, routes=None, key="k"):
    cfg = {"root": str(steam_root), "api_key": key, "steam_id": "1"}
    return SteamService(cfg, tmp_path / "cache", api=api(routes or {}, key=key), now=lambda: 1_800_000_000)


def test_load_library_merges_local_and_owned(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, {"GetOwnedGames": FakeResponse(OWNED)})
    lib = {g.appid: g for g in svc.load_library()}
    assert set(lib) == {620, 1145360, 292030}  # Proton filtered
    assert lib[620].installed and lib[620].playtime_minutes == 2000
    assert lib[1145360].installed and lib[1145360].playtime_minutes == 60
    assert not lib[292030].installed and lib[292030].playtime_minutes == 6000
    assert lib[620].last_played == 1660000000


def test_owned_games_offline_uses_cache(steam_root, tmp_path):
    service(steam_root, tmp_path, {"GetOwnedGames": FakeResponse(OWNED)}).load_library()
    offline = service(steam_root, tmp_path, {"GetOwnedGames": requests.ConnectionError()})
    assert 292030 in {g.appid for g in offline.load_library()}


def test_load_library_without_key_is_local_only(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, key="")
    assert {g.appid for g in svc.load_library()} == {620, 1145360}
    assert svc.api.session.requests == []


def test_installed_games(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, {"GetOwnedGames": FakeResponse(OWNED)})
    assert {g.appid for g in svc.installed_games()} == {620, 1145360}


def test_no_steam_installed(tmp_path):
    svc = SteamService({"root": str(tmp_path / "none")}, tmp_path / "c", api=api({}, key=""))
    assert svc.load_library() == []


def test_metadata_fetch_cache_and_apply(steam_root, tmp_path):
    routes = {"appdetails": FakeResponse(DETAILS), "GetNewsForApp": FakeResponse(NEWS)}
    svc = service(steam_root, tmp_path, routes)
    game = SteamGame(620, "Portal 2")
    assert svc.needs_metadata(game)
    meta = svc.fetch_metadata(620)
    assert meta["price_cents"] == 195 and meta["last_update"] == 1720000000
    assert not svc.needs_metadata(game)
    # persisted: a fresh service picks it up without network
    fresh = service(steam_root, tmp_path)
    svc_game = fresh.apply_metadata(SteamGame(620, "Portal 2"))
    assert svc_game.price_cents == 195 and svc_game.release_date and svc_game.last_updated == 1720000000
    # installed games keep their manifest update time
    installed = fresh.apply_metadata(SteamGame(620, "Portal 2", last_updated=5))
    assert installed.last_updated == 5
    data = json.loads((tmp_path / "cache" / "steam_metadata.json").read_text())
    assert "620" in data


def test_metadata_expires(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, {"appdetails": FakeResponse(DETAILS), "GetNewsForApp": requests.ConnectionError()})
    svc.fetch_metadata(620)
    svc.now = lambda: 1_800_000_000 + 8 * 24 * 3600
    assert svc.needs_metadata(SteamGame(620, "x"))


def test_images_local_cache_then_download(steam_root, tmp_path):
    lib = steam_root / "appcache" / "librarycache" / "620"
    lib.mkdir(parents=True)
    (lib / "library_600x900.jpg").write_bytes(b"jpg")
    svc = service(steam_root, tmp_path, {"library_600x900": FakeResponse(status=404), "header.jpg": FakeResponse(content=b"img")})
    assert svc.local_image(620) == lib / "library_600x900.jpg"
    assert svc.local_image(999) is None
    path = svc.download_image(999)
    assert path.read_bytes() == b"img"
    assert svc.local_image(999) == path


def test_image_download_failure(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, {"steamstatic": requests.ConnectionError()})
    assert svc.download_image(999) is None


def test_genres_from_the_store_page(steam_root, tmp_path):
    details = {"620": {"success": True, "data": {**DETAILS["620"]["data"], "genres": [
        {"id": "1", "description": "Action"}, {"id": "25", "description": "Adventure"}, {"id": "x"}]}}}
    assert api({"appdetails": FakeResponse(details)}).app_details(620)["genres"] == ["Action", "Adventure"]
    svc = service(steam_root, tmp_path, {"appdetails": FakeResponse(details), "GetNewsForApp": FakeResponse(NEWS)})
    svc.fetch_metadata(620)
    assert svc.apply_metadata(SteamGame(620, "Portal 2")).genres == ["Action", "Adventure"]
    assert svc.stored_metadata(620)["genres"] == ["Action", "Adventure"] and svc.stored_metadata(1) == {}
    assert not svc.needs_metadata_for(620) and svc.needs_metadata_for(1)


def test_store_data_from_before_genres_is_fetched_again(steam_root, tmp_path):
    svc = service(steam_root, tmp_path, {"appdetails": FakeResponse(DETAILS), "GetNewsForApp": FakeResponse(NEWS)})
    svc.fetch_metadata(620)
    svc._metadata["620"].pop("genres")  # cached by an older GamingCrypt
    assert svc.needs_metadata(SteamGame(620, "Portal 2"))

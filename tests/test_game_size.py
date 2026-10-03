import pytest

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.webapi import parse_storage
from gamingcrypt.ui.game_detail import GameDetailPage
from gamingcrypt.ui.games_tab import GamesTab
from tests.fakes import FakeService

GB = 1024**3
ROUNDS_PC = {"minimum": '<strong>Minimum:</strong><br><ul class="bb_ul"><li><strong>Memory:</strong> 8 GB RAM<br>'
                        '</li><li><strong>Storage:</strong> 4 GB available space<br></li></ul>'}
EMPTY_LINUX = {"minimum": '<strong>Minimum:</strong><br><ul class="bb_ul"></ul>'}


@pytest.mark.parametrize("reqs,expected", [
    ((EMPTY_LINUX, ROUNDS_PC), 4 * GB),          # Linux section empty -> Windows requirements
    (([], ROUNDS_PC), 4 * GB),                   # Steam sends [] for missing platforms
    (({"minimum": "<li><strong>Storage:</strong> 70 GB available space</li>"}, ROUNDS_PC), 70 * GB),  # Linux first
    (({"minimum": "<strong>Hard Drive:</strong> 1.5 GB HD space"},), int(1.5 * GB)),
    (({"minimum": "Hard Disk Space: 750 MB"},), 750 * 1024**2),
    (({"minimum": "Storage: 1,2 TB"},), int(1.2 * 1024**4)),
    (({"minimum": "nothing", "recommended": "Storage: 9 GB"},), 9 * GB),
    (({"minimum": "<strong>Memory:</strong> 8 GB RAM"},), None),  # RAM is not disk space
    ((None, [], {}), None),
])
def test_parse_storage(reqs, expected):
    assert parse_storage(*reqs) == expected


def test_app_details_and_metadata_cache(steam_root, tmp_path):
    from gamingcrypt.steam.service import SteamService
    from gamingcrypt.steam.webapi import SteamWebAPI
    from tests.fakes import FakeResponse, FakeSession

    details = {"1557740": {"success": True, "data": {"name": "ROUNDS", "pc_requirements": ROUNDS_PC,
                                                      "linux_requirements": [],
                                                      "release_date": {"date": "1 Apr, 2021"}}}}
    api = SteamWebAPI(session=FakeSession({"appdetails": FakeResponse(details),
                                           "GetNewsForApp": FakeResponse({"appnews": {"newsitems": []}})}))
    svc = SteamService({"root": str(steam_root)}, tmp_path / "c", api=api, now=lambda: 1_800_000_000)
    svc._metadata["1557740"] = {"price_cents": 1, "fetched_at": 1_800_000_000}  # cached before sizes existed
    game = SteamGame(1557740, "ROUNDS")
    assert svc.needs_metadata(game)  # refreshed once to learn the size
    svc.fetch_metadata(1557740)
    assert not svc.needs_metadata(game)
    assert svc.apply_metadata(game).store_size == 4 * GB


def page_for(qtbot, game, metadata=None):
    service = FakeService(games=[game], metadata=metadata or {})
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.games[game.appid] = game
    tab.open_game(game.appid)
    page = tab.currentWidget()
    assert isinstance(page, GameDetailPage)
    return page, service


def test_installed_game_shows_size_on_disk(qtbot):
    page, service = page_for(qtbot, SteamGame(1, "Installed", installed=True, size_on_disk=12 * GB))
    assert "Size on disk: 12.0 GB" in page.facts.text()
    assert service.fetched == []  # nothing to ask the store


def test_steam_game_shows_store_size(qtbot):
    page, _ = page_for(qtbot, SteamGame(2, "Not installed", store_size=4 * GB))
    assert "Size: ~4.0 GB (store)" in page.facts.text()


def test_size_is_fetched_when_opening_the_page(qtbot):
    page, service = page_for(qtbot, SteamGame(3, "Unknown size"), {3: {"storage_bytes": 30 * GB}})
    assert "Size: loading…" in page.facts.text()
    qtbot.waitUntil(lambda: "~30.0 GB" in page.facts.text())
    assert service.fetched == [3]


def test_size_unknown(qtbot):
    page, service = page_for(qtbot, SteamGame(4, "No data"))
    assert "Size: unknown" in page.facts.text() and service.fetched == []

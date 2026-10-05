"""Emulated games in Continue playing / Recently played / Favorites, with play time."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.playtime import PlayLog
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.steam.models import SteamGame


@pytest.fixture
def paths(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    (p.roms / "snes" / "Super Mario World (USA).sfc").write_text("x")
    (p.roms / "psx" / "Crash Bandicoot (USA).chd").write_text("x")
    return p


def test_play_log(paths):
    clock = [1_700_000_000.0]
    log = PlayLog(paths, now=lambda: clock[0])
    mario = scan(paths, BY_ID["snes"])[0]
    assert log.get(mario.appid) == (None, 0)
    log.start(mario)
    clock[0] += 25 * 60
    assert log.finish(mario.appid) == 25
    assert log.get(mario.appid) == (int(clock[0]), 25)
    assert log.finish(mario.appid) == 0  # not running: nothing added
    games = scan(paths, BY_ID["snes"])
    PlayLog(paths).apply(games)  # read back from the drive
    assert games[0].minutes == 25 and games[0].last_played == int(clock[0])


@pytest.fixture
def tab(qtbot, paths):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    games = [SteamGame(620, "Portal 2", installed=True, playtime_minutes=90, last_played=1_600_000_000)]
    service = FakeService(games=games)
    t = GamesTab(service, library_settings=copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(paths.root))
    t.covers = None
    qtbot.addWidget(t)
    t.show()
    t.games.update({g.appid: g for g in games})
    clock = [1_700_000_000.0]
    t.play_log.now = lambda: clock[0]
    mario = scan(paths, BY_ID["snes"])[0]
    t.play_log.start(mario)
    clock[0] += 60 * 60
    t.play_log.finish(mario.appid)
    t.home.set_installed(service.installed_games())
    t.reload_roms()
    qtbot.waitUntil(lambda: "snes" in t.roms)
    return t


def test_continue_playing_picks_the_rom(qtbot, tab):
    card = tab.home.continue_card
    assert card.isVisible() and card.title.text() == "Super Mario World"
    assert card.meta.text().startswith("SNES · last played") and "1.0 h played" in card.meta.text()
    launched = []
    tab.rom_launcher = lambda game: launched.append(game.name) or (True, "")
    card.play_button.click()
    assert launched == ["Super Mario World"]
    card.details_button.click()
    assert tab.currentWidget().game.name == "Super Mario World"
    assert "1.0 h played" in tab.currentWidget().facts.text()


def test_recently_played_and_favorites_mix_steam_and_roms(qtbot, tab):
    from gamingcrypt.ui.emulation_pages import RomCard

    tab.open_recent()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    names = [page.cards[a].game.name for a in page.order]
    assert names == ["Super Mario World", "Portal 2"]  # newest first, Steam and ROM together
    assert isinstance(page.cards[page.order[0]], RomCard)
    tab.back()
    crash = tab.roms["psx"][0]
    tab.profiles.set(crash.appid, "favorite", True)
    tab.profiles.set(620, "favorite", True)
    tab.open_favorites()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    assert [page.cards[a].game.name for a in page.order] == ["Crash Bandicoot", "Portal 2"]


def test_app_records_the_session(qtbot, paths, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.emulation import retroarch
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: (True, "Starting"))
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(paths.root))
        return dict(pages)

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(window)
    window.show_shell()
    games = pages["Games"]
    mario = scan(paths, BY_ID["snes"])[0]
    window.launch_rom(mario)
    assert games.play_log.get(mario.appid)[0] is not None and mario.appid in games.play_log.started
    window.game_watcher._stop()
    window.game_watcher.finished.emit(mario.appid)
    assert mario.appid not in games.play_log.started  # session closed

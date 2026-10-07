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


def test_favorites_count_only_games_still_there(qtbot, tab, paths):
    # a starred ROM that was removed (or renamed) kept its star: "3 games" over a page of 2
    crash = tab.roms["psx"][0]
    for appid in (crash.appid, 620):
        tab.profiles.set(appid, "favorite", True)
    tab.home.update_favorites()
    assert tab.home.favorites_card.subtitle.text() == "2 games"
    crash.path.unlink()
    tab.reload_roms()
    qtbot.waitUntil(lambda: not tab.roms.get("psx"))
    assert tab.home.favorites_card.subtitle.text() == "1 game"  # as the Favorites page shows
    (paths.roms / "psx" / crash.path.name).write_text("x")
    tab.reload_roms()
    qtbot.waitUntil(lambda: bool(tab.roms.get("psx")))
    assert tab.home.favorites_card.subtitle.text() == "2 games"  # back: still a favorite


def test_play_time_is_kept_while_playing_and_after_a_restart(paths):
    """Saved every minute while it runs: GamingCrypt (or gaming mode) restarting in the middle
    of a game doesn't lose the session - and seconds count, not rounded minutes."""
    import json

    clock = [1_700_000_000.0]
    log = PlayLog(paths, now=lambda: clock[0])
    mario = scan(paths, BY_ID["snes"])[0]
    log.start(mario)
    clock[0] += 90
    log.tick(mario.appid)
    assert log.get(mario.appid)[1] == 1  # 1.5 min so far, kept
    clock[0] += 600
    restarted = PlayLog(paths, now=lambda: clock[0])  # GamingCrypt started again, the game still runs
    assert restarted.finish(mario.appid) == 10  # from the last tick, read back from the file
    assert restarted.get(mario.appid)[1] == 11 and "playing_since" not in json.loads(
        (paths.config / "playtime.json").read_text())[str(mario.appid)]
    for _ in range(4):  # four short sessions of 40 s: 2 min 40 s, not 4 x 1 min
        log.start(mario)
        clock[0] += 40
        log.finish(mario.appid)
    assert log.get(mario.appid)[1] == 14  # 11.5 min + 2 min 40 s (rounded per session it was 15)


def test_older_minutes_are_kept(paths):
    import json

    mario = scan(paths, BY_ID["snes"])[0]
    (paths.config / "playtime.json").write_text(json.dumps({str(mario.appid): {"minutes": 30, "last_played": 5}}))
    clock = [1_700_000_000.0]
    log = PlayLog(paths, now=lambda: clock[0])
    assert log.get(mario.appid) == (5, 30)
    log.start(mario)
    clock[0] += 120
    log.finish(mario.appid)
    assert log.get(mario.appid)[1] == 32


def test_the_app_keeps_it_every_minute(qtbot, paths, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.emulation import retroarch
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: (True, "Starting"))
    monkeypatch.setattr(MainWindow, "PLAY_TICK_MS", 50)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(paths.root))
        return dict(pages)

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(window)
    window.show_shell()
    log = pages["Games"].play_log
    clock = [1_700_000_000.0]
    log.now = lambda: clock[0]
    mario = scan(paths, BY_ID["snes"])[0]
    window.launch_rom(mario)
    monkeypatch.setattr(type(window.game_watcher), "active", property(lambda self: True))
    window.game_watcher.appid = mario.appid
    clock[0] += 300
    qtbot.waitUntil(lambda: log.get(mario.appid)[1] == 5)  # kept while it runs


def test_rom_cards_show_the_play_time(qtbot, tab):
    from gamingcrypt.ui.emulation_pages import RomCard

    mario = tab.roms["snes"][0]
    assert RomCard(mario).meta.text().endswith("· 1.0 h")

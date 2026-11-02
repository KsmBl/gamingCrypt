"""A game's page: its cover blurred behind it, facts as chips, the newest save states."""

import time

from PySide6.QtGui import QColor, QPixmap

from gamingcrypt.emulation import savestates
from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.emulation.systems import SYSTEMS
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.game_look import CHIP_MAX_W, Backdrop, FactChips
from gamingcrypt.ui.game_widgets import Cover


def test_chips_read_like_a_label_and_skip_empty_lines(qtbot):
    chips = FactChips("Installed\n\n45 h played")
    qtbot.addWidget(chips)
    assert chips.text() == "Installed\n\n45 h played"
    assert [c.text() for c in chips.chips()] == ["Installed", "45 h played"]
    chips.setText("Only this")
    assert [c.text() for c in chips.chips()] == ["Only this"]


def test_a_long_fact_is_cut_with_all_of_it_in_the_tooltip(qtbot):
    long = "Starts " + "Binaries/Win64/" * 30 + "game.exe"
    chips = FactChips(long)
    qtbot.addWidget(chips)
    chip = chips.chips()[0]
    assert chip.text() != long and chip.toolTip() == long and chips.text() == long
    assert chip.fontMetrics().horizontalAdvance(chip.text()) <= CHIP_MAX_W


def test_backdrop_follows_the_cover_and_stays_faint(qtbot):
    from PySide6.QtWidgets import QWidget

    page = QWidget()
    qtbot.addWidget(page)
    cover = Cover(page)
    page.resize(400, 300)
    backdrop = Backdrop(page, cover)
    assert backdrop.size() == page.size()
    white = QPixmap(30, 30)
    white.fill(QColor("white"))
    cover.setPixmap(white)
    top = backdrop.render().toImage().pixelColor(200, 10)
    assert 60 <= top.alpha() <= 90  # a bright cover can't drown the text on it
    assert backdrop.render().toImage().pixelColor(200, 299).alpha() < 10  # gone at the bottom
    page.show()
    page.resize(500, 300)
    qtbot.waitUntil(lambda: backdrop.size() == page.size())


def test_steam_page_leaves_out_what_isnt_known(qtbot):
    from gamingcrypt.ui.game_detail import GameDetailPage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    page = GameDetailPage(tab, SteamGame(4, "No data", installed=True))
    qtbot.addWidget(page)
    facts = page.facts.text()
    assert "Installed" in facts and not any(word in facts for word in ("Released", "Price", "Latest update", " -"))


def rom_with_states(tmp_path, saved):
    paths = EmulationPaths(tmp_path)
    system = next(s for s in SYSTEMS if s.emulator == "retroarch" and s.save_states)
    rom = tmp_path / "Game.bin"
    rom.write_bytes(b"x")
    game = RomGame(system, rom, "Game", 1)
    paths.states.mkdir(parents=True)
    now = time.time()
    for slot, age in saved.items():
        state = savestates.state_file(paths, game, slot)
        state.write_bytes(b"s")
        import os

        os.utime(state, (now - age, now - age))
    return paths, game


def test_newest_states_first(tmp_path):
    paths, game = rom_with_states(tmp_path, {0: 300, 4: 100, 7: 200, 8: 400})
    assert [s.slot for s in savestates.newest(paths, game, 3)] == [4, 7, 0]


def test_rom_page_starts_the_game_from_a_state(qtbot, tmp_path):
    from gamingcrypt.ui.emulation_pages import RomGamePage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    paths, game = rom_with_states(tmp_path, {2: 10, 5: 5})
    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.emulation = paths
    started = []
    tab.rom_launcher = lambda *args: started.append(args) or (True, "")
    page = RomGamePage(tab, game)
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: len(page.states_flow.widgets()) == 2)
    assert page.states_row.isVisible()
    page.states_flow.widgets()[0].tapped.emit()
    assert started == [(game, 5)]


def test_rom_page_without_states_shows_no_row(qtbot, tmp_path):
    from gamingcrypt.ui.emulation_pages import RomGamePage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    paths, game = rom_with_states(tmp_path, {})
    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.emulation = paths
    page = RomGamePage(tab, game)
    qtbot.addWidget(page)
    page.show()
    qtbot.wait(100)
    assert not page.states_row.isVisible() and not page.states_title.isVisible()


def test_starting_from_a_state_loads_it_once_the_game_is_up(monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.emulation import retroarch

    paths, game = rom_with_states(tmp_path, {3: 1})
    savestates.played_file(savestates.state_file(paths, game, 3)).write_text("120\n")
    sent = []
    monkeypatch.setattr(retroarch, "playing", lambda: True)
    monkeypatch.setattr(retroarch, "send", lambda text: sent.append(text) or True)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    monkeypatch.setattr("gamingcrypt.app.run_async", lambda fn, done, error, owner=None: done(fn()))

    class Window:
        start_state_clock = MainWindow.start_state_clock
        state_played = MainWindow.state_played
        notify = lambda self, *a: sent.append(a)  # noqa: E731

    window = Window()
    MainWindow.load_state_when_up(window, game, paths, 3)
    assert sent == [savestates.load_command(3)] and 120 <= window.state_played() <= 121

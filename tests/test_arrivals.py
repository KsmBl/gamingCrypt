"""New things on the drive (network share, upload, copy) are noticed - once they're complete."""

import copy
import os
import time

from gamingcrypt.arrivals import Arrival, Watcher, describe, tidy


def drive(tmp_path):
    root = tmp_path / "GamingCrypt"
    for sub in ("Emulation/roms/snes", "Windows Games", "Linux Games", "Movies", "Shows"):
        (root / sub).mkdir(parents=True)
    (root / "Movies" / "Heat.mkv").write_bytes(b"x")  # there before
    return root


def test_the_first_look_learns_what_is_there(tmp_path):
    watcher = Watcher(drive(tmp_path))
    assert watcher.poll() == [] and watcher.poll() == []


def test_new_things_once_they_stopped_changing(tmp_path):
    root = drive(tmp_path)
    watcher = Watcher(root)
    watcher.poll()
    rom = root / "Emulation" / "roms" / "snes" / "Super Mario World (USA) [!].sfc"
    rom.write_bytes(b"x" * 10)
    assert watcher.poll() == []  # maybe still copying
    rom.write_bytes(b"x" * 20)  # it was
    assert watcher.poll() == []
    assert watcher.poll() == [Arrival("rom", "Super Mario World", "SNES")]
    assert watcher.poll() == []  # once


def test_what_counts(tmp_path):
    root = drive(tmp_path)
    watcher = Watcher(root)
    watcher.poll()
    (root / "Windows Games" / "Hollow Knight").mkdir()
    (root / "Windows Games" / "Hollow Knight" / "hk.exe").write_bytes(b"MZ")
    (root / "Windows Games" / "readme.txt").write_text("a file, not a game")
    (root / "Movies" / "Heat.nfo").write_text("info GamingCrypt wrote")
    (root / "Movies" / "Alien.mkv").write_bytes(b"x")
    (root / "Movies" / "Alien.mkv.part").write_bytes(b"x")
    (root / "Shows" / ".hidden").mkdir()
    (root / "Shows" / "Dark").mkdir()
    watcher.poll()
    found = watcher.poll()
    assert sorted(found, key=lambda a: a.kind) == [Arrival("movie", "Alien"), Arrival("show", "Dark"),
                                                   Arrival("windows", "Hollow Knight")]


def test_a_folder_still_filling_waits(tmp_path):
    root = drive(tmp_path)
    watcher = Watcher(root)
    watcher.poll()
    game = root / "Linux Games" / "Stardew Valley"
    game.mkdir()
    (game / "a").write_bytes(b"1")
    watcher.poll()
    (game / "b").write_bytes(b"22")  # more came in
    os.utime(game / "b", (time.time() + 5, time.time() + 5))
    assert watcher.poll() == []
    assert watcher.poll() == [Arrival("linux", "Stardew Valley")]


def test_removed_and_back_is_new_again(tmp_path):
    root = drive(tmp_path)
    watcher = Watcher(root)
    watcher.poll()
    (root / "Movies" / "Heat.mkv").unlink()
    watcher.poll()
    (root / "Movies" / "Heat.mkv").write_bytes(b"x")
    watcher.poll()
    assert watcher.poll() == [Arrival("movie", "Heat")]


def test_names_and_notices():
    assert tidy("Final_Fantasy.VII (Disc 1) [SLES].cue") == "Final Fantasy VII"
    assert tidy("Hollow Knight") == "Hollow Knight"
    assert describe([Arrival("rom", "Mario", "SNES")]) == "New on your drive: Mario (SNES)"
    assert describe([Arrival("movie", "Heat")]) == "New on your drive: Heat (movie)"
    assert describe([Arrival("rom", "A", "SNES"), Arrival("windows", "B"), Arrival("movie", "C")]) == \
        "New on your drive: 2 games, 1 movie"


def test_the_app_tells_and_shows_them(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    root = drive(tmp_path)
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"]["mount_point"] = str(root)
    pages = {}

    def factory(config):
        pages["Games"] = GamesTab(FakeService(), library_settings=config["libraries"],
                                  emulation_root=str(root / "Emulation"))
        return dict(pages)

    monkeypatch.setattr(MainWindow, "ARRIVALS_MS", 60_000)  # looked at by hand below
    w = MainWindow(cfg, lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    qtbot.waitUntil(lambda: w.arrivals.known is not None and not w._looking_for_arrivals)
    (root / "Emulation" / "roms" / "snes" / "Super Mario World (USA).sfc").write_bytes(b"x")
    for _ in range(2):
        w.look_for_arrivals()
        qtbot.waitUntil(lambda: not w._looking_for_arrivals)
    assert w.toasts.shown[-1] == "New on your drive: Super Mario World (SNES)"
    qtbot.waitUntil(lambda: "snes" in pages["Games"].roms)  # the Games tab shows it


def test_an_open_list_shows_new_games(qtbot, tmp_path):
    """A system's list - or the Windows games, even under a game opened from it - shows what
    came in, in place: the search stays, the page isn't left."""
    from gamingcrypt.ui.emulation_pages import SystemPage
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.wine_pages import WindowsLibraryPage
    from tests.fakes import FakeService

    root = drive(tmp_path)
    snes = root / "Emulation" / "roms" / "snes"
    (snes / "Super Mario World (USA).sfc").write_bytes(b"x")
    (root / "Windows Games" / "Celeste").mkdir()
    (root / "Windows Games" / "Celeste" / "Celeste.exe").write_bytes(b"MZ")
    tab = GamesTab(FakeService(), emulation_root=str(root / "Emulation"), windows_root=str(root / "Windows Games"))
    tab.covers = tab.windows_covers = None
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: "snes" in tab.roms and len(tab.windows_games) == 1)
    tab.open_system("snes")
    page = tab.currentWidget()
    page.search.setText("mario")
    (snes / "Super Mario Kart (USA).sfc").write_bytes(b"x")
    (snes / "Zelda (USA).sfc").write_bytes(b"x")
    tab.reload_roms()
    qtbot.waitUntil(lambda: len(page.cards) == 3)
    assert tab.currentWidget() is page and isinstance(page, SystemPage)
    assert page.search.text() == "mario" and len(page.shown) == 2  # the search still applies
    assert page.search.placeholderText() == "🔍  Search 3 games"
    (snes / "Zelda (USA).sfc").unlink()
    tab.reload_roms()
    qtbot.waitUntil(lambda: len(page.cards) == 2)
    tab.back()
    tab.open_windows_library()
    library = tab.currentWidget()
    tab.open_windows_game(tab.windows_games[0])  # a game page over the list
    (root / "Windows Games" / "Hades").mkdir()
    (root / "Windows Games" / "Hades" / "Hades.exe").write_bytes(b"MZ")
    tab.reload_windows()
    qtbot.waitUntil(lambda: len(library.cards) == 2)
    assert isinstance(library, WindowsLibraryPage) and tab.currentWidget() is not library  # still on the game

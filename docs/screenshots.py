"""Renders the README screenshots (offscreen, with sample games, movies and shows).

    .venv/bin/python docs/screenshots.py          # -> docs/screenshots/*.png
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QElapsedTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from gamingcrypt.app import MainWindow  # noqa: E402
from gamingcrypt.config import DEFAULTS  # noqa: E402
from gamingcrypt.movies import library as movies  # noqa: E402
from gamingcrypt.movies.library import MovieInfo  # noqa: E402
from gamingcrypt.steam.models import SteamGame  # noqa: E402
from gamingcrypt.ui import theme  # noqa: E402
from gamingcrypt.ui.games_tab import GamesTab  # noqa: E402
from gamingcrypt.ui.movies_tab import MoviesTab  # noqa: E402
from gamingcrypt.ui.shows_tab import ShowsTab  # noqa: E402
from tests.fakes import FakeService  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
SIZE = (1280, 800)  # the handheld's screen

MOVIES = [("Starfall", 2019, 128, "FSK 12", ["Science fiction"]), ("The Long Road", 2004, 112, "FSK 6", ["Drama"]),
          ("Night Harbour", 2016, 97, "FSK 16", ["Thriller"]), ("Paper Moons", 2021, 104, "FSK 0", ["Family"]),
          ("Iron Valley", 1998, 133, "FSK 16", ["Western"]), ("Quiet Signals", 2012, 121, "FSK 12", ["Mystery"]),
          ("Blue Atlas", 2023, 141, "FSK 12", ["Adventure"]), ("Glass Garden", 2009, 99, "FSK 6", ["Comedy"])]
GAMES = [SteamGame(1, "Hollow Peaks", installed=True, playtime_minutes=2700, last_played=1759600000),
         SteamGame(2, "Neon Drift", installed=True, playtime_minutes=480, size_on_disk=8_000_000_000),
         SteamGame(3, "Stellar Forge", installed=True, playtime_minutes=90),
         SteamGame(4, "Ember Knights", installed=True, playtime_minutes=1600),
         SteamGame(5, "Tidal Echoes", playtime_minutes=30), SteamGame(6, "Moss Kingdom", playtime_minutes=0)]


class NoLookup:
    def find(self, *a):
        return None


def sample_drive(base: Path) -> tuple[Path, Path, Path]:
    plot = ("A crew of misfits sets out on a journey that changes everything they believed about home, "
            "friendship and the stars above.")
    for i, (title, year, minutes, fsk, genres) in enumerate(MOVIES):
        path = base / "Movies" / f"{title} ({year}).mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"v")
        movies.write_info(path.with_suffix(".nfo"), MovieInfo(
            title=title, year=year, runtime=minutes, fsk=fsk, genres=genres, plot=plot, looked_up=1, wikidata="Q1",
            directors=["Mara Lindqvist"], actors=[("Jonas Weber", "Captain Reyes"), ("Ana Duarte", "Lena")],
            watched=i in (1, 4), playcount=int(i in (1, 4)), position=2400 if i == 2 else 0, total=5800))
    for season in (1, 2):
        for number in range(1, 7):
            seen = season == 1 and number < 4
            path = base / "Shows" / "Harbor Lights (2018)" / f"Season {season}" / f"Harbor Lights S0{season}E0{number}.mkv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"v")
            movies.write_info(path.with_suffix(".nfo"), MovieInfo(
                title=["Arrival", "The Keeper", "Low Tide", "Signals", "Undertow", "Homecoming"][number - 1],
                runtime=48, aired=f"2018-0{season + 2}-1{number}", looked_up=1, watched=seen, playcount=int(seen),
                plot="The lighthouse keeper finds a message that should not exist.", position=900 if
                (season, number) == (1, 4) else 0, total=2880, last_played=5), "episodedetails")
    movies.write_info(base / "Shows" / "Harbor Lights (2018)" / "tvshow.nfo", MovieInfo(
        title="Harbor Lights", year=2018, end_year=2022, genres=["Drama", "Mystery"], tvmaze="1", looked_up=1,
        plot="In a small coastal town, a lighthouse keeper uncovers secrets that bind its families together.",
        actors=[("Ida Novak", "Keeper"), ("Tom Berg", "Sheriff")]), "tvshow")
    for i in range(1, 4):
        path = base / "Shows" / f"Night.Shift.S01E0{i}.mkv"
        path.write_bytes(b"v")
    movies.write_info(base / "Shows" / "Night Shift.tvshow.nfo", MovieInfo(title="Night Shift", year=2021, tvmaze="2",
                                                                          genres=["Comedy"], looked_up=1), "tvshow")
    emu = base / "Emulation"
    for system, name in (("snes", "Super Space Quest.sfc"), ("gba", "Pocket Racer.gba"), ("psx", "Shadow Run.chd")):
        (emu / "roms" / system).mkdir(parents=True, exist_ok=True)
        (emu / "roms" / system / name).write_bytes(b"x")
    return base / "Movies", base / "Shows", emu


def pump(ms: int) -> None:
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.005)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    movies_root, shows_root, emu = sample_drive(Path(tempfile.mkdtemp()))
    service = FakeService(games=GAMES)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(service, library_settings=cfg["libraries"], emulation_root=str(emu))
        pages["Movies"] = MoviesTab(movies_root, lookup=NoLookup())
        pages["Shows"] = ShowsTab(shows_root, lookup=NoLookup())
        return dict(pages)

    for name in ("dark", "light"):
        theme.apply(name, app)
        window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
        window.windowed, window.update_check_enabled, window.welcome_enabled = True, False, False
        window.resize(*SIZE)
        window.show()
        window.show_shell()
        pump(800)
        shell = window.shell
        games = pages["Games"]
        games.games.update({g.appid: g for g in GAMES})

        def shot(file: str) -> None:
            pump(400)
            window.grab().save(str(OUT / f"{file}.png"))

        suffix = "" if name == "dark" else "-light"
        shot(f"games{suffix}")
        if name == "light":
            shell.show_tab("Settings")
            shot("settings-light")
            window.close()
            break
        games.open_steam()
        shot("steam")
        games.back()
        games.open_game(1)
        shot("detail")
        games.back()
        shell.show_tab("Movies")
        shot("movies")
        movie_tab = pages["Movies"]
        movie_tab.open_movie(next(m for m in movie_tab.items if m.title == "Night Harbour"))
        shot("movie")
        movie_tab.back()
        shell.show_tab("Shows")
        shot("shows")
        show_tab = pages["Shows"]
        show_tab.open_show(next(s for s in show_tab.items if s.title == "Harbor Lights"))
        shot("show")
        show_tab.currentWidget().scroll.verticalScrollBar().setValue(520)
        shot("episodes")
        show_tab.back()
        shell.show_tab("Settings")
        shot("settings")
        shell.show_tab("Games")
        window.toggle_quick_menu()
        shot("quickmenu")
        window.quick_menu.close_menu()
        window.close()

    theme.apply("dark", app)
    from gamingcrypt.ui.auth_setup import AuthSetupWizard
    from gamingcrypt.ui.lock_screen import LockScreen
    from tests.test_lock_screen import FakeUnlocker

    for method, file in (("password", "lock"), ("grid5", "grid5"), ("pattern", "pattern")):
        screen = LockScreen(FakeUnlocker(), method)
        screen.resize(*SIZE)
        screen.show()
        pump(400)
        screen.grab().save(str(OUT / f"{file}.png"))
        screen.close()
    config = copy.deepcopy(DEFAULTS)
    wizard = AuthSetupWizard(config, lambda c: None, lambda c: FakeUnlocker(), first_start=True)
    wizard.resize(*SIZE)
    wizard.show()
    pump(400)
    wizard.grab().save(str(OUT / "create.png"))
    print("screenshots in", OUT)


if __name__ == "__main__":
    main()

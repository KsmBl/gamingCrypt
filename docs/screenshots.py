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
    from gamingcrypt.minecraft import library as minecraft

    survival = minecraft.create(base / "Minecraft", "Survival", loader=minecraft.FABRIC)
    survival.installed, survival.game_version = "fabric-26.3-0.19.5", "26.3"
    minecraft.save(survival)
    minecraft.create(base / "Minecraft", "Creative builds", "26.2")
    return base / "Movies", base / "Shows", emu


def pump(ms: int) -> None:
    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < ms:
        app.processEvents()
        time.sleep(0.005)


def game_keyboard(window) -> None:
    """The on-screen keyboard over a game (its device button): the screen's size, on the game's
    dark picture - steered with the controller, typing into the game."""
    from PySide6.QtGui import QColor, QPainter, QPixmap

    from gamingcrypt.input.virtual_keyboard import VirtualKeyboard
    from gamingcrypt.ui.game_keyboard import GameKeyboard

    keyboard = GameKeyboard(sink=VirtualKeyboard(make_uinput=lambda: None), mark_overlay=lambda w: True)
    keyboard.open_over_game()
    keyboard.setGeometry(0, 0, *SIZE)
    keyboard._place()
    keyboard.select(2, 4)  # (the highlight on a key)
    pump(300)
    picture = QPixmap(*SIZE)
    picture.fill(QColor(theme.BG))
    painter = QPainter(picture)
    painter.drawPixmap(keyboard.panel.pos(), keyboard.panel.grab())
    painter.end()
    picture.save(str(OUT / "keyboard.png"))
    keyboard.close_keyboard()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    movies_root, shows_root, emu = sample_drive(Path(tempfile.mkdtemp()))
    service = FakeService(games=GAMES)
    pages = {}
    from gamingcrypt.minecraft import portable

    portable.available = lambda: True  # (never started here: who's signed in is set below)

    def factory(cfg):
        pages["Games"] = GamesTab(service, library_settings=cfg["libraries"], emulation_root=str(emu),
                                  minecraft_root=str(emu.parent / "Minecraft"))
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
        window.activateWindow()  # the controller highlight shows where the focus is
        pump(800)
        shell = window.shell
        games = pages["Games"]
        games.games.update({g.appid: g for g in GAMES})
        games.minecraft_accounts = [portable.Account("Steve", "1")]

        def shot(file: str) -> None:
            pump(400)
            window.grab().save(str(OUT / f"{file}.png"))

        suffix = "" if name == "dark" else "-light"
        games.home.steam_card.setFocus()  # the controller's highlight
        shot(f"games{suffix}")
        games.open_steam()
        shot(f"steam{suffix}")
        games.back()
        games.open_game(1)
        shot(f"detail{suffix}")
        games.back()
        if name == "light":
            shell.show_tab("Settings")
            shot("settings-light")
            shell.show_tab("Games")
            window.toggle_quick_menu()
            shot("quickmenu-light")
            window.quick_menu.close_menu()
            window.close()
            break
        games.open_minecraft_library()
        shot("minecraft")
        games.open_minecraft_game(next(g for g in games.minecraft_games if g.name == "Survival"))
        shot("minecraft-instance")
        games.back()
        games.back()
        game_keyboard(window)
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

    from gamingcrypt.ui.auth_setup import AuthSetupWizard
    from gamingcrypt.ui.lock_screen import LockScreen
    from tests.test_lock_screen import FakeUnlocker

    for look, method, file in (("dark", "password", "lock"), ("dark", "grid5", "grid5"), ("dark", "pattern", "pattern"),
                               ("light", "pin", "pin-light")):
        theme.apply(look, app)
        screen = LockScreen(FakeUnlocker(), method)
        screen.resize(*SIZE)
        screen.show()
        screen.activateWindow()
        pump(400)
        screen.grab().save(str(OUT / f"{file}.png"))
        screen.close()
    theme.apply("dark", app)
    config = copy.deepcopy(DEFAULTS)
    wizard = AuthSetupWizard(config, lambda c: None, lambda c: FakeUnlocker(), first_start=True)
    wizard.resize(*SIZE)
    wizard.show()
    pump(400)
    wizard.grab().save(str(OUT / "create.png"))
    print("screenshots in", OUT)


if __name__ == "__main__":
    main()

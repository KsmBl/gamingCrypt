"""Movies tab: cards, filters, the movie's page, playing / resuming, removing, uploading."""

import copy
import http.client

import pytest
from PySide6.QtGui import QColor

from gamingcrypt.movies import library, player
from gamingcrypt.movies.library import MovieInfo
from gamingcrypt.ui.movies_tab import MovieCard, MoviePage, MoviesTab, MovieUploadPage, Playback, movie_cover


class FakeLookup:
    """metadata.Lookup stand-in: what it would have found."""

    def __init__(self, found=None, offline=False):
        self.found, self.offline, self.asked = found or {}, offline, []
        self.languages = ("en", "de")

    def find(self, title, year):
        from gamingcrypt.movies.metadata import Offline

        self.asked.append(title)
        if self.offline:
            raise Offline("no network")
        result = self.found.get(title)
        return (MovieInfo(**result), "") if result else None

    def download_cover(self, url, path):
        return False


def put(root, name, **info):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"v" * 100)
    if info:
        library.write_info(path.with_suffix(".nfo"), MovieInfo(looked_up=1, **info))
    return path


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "GamingCrypt" / "Movies"
    put(root, "The Matrix (1999).mkv", title="The Matrix", year=1999, runtime=136, fsk="FSK 16",
        genres=["Action", "Science fiction"], plot="Neo learns the truth.", directors=["Lana Wachowski"],
        actors=[("Keanu Reeves", "Neo"), ("Carrie-Anne Moss", "Trinity")], wikidata="Q83495")
    put(root, "Finding Nemo.mkv", title="Finding Nemo", year=2003, runtime=100, fsk="FSK 0", genres=["Family"],
        wikidata="Q3", position=1800, total=6000)
    put(root, "Alien/Alien.mkv", title="Alien", year=1979, fsk="FSK 16", genres=["Horror"], wikidata="Q4",
        watched=True, playcount=1)
    return root


def make_tab(qtbot, root, lookup=None, launcher=None):
    tab = MoviesTab(root, lookup=lookup or FakeLookup())
    tab.player_launcher = launcher
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitUntil(lambda: bool(tab.home.cards) and len(tab.home.cards) == len(library.scan(root)))
    return tab


def shown_titles(tab):
    return [tab.home.cards[key].movie.title for key in tab.home.shown]


def test_every_movie_is_a_card(qtbot, root):
    tab = make_tab(qtbot, root)
    home = tab.home
    assert shown_titles(tab) == ["Alien", "Finding Nemo", "The Matrix"]
    assert home.count_label.text() == "3 movies" and home.add_button.isVisible()
    card = home.cards["The Matrix (1999).mkv"]
    assert card.title.text() == "The Matrix" and card.meta.text() == "1999 · 2 h 16 min · FSK 16"
    assert card.width() == home.cards["Alien/Alien.mkv"].width()


def test_search_and_filters(qtbot, root):
    tab = make_tab(qtbot, root)
    home = tab.home
    home.search.setText("keanu")
    assert shown_titles(tab) == ["The Matrix"]
    home.search.setText("")
    home.state_buttons["watched"].click()
    assert shown_titles(tab) == ["Alien"] and home.state_buttons["watched"].isChecked()
    home.state_buttons["progress"].click()
    assert shown_titles(tab) == ["Finding Nemo"] and not home.state_buttons["watched"].isChecked()
    home.state_buttons["all"].click()
    assert [home.genre_combo.itemText(i) for i in range(home.genre_combo.count())] == [
        "All genres", "Action", "Family", "Horror", "Science fiction"]
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Horror"))
    assert shown_titles(tab) == ["Alien"]
    home.genre_combo.setCurrentIndex(0)
    home.age_combo.setCurrentIndex(home.age_combo.findData(12))
    assert shown_titles(tab) == ["Finding Nemo"]
    home.age_combo.setCurrentIndex(0)
    home.sort_combo.setCurrentIndex(home.sort_combo.findData("year"))
    assert shown_titles(tab) == ["Finding Nemo", "The Matrix", "Alien"]
    home.search.setText("nothing like this")
    assert home.shown == [] and home.empty_label.text() == "No movie matches"


def test_cards_show_watched_and_how_far(qtbot, root):
    movies = {m.title: m for m in library.scan(root)}
    alien = movie_cover(movies["Alien"], 200, 300).toImage()
    nemo = movie_cover(movies["Finding Nemo"], 200, 300).toImage()
    matrix = movie_cover(movies["The Matrix"], 200, 300).toImage()
    corner = QColor(alien.pixel(200 - 8 - 16, 8 + 16))  # middle of the ✓ circle
    assert corner.green() > 150 and corner.red() < 100
    assert QColor(matrix.pixel(200 - 8 - 16, 8 + 16)) != corner
    assert QColor(nemo.pixel(20, 297)).blue() > 200  # 30 % of the bar at the bottom
    assert QColor(nemo.pixel(150, 297)).blue() < 100


def test_movie_page_shows_everything(qtbot, root):
    tab = make_tab(qtbot, root)
    tab.home.cards["The Matrix (1999).mkv"].tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, MoviePage)
    assert page.title.text() == "The Matrix"
    assert page.facts.text() == "1999 · 2 h 16 min · FSK 16\nAction, Science fiction"
    assert page.plot.text() == "Neo learns the truth."
    assert "Director: Lana Wachowski" in page.people.text()
    assert "Keanu Reeves  ·  Neo\nCarrie-Anne Moss  ·  Trinity" in page.people.text()
    assert page.main_button.text() == "▶  Play" and not page.restart_button.isVisible()
    assert not page.progress.isVisible() and page.watched_button.text() == "✓ Mark as watched"
    tab.gamepad_back()
    assert tab.currentWidget() is tab.home


def test_resume_or_from_the_start(qtbot, root):
    played = []
    tab = make_tab(qtbot, root, launcher=lambda movie, start: (played.append((movie.title, start)), (True, "ok"))[1])
    tab.playback.timer.stop = lambda: None
    tab.open_movie(next(m for m in tab.movies if m.title == "Finding Nemo"))
    page = tab.currentWidget()
    assert page.progress.text() == "Stopped at 0:30:00 of 1:40:00"
    assert page.main_button.text() == "▶  Resume at 0:30:00" and page.restart_button.isVisible()
    page.main_button.click()
    page.restart_button.click()
    assert played == [("Finding Nemo", 1800), ("Finding Nemo", 0)]
    assert tab.playback.movie.title == "Finding Nemo"


def test_player_problems_are_shown(qtbot, root):
    tab = make_tab(qtbot, root, launcher=lambda movie, start: (False, "The movie player (mpv) isn't installed"))
    tab.open_movie(tab.movies[0])
    tab.currentWidget().main_button.click()
    assert "mpv" in tab.currentWidget().status.text() and tab.playback.movie is None
    tab.player_launcher = None
    assert tab.play(tab.movies[0]) == (False, "The movie player isn't set up")


def test_mark_watched(qtbot, root):
    tab = make_tab(qtbot, root)
    matrix = next(m for m in tab.movies if m.title == "The Matrix")
    tab.open_movie(matrix)
    page = tab.currentWidget()
    page.watched_button.click()
    qtbot.waitUntil(lambda: page.progress.text() == "✓ Watched")
    assert library.read_info(matrix.info_path).watched and page.watched_button.text() == "Mark as unwatched"
    tab.home.state_buttons["watched"].click()
    assert sorted(shown_titles(tab)) == ["Alien", "The Matrix"]
    page.watched_button.click()
    qtbot.waitUntil(lambda: page.watched_button.text() == "✓ Mark as watched")
    assert not library.read_info(matrix.info_path).watched


def test_remove_asks_first_and_takes_cover_and_info_along(qtbot, root):
    tab = make_tab(qtbot, root)
    alien = next(m for m in tab.movies if m.title == "Alien")
    (root / "Alien" / "Alien.jpg").write_bytes(b"jpg")
    tab.open_movie(alien)
    page = tab.currentWidget()
    page.options_button.click()
    assert page.options_panel.isVisible() and "Alien/Alien.mkv" in page.file_label.text()
    page.remove_button.click()
    confirm = page.confirm
    assert confirm.isVisible() and "Really remove Alien?" in confirm.question.text()
    assert "3 files" in confirm.question.text()
    confirm.cancel_button.click()
    assert page.confirm is None and (root / "Alien" / "Alien.mkv").exists()
    page.remove_button.click()
    page.confirm.remove_button.click()
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.home)
    assert not (root / "Alien").exists()
    qtbot.waitUntil(lambda: "Alien/Alien.mkv" not in tab.home.cards)
    assert tab.home.notice.text().startswith("Alien removed")


def test_unknown_movies_are_looked_up_in_the_background(qtbot, root):
    put(root, "Blade.Runner.1982.mkv")
    put(root, "Holiday 2019.mp4")
    lookup = FakeLookup({"Blade Runner": dict(title="Blade Runner", year=1982, fsk="FSK 16", wikidata="Q5",
                                              genres=["Science fiction"])})
    tab = make_tab(qtbot, root, lookup)
    qtbot.waitUntil(lambda: tab.home.cards["Blade.Runner.1982.mkv"].meta.text() == "1982 · FSK 16")
    qtbot.waitUntil(lambda: library.read_info(root / "Holiday 2019.nfo").looked_up > 0)
    assert sorted(lookup.asked) == ["Blade Runner", "Holiday"]  # the known ones aren't asked again
    qtbot.waitUntil(lambda: not tab.home.notice.isVisible())
    assert "Science fiction" in [tab.home.genre_combo.itemText(i) for i in range(tab.home.genre_combo.count())]


def test_offline_says_so_and_tries_later(qtbot, root):
    put(root, "Blade.Runner.1982.mkv")
    tab = make_tab(qtbot, root, FakeLookup(offline=True))
    qtbot.waitUntil(lambda: "No internet" in tab.home.notice.text())
    assert not (root / "Blade.Runner.1982.nfo").exists()


def test_empty_folder_and_no_drive(qtbot, tmp_path):
    tab = MoviesTab(tmp_path / "Movies", lookup=FakeLookup())
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: "No movies yet" in tab.home.empty_label.text())
    locked = MoviesTab("", lookup=FakeLookup())
    qtbot.addWidget(locked)
    assert locked.home.empty_label.text() == "Unlock your encrypted drive to see your movies"
    locked.open_upload()
    assert locked.currentWidget() is locked.home and "Unlock" in locked.home.notice.text()


def test_the_movies_folder_is_made_on_the_unlocked_drive(qtbot, tmp_path, monkeypatch):
    import os

    drive = tmp_path / "GamingCrypt"
    drive.mkdir()
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(drive))
    tab = MoviesTab(drive / "Movies", lookup=FakeLookup())
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: (drive / "Movies").is_dir())


class Share:
    def __init__(self):
        self.user, self.password, self.running, self.folders = "gayming", "MapleOtter", False, []

    def start(self, folder):
        self.folders.append(folder)
        self.running = True
        return True, ""

    def stop(self):
        self.running = False


def test_upload_movies_over_wifi(qtbot, root):
    from gamingcrypt.emulation.upload_server import UploadServer

    share = Share()
    tab = make_tab(qtbot, root)
    tab.upload_page_factory = lambda folder: MovieUploadPage(
        folder, share=share, ip=lambda: "192.168.1.198",
        server_factory=lambda f, received: UploadServer(None, received, token="t", ports=range(18170, 18200),
                                                        host="127.0.0.1",
                                                        folders=lambda: {"movies": ("Movies", f)}))
    tab.home.add_button.click()
    page = tab.currentWidget()
    assert isinstance(page, MovieUploadPage) and "Add movies" in [l.text() for l in page.findChildren(type(page.url))]
    qtbot.waitUntil(lambda: "MapleOtter" in page.smb.text())
    assert share.folders == [str(root)]  # only the Movies folder is shared
    conn = http.client.HTTPConnection("127.0.0.1", page.server.port, timeout=5)
    conn.request("GET", "/t/")
    assert '<option value="movies">Movies</option>' in conn.getresponse().read().decode()
    conn = http.client.HTTPConnection("127.0.0.1", page.server.port, timeout=5)
    conn.request("PUT", "/t/upload?folder=movies&name=Up%20(2009).mkv", body=b"movie")
    assert conn.getresponse().status == 200
    conn = http.client.HTTPConnection("127.0.0.1", page.server.port, timeout=5)
    conn.request("PUT", "/t/upload?folder=roms/snes&name=x.sfc", body=b"x")
    assert conn.getresponse().status == 400  # only movies here
    qtbot.waitUntil(lambda: "movies/Up (2009).mkv" in page.log.text())
    page.done_button.click()
    assert tab.currentWidget() is tab.home and page.server is None and not share.running
    qtbot.waitUntil(lambda: "Up (2009).mkv" in tab.home.cards)


def test_real_upload_page_shares_the_movies_folder(qtbot, tmp_path):
    share = Share()
    page = MovieUploadPage(tmp_path / "Movies", share=share, ip=lambda: "10.0.0.2")
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: share.folders == [str(tmp_path / "Movies")])
    assert (tmp_path / "Movies").is_dir() and page.server.folders() == {"movies": ("Movies", tmp_path / "Movies")}
    page.hide()


def test_playback_keeps_the_place_and_marks_watched(qtbot, root, tmp_path):
    where = {"now": (1234.0, 6000.0)}
    tab = make_tab(qtbot, root)
    tab.playback.position = lambda sock: where["now"]
    tab.playback.socket_path = lambda: tmp_path / "mpv.sock"
    matrix = next(m for m in tab.movies if m.title == "The Matrix")
    tab.playback.start(matrix)
    tab.playback.poll()
    qtbot.waitUntil(lambda: library.read_info(matrix.info_path).position == 1234.0)
    tab.movie_ended(matrix.appid + 1)  # something else ended
    assert tab.playback.movie is matrix
    where["now"] = (5900.0, 6000.0)
    tab.playback.poll()
    qtbot.waitUntil(lambda: library.read_info(matrix.info_path).position == 5900.0)
    tab.movie_ended(matrix.appid)
    qtbot.waitUntil(lambda: tab.home.cards["The Matrix (1999).mkv"].movie.info.watched)
    info = library.read_info(matrix.info_path)
    assert info.watched and info.position == 0 and tab.playback.movie is None


def test_no_progress_written_after_the_end(qtbot, root, tmp_path):
    playback = Playback(position=lambda sock: (100.0, 6000.0), socket_path=lambda: tmp_path / "s")
    matrix = next(m for m in library.scan(root) if m.title == "The Matrix")
    playback.start(matrix)
    playback.finish(matrix.appid)
    playback.poll()  # a late tick
    qtbot.wait(100)
    assert library.read_info(matrix.info_path).position == 0


# --- in the app -----------------------------------------------------------------------------
@pytest.fixture
def window(qtbot, root, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    launched = []
    monkeypatch.setattr(player, "launch", lambda movie, data, logs, start=0, **k: (
        launched.append((movie.title, start, k.get("languages"))), (True, f"Playing {movie.title}"))[1])
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"])
        pages["Movies"] = MoviesTab(root, lookup=FakeLookup(), languages=("de", "en"))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    movies = pages["Movies"]
    qtbot.waitUntil(lambda: len(movies.movies) == 3)
    w._movies, w._launched = movies, launched
    return w


def test_playing_from_the_tab_starts_it_like_a_game(qtbot, window):
    movies = window._movies
    assert window.shell.pages["Movies"] is movies and movies.player_launcher == window.launch_movie
    nemo = next(m for m in movies.movies if m.title == "Finding Nemo")
    ok, _message = movies.play(nemo)
    assert ok and window._launched == [("Finding Nemo", 1800, ("de", "en"))]
    assert window.game_watcher.appid == nemo.appid and window.launch_overlay.isVisible()
    assert window.launch_overlay.phase.text() == "Starting the movie…"
    from gamingcrypt.ui.game_watcher import QUICK

    assert window.game_watcher.timing is QUICK  # no waiting like for a Steam game
    assert window.game_name(nemo.appid) == "Finding Nemo"
    window.game_watcher.phase = "playing"
    window.hide()
    assert window.running_movie() is nemo and window.emulated_game_in_front()  # the volume popup shows
    movies.playback.position = lambda sock: (5800.0, 6000.0)
    movies.playback.poll()
    qtbot.waitUntil(lambda: library.read_info(nemo.info_path).position == 5800.0)
    window.game_ended(nemo.appid)
    qtbot.waitUntil(lambda: library.read_info(nemo.info_path).watched)


def test_quick_menu_stops_a_movie_with_one_tap(qtbot, window, monkeypatch):
    movies = window._movies
    matrix = next(m for m in movies.movies if m.title == "The Matrix")
    movies.play(matrix)
    window.game_watcher.phase = "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.title.text() == "The Matrix" and menu.back_button.text() == "▶  Back to the movie"
    assert menu.quit_button.text() == "■  Stop the movie"
    quit_asked = []
    menu.force_quit.connect(quit_asked.append)
    menu.quit_button.click()
    assert quit_asked == [matrix.appid]
    menu.close_menu()


def test_quick_menu_for_a_game_still_asks_twice(qtbot, window):
    window.toggle_quick_menu()
    menu = window.quick_menu
    menu.open_menu(730, "Some game")
    assert menu.quit_button.text() == "✕  Force quit" and menu.back_button.text() == "▶  Back to the game"
    quit_asked = []
    menu.force_quit.connect(quit_asked.append)
    menu.quit_button.click()
    assert quit_asked == [] and menu.quit_button.text() == "Tap again to force quit"
    menu.close_menu()


def test_no_performance_overlay_over_movies(qtbot, window, monkeypatch):
    from gamingcrypt.system import gamescope_ctl

    monkeypatch.setattr("gamingcrypt.session.mode.in_gaming_session", lambda *a, **k: True)
    shown = []
    monkeypatch.setattr(gamescope_ctl, "apply_overlay", lambda over_game, env=None: shown.append(over_game))
    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order, runner=None: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda *a, **k: True)
    touch = []
    monkeypatch.setattr(gamescope_ctl, "set_touch_mode", lambda mode, runner=None: touch.append(mode) or True)
    movie = window._movies.movies[0]
    window.game_watcher.appid, window.game_watcher.phase = movie.appid, "playing"
    window.game_watcher.timer.stop()
    window.gamescope_focus("game")
    window.game_watcher.appid = 730
    window.gamescope_focus("game")
    assert shown == [False, True]
    # touches: clicks for the player, real touches again for everything else - and only then
    assert touch == [gamescope_ctl.TOUCH_LEFT_CLICK, gamescope_ctl.TOUCH_PASSTHROUGH]
    window.gamescope_focus("launcher")
    assert len(touch) == 2
    window.game_watcher.appid = movie.appid
    window.gamescope_focus("game")
    window.gamescope_focus("launcher")  # quick menu over the movie: GamingCrypt needs real touches
    assert touch[2:] == [gamescope_ctl.TOUCH_LEFT_CLICK, gamescope_ctl.TOUCH_PASSTHROUGH]
    window.game_watcher.appid = None
    window.game_watcher.phase = "idle"


def test_default_pages_have_the_movies_tab(monkeypatch):
    from gamingcrypt import app
    from gamingcrypt.config import DEFAULTS

    config = copy.deepcopy(DEFAULTS)
    config["unlock"]["mount_point"] = "/tmp/nowhere-gamingcrypt"
    config["steam"]["language"] = "german"
    movies = app.default_pages(config)["Movies"]
    assert str(movies.root) == "/tmp/nowhere-gamingcrypt/Movies" and movies.languages == ("de", "en")
    config["unlock"]["mount_point"] = ""
    assert app.default_pages(config)["Movies"].root is None


def test_install_script_installs_the_player():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "install.sh").read_text()
    assert "install_player() {" in script and "pacman -S --needed --noconfirm mpv" in script
    assert "\n    install_player\n" in script


def test_card_is_a_movie_card(qtbot, root):
    card = MovieCard(library.scan(root)[0])
    qtbot.addWidget(card)
    clicked = []
    card.clicked.connect(clicked.append)
    card.tapped.emit()
    assert clicked == [card.movie]


def test_the_controller_steers_the_movie(qtbot, window, monkeypatch):
    from gamingcrypt.input import evdev as e

    sent = []
    monkeypatch.setattr(player, "send", lambda sock, text, timeout=1.0: sent.append(text) or True)
    movies = window._movies
    matrix = next(m for m in movies.movies if m.title == "The Matrix")
    movies.play(matrix)
    window.game_watcher.phase = "playing"
    assert not window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 1)  # GamingCrypt still in front: it navigates
    window.hide()  # the movie is on screen
    assert window.movie_in_front()
    assert window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 1) and window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 0)
    assert window.pad_hotkey(e.EV_ABS, e.ABS_HAT0X, 1) and window.pad_hotkey(e.EV_ABS, e.ABS_HAT0X, 0)
    window.pad_hotkey(e.EV_KEY, e.BTN_EAST, 1)
    qtbot.waitUntil(lambda: len(sent) == 3)
    assert sorted(sent) == sorted(["osd-msg cycle pause", "osd-msg-bar seek 30", "quit"])
    window.game_watcher.appid = None  # over
    window.game_watcher.phase = "idle"
    assert not window.movie_in_front() and not window.pad_hotkey(e.EV_KEY, e.BTN_SOUTH, 1)


def test_the_quick_menu_button_still_works_during_a_movie(qtbot, window, monkeypatch):
    from gamingcrypt.input import evdev as e

    monkeypatch.setattr(player, "send", lambda *a, **k: True)
    window.config["input"]["hotkeys"] = {"quick_menu": {"source": "pad", "codes": [e.BTN_MODE]}}
    window.reload_hotkeys()
    movies = window._movies
    movies.play(movies.movies[0])
    window.game_watcher.phase = "playing"
    window.hide()
    opened = []
    monkeypatch.setattr(window, "toggle_quick_menu", lambda: opened.append(True))
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 1)
    window.pad_hotkey(e.EV_KEY, e.BTN_MODE, 0)
    assert opened == [True]


def test_volume_popup_is_cleared_when_the_movie_ends(qtbot, window):
    dismissed = []
    window.game_volume_osd = type("Overlay", (), {"dismiss": lambda self: dismissed.append(True)})()
    window.game_over(window._movies.movies[0].appid)
    assert dismissed == [True]

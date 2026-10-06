"""Shows tab: a card per show, its page with seasons and episodes, Continue, the next episode."""

import copy
import http.client

import pytest
from PySide6.QtGui import QColor

from gamingcrypt.movies import library as movies
from gamingcrypt.movies import player
from gamingcrypt.movies.library import MovieInfo
from gamingcrypt.shows import library
from gamingcrypt.ui.shows_tab import ShowCard, ShowPage, ShowsTab, ShowUploadPage, show_cover, upload_folders


class FakeLookup:
    def __init__(self):
        self.asked = []

    def find(self, name, year):
        self.asked.append(name)
        return None


def episode(root, rel, **info):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"v" * 50)
    movies.write_info(path.with_suffix(".nfo"), MovieInfo(looked_up=1, **info), "episodedetails")
    return path


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "GamingCrypt" / "Shows"
    for season in (1, 2):
        for number in (1, 2, 3):
            seen = season == 1 and number < 3
            episode(root, f"Breaking Bad (2008)/Season {season}/Breaking Bad S0{season}E0{number}.mkv",
                    title=f"Episode {season}.{number}", runtime=47, aired="2008-01-20", plot="Walter cooks.",
                    watched=seen, playcount=int(seen))
    movies.write_info(root / "Breaking Bad (2008)" / "tvshow.nfo", MovieInfo(
        title="Breaking Bad", year=2008, end_year=2013, fsk="FSK 16", genres=["Drama", "Crime"], tvmaze="169",
        plot="A chemistry teacher.", actors=[("Bryan Cranston", "Walter White")], looked_up=1), "tvshow")
    for number in (1, 2):
        episode(root, f"Dark.S01E0{number}.mkv", title=f"Dark {number}", watched=True, playcount=1)
    movies.write_info(root / "Dark.tvshow.nfo", MovieInfo(title="Dark", year=2017, genres=["Mystery"],
                                                          looked_up=1, tvmaze="17861"), "tvshow")
    return root


def make_tab(qtbot, root, launcher=None):
    tab = ShowsTab(root, lookup=FakeLookup())
    tab.player_launcher = launcher
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitUntil(lambda: len(tab.home.cards) == 2)
    return tab


def titles(tab):
    return [tab.home.cards[key].movie.title for key in tab.home.shown]


def test_one_card_per_show_not_per_episode(qtbot, root):
    tab = make_tab(qtbot, root)
    assert titles(tab) == ["Breaking Bad", "Dark"] and tab.home.count_label.text() == "2 shows"
    card = tab.home.cards["folder:Breaking Bad (2008)"]
    assert isinstance(card, ShowCard) and card.meta.text() == "2008-2013 · 2 seasons"
    assert tab.home.add_button.text() == "⬆  Add shows"


def test_card_badges(qtbot, root):
    shows = {s.title: s for s in library.scan(root)}
    bb = show_cover(shows["Breaking Bad"], 200, 300).toImage()
    dark = show_cover(shows["Dark"], 200, 300).toImage()
    badge = QColor(bb.pixel(200 - 8 - 29, 8 + 16))  # beside the digit
    assert badge.blue() > 200 and badge.red() < 120  # 4 episodes left: the blue count
    assert QColor(dark.pixel(200 - 8 - 16, 8 + 16)).green() > 150  # all watched: the green ✓
    assert QColor(bb.pixel(20, 297)).blue() > 200  # how far: 2 of 6


def test_filters_work_on_shows(qtbot, root):
    tab = make_tab(qtbot, root)
    home = tab.home
    home.state_buttons["watched"].click()
    assert titles(tab) == ["Dark"]
    home.state_buttons["progress"].click()
    assert titles(tab) == ["Breaking Bad"]
    home.state_buttons["all"].click()
    home.search.setText("cranston")
    assert titles(tab) == ["Breaking Bad"]
    home.search.setText("")
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Mystery"))
    assert titles(tab) == ["Dark"]


def test_show_page(qtbot, root):
    tab = make_tab(qtbot, root)
    tab.home.cards["folder:Breaking Bad (2008)"].tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, ShowPage) and page.title.text() == "Breaking Bad"
    assert page.facts.text() == "2008-2013 · 2 seasons · 6 episodes · FSK 16\nDrama, Crime"
    assert page.progress.text() == "2 of 6 watched · next: S01E03 Episode 1.3"
    assert page.main_button.text() == "▶  Continue with S01E03"
    assert "Bryan Cranston  ·  Walter White" in page.people.text()
    # the season of the next episode is open; the other one a tap away
    assert page.season_buttons[1].isChecked() and list(page.rows) == [
        f"Breaking Bad (2008)/Season 1/Breaking Bad S01E0{n}.mkv" for n in (1, 2, 3)]
    row = page.rows["Breaking Bad (2008)/Season 1/Breaking Bad S01E01.mkv"]
    assert row.name.text() == "1. Episode 1.1" and row.meta.text() == "S01E01 · 47 min · 20 Jan 2008"
    assert row.watched_button.text() == "✓ Watched"
    page.season_buttons[2].click()
    assert [r.episode.code for r in page.rows.values()] == ["S02E01", "S02E02", "S02E03"]


def test_continue_plays_the_next_episode_and_rows_play_theirs(qtbot, root):
    played = []
    tab = make_tab(qtbot, root, launcher=lambda e, start: (played.append((e.code, start)), (True, "ok"))[1])
    tab.open_show(tab.shows[0])
    page = tab.currentWidget()
    page.main_button.click()
    page.rows["Breaking Bad (2008)/Season 1/Breaking Bad S01E01.mkv"].tapped.emit()
    assert played == [("S01E03", 0), ("S01E01", 0)]
    assert played and tab.playback.movie.code == "S01E01"


def test_the_next_episode_starts_when_one_ran_to_its_end(qtbot, root):
    played = []
    tab = make_tab(qtbot, root, launcher=lambda e, start: (played.append(e.code), (True, "ok"))[1])
    bb = tab.shows[0]
    current = bb.episodes[2]  # S01E03
    tab.play(current)
    tab.playback.position = lambda sock: (2790.0, 2800.0)  # the credits are over
    tab.playback.poll()
    qtbot.waitUntil(lambda: tab.playback.last_where is not None)
    tab.movie_ended(current.appid)
    qtbot.waitUntil(lambda: played == ["S01E03", "S02E01"])  # on into season 2
    assert library.scan(root)[0].episodes[2].info.watched


def test_stopped_before_the_end_starts_nothing(qtbot, root):
    played = []
    tab = make_tab(qtbot, root, launcher=lambda e, start: (played.append(e.code), (True, "ok"))[1])
    current = tab.shows[0].episodes[2]
    tab.play(current)
    tab.playback.position = lambda sock: (1500.0, 2800.0)
    tab.playback.poll()
    qtbot.waitUntil(lambda: tab.playback.last_where is not None)
    tab.movie_ended(current.appid)
    qtbot.waitUntil(lambda: library.scan(root)[0].episodes[2].info.resume_at == 1500.0)
    qtbot.wait(100)
    assert played == ["S01E03"]
    tab.open_show(tab.shows[0])
    qtbot.waitUntil(lambda: tab.currentWidget().main_button.text() == "▶  Continue S01E03 at 0:25:00")


def test_mark_episodes_and_the_whole_show(qtbot, root):
    tab = make_tab(qtbot, root)
    tab.open_show(tab.shows[0])
    page = tab.currentWidget()
    page.rows["Breaking Bad (2008)/Season 1/Breaking Bad S01E03.mkv"].watched_button.click()
    qtbot.waitUntil(lambda: page.progress.text().startswith("3 of 6 watched"))
    page.watched_button.click()
    qtbot.waitUntil(lambda: page.progress.text() == "✓ All watched")
    assert page.main_button.text() == "▶  Watch again from the start"
    assert page.watched_button.text() == "Mark as unwatched"
    page.watched_button.click()
    qtbot.waitUntil(lambda: page.main_button.text() == "▶  Play S01E01")


def test_remove_a_show(qtbot, root):
    tab = make_tab(qtbot, root)
    tab.open_show(next(s for s in tab.shows if s.title == "Breaking Bad"))
    page = tab.currentWidget()
    page.options_button.click()
    assert "6 episode files in Breaking Bad (2008)" in page.files_label.text()
    page.remove_button.click()
    assert "Really remove Breaking Bad?\nAll 6 episodes" in page.confirm.question.text()
    page.confirm.cancel_button.click()
    assert (root / "Breaking Bad (2008)").exists()
    page.remove_button.click()
    page.confirm.remove_button.click()
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.home)
    qtbot.waitUntil(lambda: titles(tab) == ["Dark"])
    assert not (root / "Breaking Bad (2008)").exists() and tab.home.notice.text().startswith("Breaking Bad removed")


def test_unknown_shows_are_looked_up(qtbot, root):
    (root / "The.Office.S01E01.mkv").write_bytes(b"v")
    tab = ShowsTab(root, lookup=FakeLookup())
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.lookup.asked == ["The Office"])
    qtbot.waitUntil(lambda: (root / "The Office.tvshow.nfo").exists())


def test_upload_into_the_shows_folder_or_a_show(qtbot, root):
    from gamingcrypt.emulation.upload_server import UploadServer

    folders = upload_folders(root)
    assert folders["shows"] == ("Shows (sorted by the names in the files)", root)
    assert folders["shows/Breaking Bad (2008)"] == ("Show: Breaking Bad (2008)", root / "Breaking Bad (2008)")

    class Share:
        user, password, running, folder = "u", "MapleOtter", False, None

        def start(self, folder):
            self.folder = folder
            return True, ""

        def stop(self):
            pass

    share = Share()
    tab = make_tab(qtbot, root)
    tab.upload_page_factory = lambda folder: ShowUploadPage(
        folder, share=share, ip=lambda: "10.0.0.2",
        server_factory=lambda f, received: UploadServer(None, received, token="t", ports=range(18200, 18230),
                                                        host="127.0.0.1", folders=lambda: upload_folders(f)))
    tab.home.add_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ShowUploadPage)
    qtbot.waitUntil(lambda: share.folder == str(root))
    conn = http.client.HTTPConnection("127.0.0.1", page.server.port, timeout=5)
    conn.request("PUT", "/t/upload?folder=shows/Breaking%20Bad%20(2008)&name=Breaking%20Bad%20S03E01.mkv", body=b"x")
    assert conn.getresponse().status == 200
    page.done_button.click()
    qtbot.waitUntil(lambda: len(next(s for s in tab.shows if s.title == "Breaking Bad").episodes) == 7)


def test_real_upload_page_offers_the_show_folders(qtbot, root):
    page = ShowUploadPage(root, ip=lambda: "10.0.0.2", share=type("S", (), {
        "user": "u", "password": "p", "running": False, "start": lambda self, f: (True, ""),
        "stop": lambda self: None})())
    qtbot.addWidget(page)
    page.show()
    qtbot.waitUntil(lambda: page.server is not None)
    assert set(page.server.folders()) == {"shows", "shows/Breaking Bad (2008)"}
    page.hide()


# --- in the app -----------------------------------------------------------------------------
@pytest.fixture
def window(qtbot, root, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    launched = []
    monkeypatch.setattr(player, "launch", lambda e, data, logs, start=0, **k: (
        launched.append((e.title, start)), (True, "Playing"))[1])
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"])
        pages["Shows"] = ShowsTab(root, lookup=FakeLookup())
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    qtbot.waitUntil(lambda: len(pages["Shows"].shows) == 2)
    w._shows, w._launched = pages["Shows"], launched
    return w


def test_episodes_play_like_movies(qtbot, window):
    shows = window._shows
    assert shows.player_launcher == window.launch_movie
    nxt = library.next_up(shows.shows[0])
    shows.play(nxt)
    assert window._launched == [("Breaking Bad - S01E03 - Episode 1.3", 0)]
    assert window.game_watcher.appid == nxt.appid and window.game_name(nxt.appid) == nxt.title
    window.game_watcher.phase = "playing"
    window.hide()
    assert window.running_movie() is nxt and window.movie_in_front()
    window.game_ended(nxt.appid)
    assert shows.playback.movie is None  # the shows tab took care of it


def test_default_pages_have_the_shows_tab():
    from gamingcrypt import app
    from gamingcrypt.config import DEFAULTS

    config = copy.deepcopy(DEFAULTS)
    config["unlock"]["mount_point"] = "/tmp/nowhere-gamingcrypt"
    shows = app.default_pages(config)["Shows"]
    assert isinstance(shows, ShowsTab) and str(shows.root) == "/tmp/nowhere-gamingcrypt/Shows"

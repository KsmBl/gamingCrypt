"""Continue watching: the movie stopped in the middle / the next episode of the show watched
last, at the top of Movies and Shows."""

import time

from gamingcrypt.movies import library as movies
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import put
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture
from tests.test_shows_tab import make_tab as make_shows_tab
from tests.test_shows_tab import root as shows_root  # noqa: F401 - fixture


def test_the_movie_stopped_last(qtbot, movies_root):  # noqa: F811
    put(movies_root, "Heat.mkv", title="Heat", position=600, total=10200, last_played=time.time())
    played = []
    tab = make_movies_tab(qtbot, movies_root, launcher=lambda movie, start: played.append((movie.title, start))
                          or (True, ""))
    card = tab.home.continue_card
    assert card.isVisible() and card.title.text() == "Heat"  # Nemo was stopped too, but longer ago
    assert card.meta.text() == "Stopped at 0:10:00 · 160 min left" and card.play_button.text() == "▶  Resume"
    card.play_button.click()
    assert played == [("Heat", 600)]
    card.details_button.click()
    assert tab.currentWidget().movie.title == "Heat"


def test_hidden_while_searching_or_filtering_and_when_nothing_was_started(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    home = tab.home
    assert home.continue_card.isVisible() and home.continue_card.title.text() == "Finding Nemo"
    home.search.setText("matrix")
    assert not home.continue_card.isVisible()
    home.search.setText("")
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Horror"))
    assert not home.continue_card.isVisible()
    home.clear_button.click()
    nemo = next(m for m in tab.movies if m.title == "Finding Nemo")
    movies.set_watched(nemo, True)
    tab.movie_changed(nemo)
    assert not home.continue_card.isVisible()


def test_the_next_episode_of_the_show_watched_last(qtbot, shows_root):  # noqa: F811
    episode = shows_root / "Breaking Bad (2008)" / "Season 1" / "Breaking Bad S01E02.nfo"
    info = movies.read_info(episode)
    info.last_played = time.time()
    movies.write_info(episode, info, "episodedetails")
    played = []
    tab = make_shows_tab(qtbot, shows_root, launcher=lambda ep, start: played.append(ep.code) or (True, ""))
    card = tab.home.continue_card
    assert card.isVisible() and card.title.text() == "Breaking Bad"
    assert card.meta.text() == "S01E03 · Episode 1.3" and card.play_button.text() == "▶  Play"
    card.play_button.click()
    assert played == ["S01E03"]
    card.details_button.click()
    assert tab.currentWidget().show_item.title == "Breaking Bad"


def test_no_show_watched_yet(qtbot, shows_root):  # noqa: F811
    tab = make_shows_tab(qtbot, shows_root)
    assert not tab.home.continue_card.isVisible()

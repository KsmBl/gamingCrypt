"""The D-pad goes where an average user expects it to - on the real pages.

Left / right stay in their row (the end of a grid row goes on with the next row), up / down
go to the next row in the same column, a row of tabs or chips is entered at the selected one,
and up in a scrolled list first goes back to the list's top.
"""

import copy

import pytest

from gamingcrypt.movies import library as movies
from gamingcrypt.movies.library import MovieInfo
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.navigator import GamepadNavigator


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


@pytest.fixture
def app(qtbot, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui import theme
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.movies_tab import MoviesTab
    from gamingcrypt.ui.shows_tab import ShowsTab
    from tests.fakes import FakeService

    emu = tmp_path / "Emulation"
    (emu / "roms" / "snes").mkdir(parents=True)
    (emu / "roms" / "snes" / "Super Mario World.sfc").write_bytes(b"x")
    for i, title in enumerate(["Alien", "Blade Runner", "Dune", "Up", "Arrival", "Heat", "Jaws", "Rocky"]):
        path = tmp_path / "Movies" / f"{title}.mkv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"v")
        movies.write_info(path.with_suffix(".nfo"), MovieInfo(title=title, year=1980 + i, looked_up=1, wikidata="Q1"))
    for season in (1, 2):
        for number in (1, 2, 3):
            path = tmp_path / "Shows" / "Dark" / f"Season {season}" / f"Dark S0{season}E0{number}.mkv"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"v")

    class Lookup:
        def find(self, *a):
            return None

    service = FakeService()
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(service, library_settings=cfg["libraries"], emulation_root=str(emu))
        pages["Movies"] = MoviesTab(tmp_path / "Movies", lookup=Lookup())
        pages["Shows"] = ShowsTab(tmp_path / "Shows", lookup=Lookup())
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.setStyleSheet(theme.STYLESHEET)
    w.windowed = True
    w.update_check_enabled = False
    w.resize(1280, 800)
    w.show()
    w.show_shell()
    qtbot.waitExposed(w)
    games = pages["Games"]
    games.games.update({g.appid: g for g in service.games})
    qtbot.waitUntil(lambda: "snes" in games.home.system_cards and bool(games.home.cards))
    qtbot.waitUntil(lambda: len(pages["Movies"].items) == 8 and len(pages["Shows"].items) == 1)
    nav = GamepadNavigator(w)
    return w, nav, pages


def go(qtbot, nav, moves: str):
    for m in moves:
        nav.move(*{"R": (1, 0), "L": (-1, 0), "U": (0, -1), "D": (0, 1)}[m])
        qtbot.wait(20)
    return nav.focused()


def test_grid_rows_go_on_with_the_next_row(qtbot, app):
    w, nav, pages = app
    home = pages["Games"].home
    nav.focus(w.shell.tab_buttons["Games"])
    assert go(qtbot, nav, "D") is home.search
    assert go(qtbot, nav, "D") is home.genre_combo  # the filters below the search
    assert go(qtbot, nav, "D") is home.favorites_card  # the first one, from the left
    assert go(qtbot, nav, "RR") is home.recent_card
    assert go(qtbot, nav, "R") is home.system_cards["snes"]  # end of the row: the next row
    assert go(qtbot, nav, "L") is home.recent_card  # and back
    assert go(qtbot, nav, "RRR") is home.add_card
    assert go(qtbot, nav, "RRRR") is not w.shell.exit_button  # never off to the power button


def test_up_from_a_page_lands_on_the_open_tab(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Movies")
    movies_home = pages["Movies"].home
    nav.focus(movies_home.cards[movies_home.shown[0]])
    target = go(qtbot, nav, "UUUU")
    assert target is w.shell.tab_buttons["Movies"]


def test_up_and_down_keep_the_column(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Movies")
    home = pages["Movies"].home
    third = home.cards[home.shown[2]]
    nav.focus(third)
    assert go(qtbot, nav, "D") is home.cards[home.shown[7]]  # the row below, same column (5 per row)
    assert go(qtbot, nav, "U") is third
    up = go(qtbot, nav, "U")
    if up is third:  # the first press brought the list back to its top
        qtbot.wait(300)
        up = go(qtbot, nav, "U")
    assert up is not third and not home.grid_widget.isAncestorOf(up)  # out of the grid, into the filters
    while up is not home.search and up is not None and home.header.isAncestorOf(up):
        up = go(qtbot, nav, "U")
    assert up is home.search
    while not isinstance(go(qtbot, nav, "D"), type(third)):
        pass
    assert nav.focused() is third  # back where it came from, not the middle or the first


def test_chips_and_tabs_are_entered_at_the_selected_one(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Settings")
    settings = w.shell.pages["Settings"]
    nav.focus(w.shell.tab_buttons["Settings"])
    target = go(qtbot, nav, "D")
    assert target.isChecked() and target.text() == "Device"  # the open sub-tab, not the nearest one
    w.shell.show_tab("Movies")
    home = pages["Movies"].home
    home.state_buttons["watched"].click()
    home.state_buttons["all"].click()
    home.set_state("progress")
    home.set_state("all")
    nav.focus(home.search)
    target = go(qtbot, nav, "D")
    assert target in home.state_buttons.values() or target in (home.genre_combo, home.age_combo, home.sort_combo)
    if target in home.state_buttons.values():
        assert target is home.state_buttons["all"]
    del settings


def test_show_page_goes_through_actions_seasons_and_episodes(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Shows")
    shows = pages["Shows"]
    shows.open_show(shows.items[0])
    page = shows.currentWidget()
    qtbot.wait(300)  # the page settles (it's filled again when the list was read)
    nav.focus(page.main_button)
    assert go(qtbot, nav, "R") is page.watched_button
    assert go(qtbot, nav, "RRR") is page.options_button  # the end of the row: stays
    assert go(qtbot, nav, "D") is page.season_buttons[1]  # the open season
    rows = list(page.rows.values())
    assert go(qtbot, nav, "D") is rows[0] and go(qtbot, nav, "DD") is rows[2]
    assert go(qtbot, nav, "D") is rows[2]  # the last one: stays
    assert go(qtbot, nav, "UUU") is page.season_buttons[1]
    page.season_buttons[2].click()
    qtbot.wait(100)
    nav.focus(list(page.rows.values())[0])
    assert go(qtbot, nav, "U") is page.season_buttons[2]  # the season shown now


def test_up_in_a_scrolled_list_first_goes_to_its_top(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Shows")
    shows = pages["Shows"]
    shows.open_show(shows.items[0])
    page = shows.currentWidget()
    qtbot.wait(300)
    bar = page.scroll.verticalScrollBar()
    first = list(page.rows.values())[0]
    nav.focus(page.season_buttons[1])
    nav.focus(first)
    qtbot.waitUntil(lambda: bar.value() > 0 or bar.maximum() == 0)
    if bar.maximum() == 0:
        pytest.skip("the page fits on the screen")
    assert go(qtbot, nav, "U") is page.season_buttons[1]


def test_end_of_a_button_row_stays(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Movies")
    movies_tab = pages["Movies"]
    movies_tab.open_movie(movies_tab.items[0])
    page = movies_tab.currentWidget()
    nav.focus(page.options_button)
    assert go(qtbot, nav, "RR") is page.options_button
    assert go(qtbot, nav, "U") is not w.shell.exit_button


@pytest.mark.parametrize("kind", ["rom", "steam"])
def test_right_from_play_goes_to_options_not_over_it(qtbot, app, kind):
    """Options and Favorite are on / off buttons, not a row to pick one from: with the game a
    favorite, right from Play went straight to the (checked) Favorite."""
    w, nav, pages = app
    games = pages["Games"]
    if kind == "rom":
        game = games.roms["snes"][0]
        games.profiles.set(game.appid, "favorite", True)
        games.open_rom(game)
    else:
        games.profiles.set(620, "favorite", True)
        games.open_game(620)
    page = games.currentWidget()
    qtbot.wait(100)
    assert page.favorite_button.isChecked()
    nav.focus(page.main_button)
    assert go(qtbot, nav, "R") is page.options_button
    assert go(qtbot, nav, "R") is page.favorite_button
    assert go(qtbot, nav, "L") is page.options_button


def test_choice_rows_are_still_entered_at_the_picked_one(qtbot, app):
    w, nav, pages = app
    games = pages["Games"]
    games.open_steam()
    page = games.currentWidget()
    qtbot.wait(100)
    page.set_sort("playtime")
    nav.focus(page.search)
    target = go(qtbot, nav, "U")
    assert target is page.sort_buttons["playtime"]  # the sort order in use, not the nearest


def test_sideways_into_a_choice_row_goes_to_the_neighbour(qtbot, app):
    """Only coming from above / below lands on the picked tab or chip - sideways it's the next one."""
    w, nav, pages = app
    shell = w.shell
    nav.focus(shell.exit_button)
    assert go(qtbot, nav, "L") is shell.tab_buttons["Settings"]  # not all the way to "Games"
    games = pages["Games"]
    games.open_steam()
    page = games.currentWidget()
    qtbot.wait(100)
    nav.focus(page.direction_button)
    assert go(qtbot, nav, "L") is page.sort_buttons["last_update"]  # not the picked "Name"
    w.shell.show_tab("Movies")
    home = pages["Movies"].home
    qtbot.wait(200)  # the tab laid out
    nav.focus(home.genre_combo)
    assert go(qtbot, nav, "L") is home.state_buttons["watched"]  # not the picked "All"


def test_up_from_the_keyboard_goes_back_to_its_field(qtbot, app):
    w, nav, pages = app
    w.shell.show_tab("Movies")
    home = pages["Movies"].home
    nav.focus(home.search)
    nav.activate()
    qtbot.waitUntil(home.keyboard.isVisible)
    key = nav.focused()
    assert home.keyboard.isAncestorOf(key)
    assert go(qtbot, nav, "U") is home.search  # not a movie card behind the keyboard


def test_a_list_with_nothing_on_screen_yet_can_be_entered(qtbot, app):
    """Settings -> Health: only text at the top, the button further down - down from the tab
    reached nothing."""
    w, nav, pages = app
    w.shell.show_tab("Settings")
    settings = w.shell.pages["Settings"]
    settings.show_sub_tab("Health")
    qtbot.wait(200)
    nav.focus(settings.sub_buttons["Health"])
    target = go(qtbot, nav, "D")
    assert target is not settings.sub_buttons["Health"]
    assert settings.sub_pages["Health"].isAncestorOf(target)


@pytest.mark.parametrize("library", ["steam", "favorites", "recent", "system"])
def test_libraries_open_on_their_first_game(qtbot, app, library):
    w, nav, pages = app
    games = pages["Games"]
    games.profiles.set(1145360, "favorite", True)
    for game in games.service.games:
        game.last_played = 1700000000 + game.appid  # something recently played
    nav.focus(games.home.steam_card)
    {"steam": games.open_steam, "favorites": games.open_favorites, "recent": games.open_recent,
     "system": lambda: games.open_system("snes")}[library]()
    page = games.currentWidget()
    first = lambda: page.cards.get(page.order[0] if hasattr(page, "order") and page.order  # noqa: E731
                                   else (page.shown[0] if getattr(page, "shown", None) else None))
    qtbot.waitUntil(lambda: first() is not None and w.focusWidget() is first())
    assert not (w.focusWidget().property("back"))


def test_store_opens_ready_to_search(qtbot, app):
    w, nav, pages = app
    games = pages["Games"]
    games.open_store()
    page = games.currentWidget()
    qtbot.wait(100)
    assert not page.keyboard.isVisible() and w.focusWidget() is page.search
    nav.back()
    qtbot.wait(100)
    assert games.currentWidget() is games.home  # one B: out of the store


def test_controller_picture_reads_like_the_picture(qtbot, app):
    w, nav, pages = app
    games = pages["Games"]
    games.open_controls("snes")
    page = games.currentWidget()
    qtbot.wait(200)
    buttons = page.picture.buttons
    nav.focus(buttons["B"])
    assert go(qtbot, nav, "L") is buttons["Y"]  # the diamond's left one, not across to the D-pad
    nav.focus(buttons["B"])
    assert go(qtbot, nav, "R") is buttons["A"]
    nav.focus(buttons["Y"])
    assert go(qtbot, nav, "U") is buttons["X"]


def test_shader_page_goes_down_the_list(qtbot, app):
    w, nav, pages = app
    games = pages["Games"]
    game = games.roms["snes"][0]
    games.open_rom(game)
    games.currentWidget().shaders_button.click()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: nav.focused() is page.same_button)  # opens on the picked choice
    assert go(qtbot, nav, "R") is page.own_button
    assert go(qtbot, nav, "D") is page.rows["handheld_colors"]  # down into the list
    assert go(qtbot, nav, "D") is page.rows["ntsc"]
    assert go(qtbot, nav, "DD") is page.rows["sharpen"]  # over the group's heading
    nav.activate()
    assert page.rows["sharpen"].isChecked() and page.own_button.isChecked()
    assert go(qtbot, nav, "UUUU") in (page.same_button, page.own_button)

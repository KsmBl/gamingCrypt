"""Dark and light theme: the same design, switched at once in Settings -> Device -> Appearance."""

import copy

import pytest
from PySide6.QtGui import QColor

from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui import theme


@pytest.fixture(autouse=True)
def back_to_dark():
    yield
    theme.apply(theme.DEFAULT, size="normal")


def test_both_themes_have_every_colour():
    dark, light = theme.PALETTES["dark"], theme.PALETTES["light"]
    assert set(dark) == set(light) and set(theme.THEMES) == {"dark", "light"}
    assert QColor(dark["BG"]).lightness() < 40 and QColor(light["BG"]).lightness() > 200
    assert QColor(dark["TEXT"]).lightness() > 200 and QColor(light["TEXT"]).lightness() < 60


def test_apply_switches_colours_and_stylesheet():
    dark_css = theme.STYLESHEET
    assert theme.apply("light") == "light" and theme.current == "light"
    assert theme.BG == theme.PALETTES["light"]["BG"] and theme.STYLESHEET != dark_css
    assert f"background: {theme.PALETTES['light']['BG']}" in theme.STYLESHEET
    assert theme.apply("purple") == "dark"  # unknown: the default


def test_the_same_rules_in_both_themes():
    """One design: the themes differ only in colour."""
    import re

    selectors = []
    for name in theme.THEMES:
        theme.apply(name)
        selectors.append(re.findall(r"^([^\s{][^{]*)\{", theme.STYLESHEET, re.MULTILINE))
    assert selectors[0] == selectors[1] and len(selectors[0]) > 40


def test_listeners_hear_about_it():
    heard = []
    theme.on_change(lambda: heard.append(theme.current))
    theme.apply("light")
    assert heard[-1] == "light"


def test_dropdown_arrow_in_the_themes_colour():
    theme.apply("light")
    arrow = theme._chevron(theme.TEXT_DIM)
    assert theme.TEXT_DIM in open(arrow).read() and f"url({arrow})" in theme.STYLESHEET


def test_config_default_and_choice():
    assert DEFAULTS["appearance"]["theme"] == "dark"
    assert theme.from_config({"appearance": {"theme": "light"}}) == "light"
    assert theme.from_config({}) == "dark"


def test_settings_switch_it_at_once(qtbot):
    from PySide6.QtWidgets import QApplication

    from gamingcrypt.ui.system_settings import AppearanceSection

    config = copy.deepcopy(DEFAULTS)
    saved = []
    section = AppearanceSection(config, lambda c: saved.append(copy.deepcopy(c)))
    qtbot.addWidget(section)
    assert section.buttons["dark"].isChecked() and not section.buttons["light"].isChecked()
    app = QApplication.instance()
    before = app.styleSheet()
    try:
        section.buttons["light"].click()
        assert config["appearance"]["theme"] == "light" and saved[-1]["appearance"]["theme"] == "light"
        assert theme.current == "light" and app.styleSheet() == theme.STYLESHEET
        assert section.buttons["light"].isChecked() and not section.buttons["dark"].isChecked()
    finally:
        app.setStyleSheet(before)


def test_covers_without_artwork_follow_the_theme():
    from gamingcrypt.ui.game_widgets import placeholder_cover

    dark = QColor(placeholder_cover("Portal", 200, 300).toImage().pixel(5, 5))
    theme.apply("light")
    light = QColor(placeholder_cover("Portal", 200, 300).toImage().pixel(5, 5))
    assert light.lightness() > dark.lightness() + 60
    other = QColor(placeholder_cover("Hades", 200, 300).toImage().pixel(5, 5))
    assert other.hue() != light.hue()  # every title its own colour


def test_covers_have_rounded_corners(qtbot):
    from PySide6.QtGui import QPixmap

    from gamingcrypt.ui.game_widgets import Cover

    cover = Cover()
    cover.setFixedSize(100, 150)
    pixmap = QPixmap(100, 150)
    pixmap.fill(QColor("red"))
    cover.setPixmap(pixmap)
    qtbot.addWidget(cover)
    cover.show()
    image = cover.grab().toImage()
    assert QColor(image.pixel(50, 75)).red() > 200  # the picture
    assert QColor(image.pixel(0, 0)).green() > 100  # but not in the rounded-off corner


def test_window_redraws_its_pictures_when_switched(qtbot):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(FakeService())})
    qtbot.addWidget(window)
    window.windowed = True
    window.update_check_enabled = False
    window.show()
    window.show_shell()
    home = window.shell.pages["Games"].home
    qtbot.waitUntil(lambda: bool(home.cards))
    old = dict(home.cards)
    theme.apply("light")
    assert all(home.cards.get(k) is not card for k, card in old.items())  # new cards, drawn in light


def test_text_size_makes_every_text_bigger():
    normal = theme.stylesheet(theme.PALETTES["dark"])
    assert "QLabel#title { font-size: 34px;" in normal
    theme.apply("dark", size="larger")
    assert "QLabel#title { font-size: 44px;" in theme.STYLESHEET and "font-size: 26px;" in theme.STYLESHEET  # 20 -> 26
    theme.apply("light")  # switching the theme keeps the size
    assert theme.text_size == "larger" and "QLabel#title { font-size: 44px;" in theme.STYLESHEET
    theme.apply("dark", size="huge")  # unknown: normal
    assert theme.text_size == "normal" and theme.STYLESHEET == normal
    config = copy.deepcopy(DEFAULTS)
    assert theme.size_from_config(config) == "normal"


def test_text_size_in_settings(qtbot):
    from PySide6.QtWidgets import QApplication

    from gamingcrypt.ui.system_settings import AppearanceSection

    config = copy.deepcopy(DEFAULTS)
    saved = []
    section = AppearanceSection(config, lambda c: saved.append(copy.deepcopy(c)))
    qtbot.addWidget(section)
    assert section.size_buttons["normal"].isChecked()
    app = QApplication.instance()
    before = app.styleSheet()
    try:
        section.size_buttons["large"].click()
        assert saved[-1]["appearance"]["text_size"] == "large" and theme.text_size == "large"
        assert app.styleSheet() == theme.STYLESHEET and "font-size: 23px;" in app.styleSheet()  # 20 -> 23
        assert section.size_buttons["large"].isChecked() and not section.size_buttons["normal"].isChecked()
    finally:
        app.setStyleSheet(before)


def test_the_tab_rows_keep_their_size():
    """They must fit the 1280 px screen - with every text size."""
    theme.apply("dark", size="larger")
    assert "padding: 16px 20px;\n    font-size: 22px;" in theme.STYLESHEET  # QPushButton#tab

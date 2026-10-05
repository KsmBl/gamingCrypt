"""Box art for emulated games from libretro-thumbnails, cached on the drive."""

from types import SimpleNamespace

import pytest
import requests

from gamingcrypt.emulation.covers import Covers, thumbnail_names, urls
from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.emulation.systems import BY_ID

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


def game(tmp_path, filename, system="snes"):
    return RomGame(BY_ID[system], tmp_path / filename, "x", 1)


def test_names_and_urls(tmp_path):
    exact = game(tmp_path, "Super Mario World (USA).sfc")
    assert thumbnail_names(exact) == ["Super Mario World (USA)"]
    assert urls(exact) == ["https://thumbnails.libretro.com/Nintendo%20-%20Super%20Nintendo%20Entertainment%20System/"
                           "Named_Boxarts/Super%20Mario%20World%20%28USA%29.png"]
    tidy = game(tmp_path, "Chrono Trigger.sfc")
    assert thumbnail_names(tidy)[:3] == ["Chrono Trigger", "Chrono Trigger (USA)", "Chrono Trigger (Europe)"]
    assert thumbnail_names(game(tmp_path, "Q*bert: Tales (USA).nes", "nes")) == ["Q_bert_ Tales (USA)"]


@pytest.fixture
def paths(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    return p


def test_downloaded_once_then_from_the_drive(paths, tmp_path):
    asked = []

    def get(url):
        asked.append(url)
        return SimpleNamespace(status_code=200 if "%28USA%29" in url else 404, content=PNG)

    covers = Covers(paths, get=get)
    tidy = game(tmp_path, "Chrono Trigger.sfc")
    path = covers.fetch(tidy)
    assert path == paths.config / "covers" / "snes" / "Chrono Trigger.png" and path.read_bytes() == PNG
    assert len(asked) == 2  # plain name, then "(USA)"
    assert covers.fetch(tidy) == path and len(asked) == 2  # cached on the drive


def test_misses_are_remembered_but_offline_isnt(paths, tmp_path):
    asked = []
    clock = [1000.0]
    covers = Covers(paths, get=lambda url: asked.append(url) or SimpleNamespace(status_code=404, content=b""),
                    now=lambda: clock[0])
    nothing = game(tmp_path, "Homebrew Thing.sfc")
    assert covers.fetch(nothing) is None
    first = len(asked)
    assert covers.fetch(nothing) is None and len(asked) == first  # not asked again ...
    clock[0] += 8 * 86400
    covers.fetch(nothing)
    assert len(asked) == 2 * first  # ... until a week later

    def offline(url):
        raise requests.ConnectionError("no network")

    other = game(tmp_path, "Other (USA).sfc")
    assert Covers(paths, get=offline).fetch(other) is None
    assert not (paths.config / "covers" / "snes" / "Other (USA).miss").exists()  # try again next time


def test_not_an_image_is_ignored(paths, tmp_path):
    covers = Covers(paths, get=lambda url: SimpleNamespace(status_code=200, content=b"<html>error</html>"))
    assert covers.fetch(game(tmp_path, "X (USA).sfc")) is None


def test_cards_show_the_cover(qtbot, paths, tmp_path):
    from PySide6.QtGui import QColor, QPixmap

    from gamingcrypt.ui.emulation_pages import RomCard

    image = QPixmap(60, 80)
    image.fill(QColor("#ff0000"))
    cover_file = paths.config / "covers" / "snes" / "Mario (USA).png"
    cover_file.parent.mkdir(parents=True)
    image.save(str(cover_file))
    card = RomCard(game(tmp_path, "Mario (USA).sfc"), covers=Covers(paths, get=lambda url: None))
    qtbot.addWidget(card)
    shown = card.cover.pixmap().toImage()
    assert QColor(shown.pixel(shown.width() // 2, shown.height() // 2)) == QColor("#ff0000")

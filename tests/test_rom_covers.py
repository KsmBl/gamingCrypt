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
    assert not (paths.config / "covers" / "snes" / "Other (USA).nomatch").exists()  # try again next time


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


INDEX = """<html><body>
<a href="Final%20Fantasy%20VII%20(Europe)%20(Disc%201).png">x</a>
<a href="Final%20Fantasy%20VII%20(Germany)%20(Disc%201).png">x</a>
<a href="Final%20Fantasy%20VIII%20(Germany)%20(Disc%201).png">x</a>
<a href="Final%20Fantasy%20(Japan).png">x</a>
<a href="Legend%20of%20Zelda,%20The%20-%20Ocarina%20of%20Time%20(USA).png">x</a>
<a href="?C=N;O=D">sort</a>
</body></html>"""


def test_best_match():
    from gamingcrypt.emulation.covers import best_match

    names = ["Final Fantasy VII (Europe) (Disc 1)", "Final Fantasy VII (Germany) (Disc 1)",
             "Final Fantasy VIII (Germany) (Disc 1)", "Final Fantasy (Japan)",
             "Legend of Zelda, The - Ocarina of Time (USA)", "Need for Speed - Underground (Europe)",
             "Need for Speed - Underground 2 (Europe) (v1.01)"]
    assert best_match("Final Fantasy VII - German Retranslation (v1.0).m3u", names) == \
        "Final Fantasy VII (Germany) (Disc 1)"  # the longest title, in the file's language
    assert best_match("FF7 (USA).bin", names) is None  # nothing fits: no wrong cover
    assert best_match("The Legend of Zelda Ocarina of Time Redux.z64", names) == \
        "Legend of Zelda, The - Ocarina of Time (USA)"
    assert best_match("Need for Speed - Underground 2 (v2.00).iso", names) == \
        "Need for Speed - Underground 2 (Europe) (v1.01)"


def test_cover_found_through_the_list(paths, tmp_path):
    asked = []

    def get(url):
        asked.append(url)
        if url.endswith("/Named_Boxarts/"):
            return SimpleNamespace(status_code=200, content=INDEX.encode())
        if "Germany" in url and "VII%20" in url:
            return SimpleNamespace(status_code=200, content=b"\x89PNG cover")
        return SimpleNamespace(status_code=404, content=b"")

    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.emulation.systems import BY_ID

    rom = tmp_path / "Final Fantasy VII - German Retranslation (v1.0).m3u"
    rom.write_text("x")
    ff7 = RomGame(BY_ID["psx"], rom, "Final Fantasy VII", 1)
    covers = Covers(paths, get=get)
    path = covers.fetch(ff7)
    assert path is not None and path.read_bytes() == b"\x89PNG cover"
    assert asked[-1].endswith("Final%20Fantasy%20VII%20%28Germany%29%20%28Disc%201%29.png")
    index_requests = sum(u.endswith("/Named_Boxarts/") for u in asked)
    other = tmp_path / "Final Fantasy VII (Disc 2) (Germany).cue"
    other.write_text("x")
    covers.fetch(RomGame(BY_ID["psx"], other, "x", 1))
    assert sum(u.endswith("/Named_Boxarts/") for u in asked) == index_requests  # the list is kept


def test_old_misses_are_retried(paths, tmp_path):
    (paths.config / "covers" / "snes").mkdir(parents=True)
    (paths.config / "covers" / "snes" / "Terranigma (Germany) (Rev 1).miss").write_text("9999999999")
    covers = Covers(paths, get=lambda url: SimpleNamespace(status_code=200, content=b"\x89PNG"))
    assert covers.fetch(game(tmp_path, "Terranigma (Germany) (Rev 1).sfc")) is not None

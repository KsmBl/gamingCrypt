"""RetroArch cores downloaded automatically from the libretro buildbot."""

import copy
import io
import threading
import time
import zipfile

import pytest
import requests

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import cores, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", ())  # only the drive's cores/ count
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    (p.roms / "snes" / "Super Mario World (USA).sfc").write_text("x")
    return p


def core_zip(name: str, data: bytes = b"\x7fELF core") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{name}_libretro.so", data)
    return buffer.getvalue()


class Response:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class Buildbot:
    """Offers the given cores; records what was asked."""

    def __init__(self, offered=("snes9x",), delay=0.0):
        self.offered, self.delay, self.asked = offered, delay, []

    def __call__(self, url):
        self.asked.append(url)
        time.sleep(self.delay)
        name = url.rsplit("/", 1)[1].removesuffix("_libretro.so.zip")
        return Response(200, core_zip(name)) if name in self.offered else Response(404)


def test_url_per_architecture():
    assert cores.url("snes9x", "x86_64") == \
        "https://buildbot.libretro.com/nightly/linux/x86_64/latest/snes9x_libretro.so.zip"
    assert cores.url("snes9x", "aarch64").startswith("https://buildbot.libretro.com/nightly/linux/aarch64/")
    assert cores.url("snes9x", "riscv64") is None


def test_download_unzips_into_the_drive(paths):
    bot = Buildbot()
    path = cores.download(paths, "snes9x", bot, "x86_64")
    assert path == paths.cores / "snes9x_libretro.so" and path.read_bytes() == b"\x7fELF core"
    assert not list(paths.cores.glob("*.part"))
    assert cores.download(paths, "snes9x", bot, "x86_64") == path and len(bot.asked) == 1  # already there


@pytest.mark.parametrize("get", [lambda u: Response(404), lambda u: Response(200, b"no zip"),
                                 lambda u: Response(200, core_zip("other")),
                                 lambda u: (_ for _ in ()).throw(requests.ConnectionError())])
def test_download_failures_leave_nothing(paths, get):
    assert cores.download(paths, "snes9x", get, "x86_64") is None
    assert not list(paths.cores.iterdir())


def test_ensure_takes_the_next_core_when_the_first_isnt_offered(paths):
    bot = Buildbot(offered=("bsnes",))
    assert cores.ensure(paths, BY_ID["snes"], get=bot, machine="x86_64") == paths.cores / "bsnes_libretro.so"
    assert [u.rsplit("/", 1)[1] for u in bot.asked] == ["snes9x_libretro.so.zip", "bsnes_libretro.so.zip"]
    assert cores.ensure(paths, BY_ID["snes"], get=bot, machine="x86_64") is not None and len(bot.asked) == 2


def test_ensure_prefers_the_games_chosen_core(paths):
    bot = Buildbot(offered=("snes9x", "bsnes"))
    assert cores.ensure(paths, BY_ID["snes"], "bsnes", bot, "x86_64").name == "bsnes_libretro.so"


def test_same_core_is_fetched_once_at_a_time(paths):
    bot = Buildbot(delay=0.2)
    threads = [threading.Thread(target=cores.download, args=(paths, "snes9x", bot, "x86_64")) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(bot.asked) == 1 and (paths.cores / "snes9x_libretro.so").exists()


def test_missing(paths):
    assert cores.missing(paths, [BY_ID["snes"], BY_ID["psx"]]) == [BY_ID["snes"], BY_ID["psx"]]
    (paths.cores / "swanstation_libretro.so").write_text("x")
    assert cores.missing(paths, [BY_ID["snes"], BY_ID["psx"]]) == [BY_ID["snes"]]


def test_library_fetches_cores_for_systems_with_games(qtbot, paths):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    asked = []

    def fetch(p, system, wanted):
        asked.append(system.id)
        return cores.ensure(p, system, wanted, Buildbot(), "x86_64")

    tab = GamesTab(FakeService(), emulation_root=str(paths.root))
    qtbot.addWidget(tab)
    notices = []
    tab.home.show_notice = lambda text, error=False: notices.append(text)
    tab.core_fetcher = fetch
    tab.reload_roms()
    qtbot.waitUntil(lambda: bool(notices), timeout=5000)
    assert asked == ["snes"] and notices == ["RetroArch cores downloaded for SNES"]
    assert (paths.cores / "snes9x_libretro.so").exists()


def test_no_downloads_without_retroarch(monkeypatch):
    from gamingcrypt import app

    monkeypatch.setattr(retroarch, "available", lambda which=None: False)
    config = copy.deepcopy(DEFAULTS)
    config["unlock"]["mount_point"] = "/tmp/nowhere"
    assert app.default_pages(config)["Games"].core_fetcher is None


@pytest.fixture
def window(qtbot, paths, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(retroarch, "available", lambda which=None: True)
    started = []
    monkeypatch.setattr(retroarch, "launch", lambda game, *a, **k: (started.append(game.name), (True, "Starting"))[1])
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(paths.root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.show_shell()
    w.resize(1280, 800)
    w.show()
    w._games, w._started = pages["Games"], started
    return w


def test_playing_without_a_core_downloads_it_first(qtbot, window, paths):
    bot = Buildbot(delay=0.1)
    window._games.core_fetcher = lambda p, s, wanted: cores.ensure(p, s, wanted, bot, "x86_64")
    mario = scan(paths, BY_ID["snes"])[0]
    ok, message = window.launch_rom(mario)
    assert ok and message == "Downloading the RetroArch core for SNES…"
    assert window.launch_overlay.isVisible() and "Downloading" in window.launch_overlay.phase.text()
    qtbot.waitUntil(lambda: window._started == ["Super Mario World"], timeout=5000)
    assert (paths.cores / "snes9x_libretro.so").exists()
    window.launch_rom(mario)  # now there: no second download
    assert len(bot.asked) == 1 and window._started == ["Super Mario World"] * 2


def test_failed_core_download_says_so(qtbot, window, paths):
    window._games.core_fetcher = lambda p, s, wanted: cores.ensure(p, s, wanted, Buildbot(offered=()), "x86_64")
    notices = []
    window.notify = lambda text, icon="ℹ": notices.append(text)
    window.launch_rom(scan(paths, BY_ID["snes"])[0])
    qtbot.waitUntil(lambda: bool(notices), timeout=5000)
    assert "Couldn't download a RetroArch core for SNES" in notices[0]
    assert not window.launch_overlay.isVisible() and window._started == []

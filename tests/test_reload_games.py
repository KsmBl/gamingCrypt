"""The Reload button on the Games page: games put onto the drive show up without a restart."""

from gamingcrypt.steam.models import SteamGame
from tests.fakes import FakeService
from tests.test_arrivals import drive


def test_reload_finds_new_games(qtbot, tmp_path):
    from gamingcrypt.ui.games_tab import GamesTab

    root = drive(tmp_path)
    service = FakeService(games=[SteamGame(1, "Burnout", installed=True)])
    tab = GamesTab(service, emulation_root=str(root / "Emulation"), windows_root=str(root / "Windows Games"))
    tab.covers = tab.windows_covers = None
    qtbot.addWidget(tab)
    tab.show()
    home = tab.home
    qtbot.waitUntil(lambda: len(home.installed) == 1 and "snes" not in tab.roms)
    assert home.reload_button.text() == "⟳  Reload"

    service.games.append(SteamGame(2, "Celeste", installed=True))
    snes = root / "Emulation" / "roms" / "snes"
    (snes / "Super Mario World (USA).sfc").write_bytes(b"x")
    (root / "Windows Games" / "Hades").mkdir()
    (root / "Windows Games" / "Hades" / "Hades.exe").write_bytes(b"MZ")
    home.reload_button.click()
    assert home.reloading and home.reload_button.text() == "⟳  Reloading…"
    home.reload_button.click()  # a second press while looking does nothing more

    qtbot.waitUntil(lambda: len(home.installed) == 2 and "snes" in tab.roms and len(tab.windows_games) == 1)
    assert not home.reloading and home.reload_button.text() == "⟳  Reload"
    assert {2, tab.roms["snes"][0].appid, tab.windows_games[0].appid} <= set(home.result_appids)

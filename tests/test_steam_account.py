import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.steam import library
from gamingcrypt.steam.service import SteamService
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.steam_page import SteamLibraryPage
from tests.fakes import FakeResponse, FakeService, FakeSession

LOGINUSERS = '''"users"
{
\t"76561198000000001"
\t{
\t\t"AccountName"\t\t"old"
\t\t"PersonaName"\t\t"Old Account"
\t\t"MostRecent"\t\t"0"
\t\t"Timestamp"\t\t"1800000000"
\t}
\t"76561198000000002"
\t{
\t\t"AccountName"\t\t"gamer"
\t\t"PersonaName"\t\t"Handheld Gamer"
\t\t"MostRecent"\t\t"1"
\t\t"Timestamp"\t\t"1700000000"
\t}
}
'''
OWNED = {"response": {"games": [{"appid": 292030, "name": "The Witcher 3", "playtime_forever": 5}]}}


def with_login(steam_root):
    (steam_root / "config").mkdir(exist_ok=True)
    (steam_root / "config" / "loginusers.vdf").write_text(LOGINUSERS)
    return steam_root


def test_logged_in_user_prefers_most_recent(steam_root):
    assert library.logged_in_user(with_login(steam_root)) == {"steam_id": "76561198000000002", "name": "Handheld Gamer"}


def test_logged_in_user_missing(steam_root):
    assert library.logged_in_user(steam_root) is None


def test_snap_steam_is_found(isolated_home):
    snap = isolated_home / "snap/steam/common/.local/share/Steam"
    (snap / "steamapps").mkdir(parents=True)
    assert library.find_steam_root() == snap.resolve()


def make_service(steam_root, tmp_path, key=""):
    from gamingcrypt.steam.webapi import SteamWebAPI

    cfg = {"root": str(steam_root), "api_key": key, "steam_id": ""}
    api = SteamWebAPI("", "", session=FakeSession({"GetOwnedGames": FakeResponse(OWNED)}))
    return SteamService(cfg, tmp_path / "cache", api=api), cfg


def test_only_api_key_needed_steam_id_is_detected(steam_root, tmp_path):
    svc, cfg = make_service(with_login(steam_root), tmp_path)
    assert not svc.full_library_available
    assert 292030 not in {g.appid for g in svc.load_library()}
    cfg["api_key"] = "0123456789ABCDEF0123456789ABCDEF"  # what the Settings page does
    assert svc.full_library_available
    assert 292030 in {g.appid for g in svc.load_library()}
    _, params = svc.api.session.requests[-1]
    assert params["steamid"] == "76561198000000002"


def test_diagnose_report(steam_root, tmp_path):
    svc, cfg = make_service(with_login(steam_root), tmp_path)
    report = "\n".join(svc.diagnose({"volume": "/v.vc", "mount_point": str(tmp_path / "nope")}))
    assert f"Steam: {steam_root.resolve()}" in report
    assert "2 manifests" in report or "3 manifests" in report
    assert "missing steamapps" in report  # the unmounted library from the fixture
    assert "installed games (without tools): 2" in report
    assert "Handheld Gamer (76561198000000002)" in report
    assert "NOT SET" in report and "NOT mounted" in report


def test_diagnose_without_steam(tmp_path, isolated_home):
    svc = SteamService({"root": ""}, tmp_path / "c")
    report = svc.diagnose()
    assert report[0] == "Steam: NOT FOUND - checked:"
    assert any("snap" in line for line in report)


def test_diagnose_cli(capsys, tmp_path):
    from gamingcrypt.app import main

    assert main(["--config", str(tmp_path / "none.json"), "--diagnose"]) == 0
    assert "Steam:" in capsys.readouterr().out


# --- UI hints ------------------------------------------------------------------

def page_for(qtbot, service):
    SteamLibraryPage.FETCH_DELAY_MS = 0
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.open_steam()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    return page


def test_hint_steam_not_found(qtbot):
    service = FakeService(games=[])
    service.root = None
    assert "wasn't found" in page_for(qtbot, service).status.text()


def test_hint_nothing_installed_without_key(qtbot):
    service = FakeService(games=[])
    service.full_library_available = False
    text = page_for(qtbot, service).status.text()
    assert "No installed games yet" in text and "Settings → Steam" in text


def test_settings_api_key(qtbot, steam_root):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["steam"]["root"] = str(with_login(steam_root))
    saved = []
    tab = SettingsTab(cfg, saved.append)
    qtbot.addWidget(tab)
    assert "2" in tab.account_label.text()
    assert "not set" in tab.api_key_label.text()
    tab.api_key_button.click()
    page = tab.currentWidget()
    page.edit.setText("not-a-key")
    page.keyboard.submitted.emit()
    assert "doesn't look like" in page.status.text() and saved == []
    page.edit.setText(" 0123456789abcdef0123456789ABCDEF ")
    page.keyboard.submitted.emit()
    assert tab.currentWidget() is tab.overview
    assert saved[-1]["steam"]["api_key"] == "0123456789abcdef0123456789ABCDEF"
    assert "whole library" in tab.api_key_label.text() and "saved" in tab.status.text()
    assert tab.api_key_button.text() == "Change Steam API key"


def test_settings_without_steam(qtbot, tmp_path):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["steam"]["root"] = str(tmp_path / "none")
    tab = SettingsTab(cfg, lambda c: None)
    qtbot.addWidget(tab)
    assert "not found" in tab.account_label.text()

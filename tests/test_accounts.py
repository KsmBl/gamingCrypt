import copy

from PySide6.QtWidgets import QLabel

from gamingcrypt.config import DEFAULTS
from gamingcrypt.steam import accounts, library, vdf
from gamingcrypt.steam.service import SteamService
from gamingcrypt.steam.webapi import SteamWebAPI
from gamingcrypt.ui.settings_tab import SettingsTab
from tests.fakes import FakeResponse, FakeSession

ALICE, BOB = str(accounts.STEAMID64_BASE + 1), str(accounts.STEAMID64_BASE + 2)


def write_users(root, recent=ALICE, bob_remembers="1"):
    (root / "config").mkdir(exist_ok=True)
    data = {"users": {
        ALICE: {"AccountName": "alice", "PersonaName": "Alice", "RememberPassword": "1",
                "MostRecent": "1" if recent == ALICE else "0", "Timestamp": "1"},
        BOB: {"AccountName": "bob", "PersonaName": "Bob", "RememberPassword": bob_remembers,
              "MostRecent": "1" if recent == BOB else "0", "Timestamp": "2"},
    }}
    (root / "config" / "loginusers.vdf").write_text(vdf.dumps(data))
    return root


class Client:
    def __init__(self):
        self.calls = []

    def shutdown(self):
        self.calls.append("shutdown")
        return True

    def start_silent(self):
        self.calls.append("start_silent")
        return True


def test_list_accounts(steam_root):
    found = accounts.list_accounts(write_users(steam_root))
    assert [(a.persona, a.most_recent) for a in found] == [("Alice", True), ("Bob", False)]
    assert found[0].account_id == 1
    assert accounts.list_accounts(None) == []


def test_switch_sets_auto_login_and_most_recent(steam_root, isolated_home):
    write_users(steam_root)
    (isolated_home / ".steam").mkdir()
    (isolated_home / ".steam" / "registry.vdf").write_text(vdf.dumps(
        {"Registry": {"HKCU": {"Software": {"Valve": {"Steam": {"AutoLoginUser": "alice", "language": "german"}}}}}}))
    bob = accounts.list_accounts(steam_root)[1]
    client = Client()
    running = iter([True, False])
    ok, msg = accounts.switch_account(steam_root, bob, client, isolated_home,
                                      is_running=lambda: next(running, False), sleep=lambda s: None)
    assert ok and msg == "Switched to Bob"
    assert client.calls == ["shutdown", "start_silent"]
    steam = vdf.load(isolated_home / ".steam" / "registry.vdf")["Registry"]["HKCU"]["Software"]["Valve"]["Steam"]
    assert steam["AutoLoginUser"] == "bob" and steam["RememberPassword"] == "1"
    assert steam["language"] == "german"  # other settings kept
    assert library.logged_in_user(steam_root)["steam_id"] == BOB
    users = vdf.load(steam_root / "config" / "loginusers.vdf")["users"]
    assert users[ALICE]["MostRecent"] == "0" and users[BOB]["AllowAutoLogin"] == "1"


def test_switch_without_remembered_password_warns(steam_root, isolated_home):
    write_users(steam_root, bob_remembers="0")
    bob = accounts.list_accounts(steam_root)[1]
    ok, msg = accounts.switch_account(steam_root, bob, Client(), isolated_home, is_running=lambda: False)
    assert ok and "password" in msg
    assert (isolated_home / ".steam" / "registry.vdf").exists()  # created if missing


def test_switch_failures(steam_root, isolated_home):
    write_users(steam_root)
    bob = accounts.list_accounts(steam_root)[1]
    assert not accounts.switch_account(None, bob, Client())[0]

    class Stubborn(Client):
        def shutdown(self):
            return False

    ok, msg = accounts.switch_account(steam_root, bob, Stubborn(), isolated_home, is_running=lambda: True)
    assert not ok and "close" in msg
    assert library.logged_in_user(steam_root)["steam_id"] == ALICE  # nothing changed
    nameless = accounts.Account("1", "", "X", False, True)
    assert not accounts.switch_account(steam_root, nameless, Client(), isolated_home, is_running=lambda: False)[0]


def test_flatpak_registry_path(tmp_path):
    root = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    root.mkdir(parents=True)
    assert accounts.registry_path(root, tmp_path) == tmp_path / ".var/app/com.valvesoftware.Steam/.steam/registry.vdf"
    assert accounts.registry_path(tmp_path / "Steam", tmp_path) == tmp_path / ".steam" / "registry.vdf"


# --- per-account data ----------------------------------------------------------------

def test_playtime_and_owned_cache_follow_the_active_account(steam_root, tmp_path, isolated_home):
    write_users(steam_root, recent=BOB)
    for account_id, minutes in ((1, 111), (2, 222)):
        cfg = steam_root / "userdata" / str(account_id) / "config"
        cfg.mkdir(parents=True)
        cfg.joinpath("localconfig.vdf").write_text(vdf.dumps({"UserLocalConfigStore": {"Software": {"Valve": {
            "Steam": {"apps": {"620": {"Playtime": str(minutes)}}}}}}}))
    owned = {"response": {"games": [{"appid": 400, "name": "Portal"}]}}
    svc = SteamService({"root": str(steam_root), "api_key": "k"}, tmp_path / "cache",
                       api=SteamWebAPI(session=FakeSession({"GetOwnedGames": FakeResponse(owned)})))
    games = {g.appid: g for g in svc.load_library()}
    assert games[620].playtime_minutes == 222  # Bob's, not Alice's or the fixture's
    assert (tmp_path / "cache" / f"owned_games_{BOB}.json").exists()
    assert svc.api.session.requests[-1][1]["steamid"] == BOB


def test_service_switch_follows_account(steam_root, tmp_path, isolated_home):
    write_users(steam_root)
    svc = SteamService({"root": str(steam_root), "steam_id": ALICE}, tmp_path / "c", client=Client())
    bob = svc.accounts()[1]
    svc_switch = svc.switch_account
    import gamingcrypt.steam.library_setup as ls
    original = ls.steam_running
    ls.steam_running = lambda: False
    try:
        ok, _ = svc_switch(bob)
    finally:
        ls.steam_running = original
    assert ok and svc.cfg["steam_id"] == "" and svc.api.steam_id == BOB


# --- Settings UI -------------------------------------------------------------------------

class FakeSteam:
    def __init__(self, root):
        self.root = root
        self.switched = []

    def switch_account(self, account):
        self.switched.append(account.persona)
        accounts.set_auto_login(self.root, account, self.root)
        return True, f"Switched to {account.persona}"


def test_settings_lists_accounts_and_switches(qtbot, steam_root):
    write_users(steam_root)
    cfg = copy.deepcopy(DEFAULTS)
    cfg["steam"]["root"] = str(steam_root)
    steam = FakeSteam(steam_root)
    tab = SettingsTab(cfg, lambda c: None, steam_service=steam)
    qtbot.addWidget(tab)
    labels = [l.text() for l in tab.findChildren(QLabel)]
    assert any("Alice" in t and "active" in t for t in labels)
    assert set(tab.account_buttons) == {BOB}  # no switch button for the active one
    tab.account_buttons[BOB].click()
    qtbot.waitUntil(lambda: "Switched to Bob" in tab.status.text())
    assert steam.switched == ["Bob"]
    qtbot.waitUntil(lambda: set(tab.account_buttons) == {ALICE})  # list refreshed: Bob is active now


def test_single_account_has_no_switcher(qtbot, steam_root):
    (steam_root / "config").mkdir(exist_ok=True)
    (steam_root / "config" / "loginusers.vdf").write_text(vdf.dumps({"users": {ALICE: {
        "AccountName": "alice", "PersonaName": "Alice", "MostRecent": "1"}}}))
    cfg = copy.deepcopy(DEFAULTS)
    cfg["steam"]["root"] = str(steam_root)
    tab = SettingsTab(cfg, lambda c: None, steam_service=FakeSteam(steam_root))
    qtbot.addWidget(tab)
    assert tab.account_label.text() == "Steam account: Alice" and tab.account_buttons == {}


def test_steam_page_shows_active_account(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.steam_page import SteamLibraryPage
    from tests.fakes import FakeService

    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = FakeService()
    service.account = lambda: {"steam_id": BOB, "name": "Bob"}
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.open_steam()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    assert page.count_label.text().startswith("Bob · 4 games")

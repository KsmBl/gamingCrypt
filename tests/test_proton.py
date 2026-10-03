import pytest

from gamingcrypt.steam import compat, vdf
from gamingcrypt.steam.compat import CompatTool


@pytest.mark.parametrize("folder,name", [
    ("Proton - Experimental", "proton_experimental"),
    ("Proton Hotfix", "proton_hotfix"),
    ("Proton 9.0", "proton_9"),
    ("Proton 9.0 (Beta)", "proton_9"),
    ("Proton 8.0", "proton_8"),
    ("Proton 6.3", "proton_63"),
    ("Proton 5.13", "proton_513"),
    ("Proton EasyAntiCheat Runtime", None),
    ("Portal 2", None),
])
def test_official_name(folder, name):
    assert compat.official_name(folder) == name


def install_proton(library, folder):
    path = library / "steamapps" / "common" / folder
    path.mkdir(parents=True)
    (path / "proton").write_text("#!/bin/sh")


def install_custom(root, folder, name, display):
    path = root / "compatibilitytools.d" / folder
    path.mkdir(parents=True)
    (path / "compatibilitytool.vdf").write_text(vdf.dumps({"compatibilitytools": {"compat_tools": {
        name: {"install_path": ".", "display_name": display, "from_oslist": "windows", "to_oslist": "linux"}}}}))


def test_available_tools(steam_root, isolated_home):
    install_proton(steam_root, "Proton 8.0")
    install_proton(steam_root, "Proton - Experimental")
    install_proton(steam_root.parent / "crypt" / "SteamLibrary", "Proton 9.0")  # on the encrypted drive
    (steam_root / "steamapps/common/Proton EasyAntiCheat Runtime").mkdir(parents=True)
    install_custom(steam_root, "GE-Proton9-20", "GE-Proton9-20", "GE-Proton9-20")
    install_custom(steam_root, "GE-Proton8-32", "GE-Proton8-32", "GE-Proton8-32")
    tools = compat.available(steam_root, isolated_home)
    assert [t.name for t in tools] == ["proton_experimental", "proton_9", "proton_8",
                                       "GE-Proton9-20", "GE-Proton8-32"]
    assert tools[1] == CompatTool("proton_9", "Proton 9.0")
    assert compat.available(None) == []


def test_read_and_write_choice_keeps_other_settings(steam_root):
    config = steam_root / "config" / "config.vdf"
    config.parent.mkdir(exist_ok=True)
    config.write_text(vdf.dumps({"InstallConfigStore": {"Software": {"Valve": {"Steam": {
        "AutoUpdateWindowEnabled": "0",
        "CompatToolMapping": {"0": {"name": "proton_9", "config": "", "priority": "75"}}}}}}}))
    assert compat.current(steam_root, 620) is None
    compat.write_choice(steam_root, 620, "GE-Proton9-20")
    assert compat.current(steam_root, 620) == "GE-Proton9-20"
    steam = vdf.load(config)["InstallConfigStore"]["Software"]["Valve"]["Steam"]
    assert steam["AutoUpdateWindowEnabled"] == "0"
    assert steam["CompatToolMapping"]["0"]["name"] == "proton_9"  # global default untouched
    compat.write_choice(steam_root, 620, None)  # back to default
    assert compat.current(steam_root, 620) is None


def test_write_choice_without_config_file(steam_root):
    compat.write_choice(steam_root, 1145360, "proton_experimental")
    assert compat.current(steam_root, 1145360) == "proton_experimental"


class Client:
    def __init__(self, shutdown_ok=True):
        self.calls = []
        self.shutdown_ok = shutdown_ok

    def shutdown(self):
        self.calls.append("shutdown")
        return self.shutdown_ok

    def start_silent(self):
        self.calls.append("start_silent")
        return True


def test_set_tool_closes_and_restarts_steam(steam_root):
    client = Client()
    states = iter([True, True, False])
    ok, msg = compat.set_tool(steam_root, 620, "proton_8", client, is_running=lambda: next(states, False),
                              sleep=lambda s: None)
    assert ok and "proton_8" in msg and client.calls == ["shutdown", "start_silent"]
    assert compat.current(steam_root, 620) == "proton_8"
    client = Client()
    assert compat.set_tool(steam_root, 620, None, client, is_running=lambda: False)[0]
    assert client.calls == []  # Steam wasn't running -> not started either


def test_set_tool_failures(steam_root):
    assert not compat.set_tool(None, 1, "x", Client())[0]
    ok, msg = compat.set_tool(steam_root, 620, "proton_8", Client(shutdown_ok=False), is_running=lambda: True)
    assert not ok and "close" in msg and compat.current(steam_root, 620) is None


# --- game page -----------------------------------------------------------------------

def proton_page(qtbot, current=None, result=(True, "Compatibility tool: GE-Proton9-20")):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    service = FakeService()
    service.compat_tools = lambda: [CompatTool("proton_experimental", "Proton - Experimental"),
                                    CompatTool("GE-Proton9-20", "GE-Proton9-20")]
    service.compat_tool = lambda appid: current
    service.chosen = []
    service.set_compat_tool = lambda appid, name: service.chosen.append((appid, name)) or result
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.games.update({g.appid: g for g in service.games})
    tab.open_game(620)
    page = tab.currentWidget()
    page.options_button.click()
    return page, service


def test_proton_choices_in_options(qtbot):
    page, service = proton_page(qtbot, current="GE-Proton9-20")
    combo = page.proton_combo
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "Default (Steam decides)", "Proton - Experimental", "GE-Proton9-20"]
    assert combo.currentText() == "GE-Proton9-20"
    assert service.chosen == []  # opening Options changes nothing


def test_choose_proton(qtbot):
    page, service = proton_page(qtbot)
    page.proton_combo.setCurrentIndex(page.proton_combo.findData("GE-Proton9-20"))
    assert "Steam restarts" in page.status.text() and not page.proton_combo.isEnabled()
    qtbot.waitUntil(lambda: "GE-Proton9-20" in page.status.text() and page.proton_combo.isEnabled())
    assert service.chosen == [(620, "GE-Proton9-20")]
    page.proton_combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: service.chosen[-1] == (620, None))  # back to Steam's default


def test_choose_proton_failure_shows_real_setting(qtbot):
    page, service = proton_page(qtbot, result=(False, "Steam didn't close - close it and try again"))
    page.proton_combo.setCurrentIndex(1)
    qtbot.waitUntil(lambda: "didn't close" in page.status.text())
    assert page.proton_combo.currentIndex() == 0  # reset to what's actually set


def test_unknown_current_tool_is_still_shown(qtbot):
    page, _ = proton_page(qtbot, current="proton_7")
    assert page.proton_combo.currentText() == "proton_7 (not installed)"

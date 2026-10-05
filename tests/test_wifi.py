"""Settings -> Network -> Wi-Fi (nmcli)."""

import copy
import subprocess

import pytest

from gamingcrypt.system.wifi import Network, Wifi, split_terse

LIST = """ :[>SynthelicZ<]:72:WPA1 WPA2
*:Home\\:5G:66:WPA2
 :Home\\:5G:40:WPA2
 :Cafe:55:
 ::30:WPA2
"""
SAVED = "Home:5G:802-11-wireless\nWired connection 1:802-3-ethernet\nOld:802-11-wireless\n".replace(
    "Home:5G", "Home\\:5G")


class Nmcli:
    def __init__(self, enabled=True, fail=None):
        self.calls, self.inputs, self.enabled, self.fail = [], [], enabled, fail or {}

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        self.inputs.append(kw.get("input"))
        joined = " ".join(cmd)
        for key, error in self.fail.items():
            if key in joined:
                return subprocess.CompletedProcess(cmd, 4, "", f"Error: {error}")
        if cmd[1:] == ["radio", "wifi"]:
            return subprocess.CompletedProcess(cmd, 0, "enabled\n" if self.enabled else "disabled\n", "")
        if "wifi" in cmd and "list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, LIST, "")
        if cmd[1:4] == ["-t", "-f", "NAME,TYPE"]:
            return subprocess.CompletedProcess(cmd, 0, SAVED, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def wifi(**kw):
    return Wifi(Nmcli(**kw), which=lambda tool: "/usr/bin/nmcli")


def test_terse_fields_with_colons():
    assert split_terse("*:Home\\:5G:66:WPA2") == ["*", "Home:5G", "66", "WPA2"]


def test_networks_merged_and_sorted():
    w = wifi()
    nets = w.networks()
    assert [n.ssid for n in nets] == ["Home:5G", "[>SynthelicZ<]", "Cafe"]  # hidden SSID dropped
    home = nets[0]
    assert home.in_use and home.saved and home.signal == 66 and home.secured  # the in-use one of two APs
    assert not nets[2].secured and nets[2].bars == "▂▄▆"
    assert w.saved() == {"Home:5G", "Old"}
    w.networks(rescan=True)
    assert w.runner.calls[-2][-2:] == ["--rescan", "yes"]


def test_connect_new_network_password_via_stdin():
    w = wifi()
    ok, message = w.connect(Network("[>SynthelicZ<]", 72, True), "secret-pass")
    cmd = w.runner.calls[-1]
    assert ok and message == "Connected to [>SynthelicZ<]"
    assert cmd == ["nmcli", "--ask", "device", "wifi", "connect", "[>SynthelicZ<]"]
    assert "secret-pass" not in " ".join(cmd) and w.runner.inputs[-1] == "secret-pass\n"  # not in ps


def test_connect_saved_open_and_errors():
    w = wifi()
    w.connect(Network("Home:5G", 66, True, saved=True))
    assert w.runner.calls[-1] == ["nmcli", "connection", "up", "id", "Home:5G"]
    w.connect(Network("Cafe", 55, False))
    assert w.runner.calls[-1] == ["nmcli", "device", "wifi", "connect", "Cafe"]
    bad = wifi(fail={"connect": "Secrets were required, but not provided."})
    assert bad.connect(Network("X", 50, True), "wrongpass") == (False, "Secrets were required, but not provided.")
    assert w.forget("Old") == (True, "Forgot Old") and w.runner.calls[-1][-3:] == ["delete", "id", "Old"]
    assert w.set_enabled(False)[0] and w.runner.calls[-1] == ["nmcli", "radio", "wifi", "off"]


def test_missing_nmcli():
    assert not Wifi(Nmcli(), which=lambda tool: None).available


# --- UI ---------------------------------------------------------------------------------

@pytest.fixture
def tab(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    t = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, wifi=wifi())
    qtbot.addWidget(t)
    t.show()
    t.sub_buttons["Network"].click()
    qtbot.waitUntil(lambda: len(t.wifi_section.rows) == 3)
    return t


def test_network_list(qtbot, tab):
    section = tab.wifi_section
    assert section.toggle.isChecked() and section.toggle.text() == "On"
    home = section.rows["Home:5G"].findChildren(type(section.toggle))
    assert "Connected" in home[0].text() and home[1].text() == "Forget"
    home[1].click()  # forget
    qtbot.waitUntil(lambda: ["nmcli", "connection", "delete", "id", "Home:5G"] in section.wifi.runner.calls)
    qtbot.waitUntil(lambda: "Forgot Home:5G" in section.status.text())


def test_new_secured_network_asks_for_the_password(qtbot, tab):
    section = tab.wifi_section
    section.rows["[>SynthelicZ<]"].findChildren(type(section.toggle))[0].click()
    page = section.password_page
    assert tab.currentWidget() is page and page.edit.echoMode() == page.edit.EchoMode.Password
    page.edit.setText("short")
    page.connect_button.click()
    assert "at least 8" in page.status.text()
    page.edit.setText("long enough")
    page.connect_button.click()
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview)
    assert "Connected to [>SynthelicZ<]" in section.status.text()
    assert section.wifi.runner.inputs[section.wifi.runner.calls.index(
        ["nmcli", "--ask", "device", "wifi", "connect", "[>SynthelicZ<]"])] == "long enough\n"


def test_password_page_back_button(qtbot, tab):
    section = tab.wifi_section
    section.choose(Network("[>SynthelicZ<]", 72, True))
    assert tab.gamepad_back() and tab.currentWidget() is tab.overview and section.password_page is None


def test_wifi_off(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    t = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, wifi=wifi(enabled=False))
    qtbot.addWidget(t)
    t.sub_buttons["Network"].click()
    qtbot.waitUntil(lambda: t.wifi_section.status.text() == "Wi-Fi is off")
    assert not t.wifi_section.toggle.isChecked() and t.wifi_section.rows == {}

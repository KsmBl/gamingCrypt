"""Gaming mode: every window GamingCrypt opens needs its gamescope app id - otherwise
gamescope's Steam mode never shows it. Drop-down lists open inside the window instead."""

import copy

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from gamingcrypt.config import DEFAULTS
from gamingcrypt.session import mode
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.combo import open_list
from gamingcrypt.ui.gamescope_windows import WindowAppIds
from tests.test_quick_menu import Audio, Brightness
from tests.test_system_settings import FakeAudio


@pytest.fixture
def tagged(qtbot):
    ids = []
    tagger = WindowAppIds(set_appid=lambda wid: ids.append(wid) or True).install(QApplication.instance())
    yield ids
    QApplication.instance().removeEventFilter(tagger)


def opened_list_is_tagged(qtbot, combo: QComboBox, ids: list) -> None:
    """The open list is part of the window (gaming mode or not): no window of its own that
    gamescope could leave out or put behind GamingCrypt's."""
    before = list(ids)
    combo.showPopup()
    try:
        listing = open_list()
        qtbot.waitUntil(lambda: listing is not None and listing.isVisible())
        assert not listing.isWindow() and listing.window() is combo.window()
        assert QApplication.activePopupWidget() is None and ids == before  # (nothing to tag)
    finally:
        combo.hidePopup()
    assert open_list() is None


def test_every_shown_window_gets_the_app_id_once(qtbot, tagged):
    w = QWidget()
    qtbot.addWidget(w)
    w.show()
    assert tagged == [int(w.winId())]
    w.hide()
    w.show()
    assert tagged == [int(w.winId())]  # stays on the X window - no second xprop
    child = QWidget(w)
    child.show()
    assert len(tagged) == 1  # not a window: nothing to tag


def test_failed_tag_is_retried(qtbot):
    results = [False, True]
    calls = []
    tagger = WindowAppIds(set_appid=lambda wid: calls.append(wid) or results.pop(0))
    w = QWidget()
    qtbot.addWidget(w)
    tagger.tag(w)
    tagger.tag(w)
    assert len(calls) == 2 and tagger.tagged == {int(w.winId())}


def test_quick_menu_lists_open_in_gaming_mode(qtbot, tagged):
    from gamingcrypt.ui.quick_menu import QuickMenu

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1280, 800)
    host.show()
    menu = QuickMenu(host, SystemControls(audio=Audio(), brightness=Brightness()),
                     refresh_get=lambda: 0, refresh_set=lambda hz: True)
    menu.open_menu(620, "Portal 2")
    for combo in (menu.output, menu.input, menu.refresh):
        opened_list_is_tagged(qtbot, combo, tagged)


def test_settings_lists_open_in_gaming_mode(qtbot, tagged, monkeypatch):
    from gamingcrypt.ui.settings_tab import SettingsTab

    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(mode, "panel_size", lambda *a: (1280, 800))
    monkeypatch.setattr(mode, "refresh_rates_available", lambda env=None: True)
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, system=SystemControls(audio=FakeAudio()),
                      restart_gaming=lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    d, a = tab.display_section, tab.audio_section
    for combo in (d.gs_resolution, d.gs_refresh, a.combos["output"], a.combos["input"]):
        opened_list_is_tagged(qtbot, combo, tagged)


def test_only_in_gaming_mode(monkeypatch):
    from gamingcrypt.app import tag_windows_in_gaming_mode

    app = QApplication.instance()
    assert tag_windows_in_gaming_mode(app) is None
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    tagger = tag_windows_in_gaming_mode(app)
    try:
        assert isinstance(tagger, WindowAppIds)
    finally:
        app.removeEventFilter(tagger)
        tagger.deleteLater()


def test_real_xprop_command():
    import subprocess

    from gamingcrypt.system import gamescope_ctl as gs

    seen = []
    gs.set_window_appid(0x400007, runner=lambda cmd, **kw: seen.append(cmd) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    assert seen == [["xprop", "-id", str(0x400007), "-f", "STEAM_GAME", "32c", "-set", "STEAM_GAME",
                     str(gs.LAUNCHER_APPID)]]

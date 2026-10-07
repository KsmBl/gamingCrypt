"""Game page Options: a pop-up over the page - its boxes line up, everything on screen."""

from gamingcrypt.steam.compat import CompatTool
from gamingcrypt.system import power
from gamingcrypt.system.power import PowerLimit
from gamingcrypt.ui import theme
from gamingcrypt.ui.games_tab import GamesTab
from tests.fakes import FakeService


def test_options_line_up_and_scroll_into_view(qtbot, monkeypatch):
    monkeypatch.setattr(power, "read_limit", lambda *a, **k: PowerLimit(15, 5, 28, "x"))
    service = FakeService()
    service.compat_tools = lambda: [CompatTool("proton_experimental", "Proton - Experimental")]
    service.compat_tool = lambda appid: None
    tab = GamesTab(service)
    tab.setStyleSheet(theme.STYLESHEET)
    qtbot.addWidget(tab)
    tab.resize(1280, 640)  # what's left of 800 px with the top and hint bars
    tab.show()
    qtbot.waitExposed(tab)
    tab.games.update({g.appid: g for g in service.games})
    tab.open_game(620)
    page = tab.currentWidget()
    page.options_button.click()
    popup = page.options_popup
    assert popup.isVisible() and popup.geometry() == page.rect()  # over the whole page
    xs = {combo.mapTo(page, combo.rect().topLeft()).x()
          for combo in (page.proton_combo, page.power_combo, page.fps_combo)}
    assert len(xs) == 1  # one caption column: all boxes start at the same place
    view = popup.scroll.viewport()
    bottom = page.uninstall_button.mapTo(view, page.uninstall_button.rect().bottomLeft()).y()
    assert bottom <= view.height()  # Uninstall on screen without scrolling (640 px high)


def test_options_popup_closes_with_b_close_and_a_tap_beside(qtbot):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    service = FakeService()
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.resize(1280, 720)
    tab.show()
    tab.games.update({g.appid: g for g in service.games})
    tab.open_game(620)
    page = tab.currentWidget()
    page.options_button.click()
    popup = page.options_popup
    assert page.options_button.isChecked() and popup.title.text() == "Options · Portal 2"
    assert popup.isAncestorOf(tab.window().focusWidget())  # the controller starts inside
    assert popup.gamepad_back() and not popup.isVisible() and not page.options_button.isChecked()
    assert tab.currentWidget() is page  # B closed the options, not the page
    page.options_button.click()
    popup.close_button.click()
    assert not popup.isVisible() and not page.options_button.isChecked()
    page.options_button.click()
    QTest.mouseClick(popup, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))  # on the dimmed page
    assert not popup.isVisible()

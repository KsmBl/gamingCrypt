"""Game page Options: boxes line up, and on a short screen the page scrolls to them."""

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
    bar = page.scroll.verticalScrollBar()
    assert bar.value() == 0
    page.options_button.click()
    qtbot.waitUntil(lambda: bar.value() > 0)  # scrolled to the opened panel
    xs = {combo.mapTo(page, combo.rect().topLeft()).x()
          for combo in (page.proton_combo, page.power_combo, page.fps_combo)}
    assert len(xs) == 1  # one caption column: all boxes start at the same place
    panel_bottom = page.options_panel.mapTo(page.scroll.widget(), page.options_panel.rect().bottomLeft()).y()
    assert panel_bottom <= bar.value() + page.scroll.viewport().height() + 1  # Uninstall on screen

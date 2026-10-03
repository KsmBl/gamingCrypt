from gamingcrypt.ui.game_detail import GameDetailPage
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.steam_page import SteamLibraryPage
from tests.fakes import FakeService


def make_tab(qtbot):
    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.installed != [])
    return tab


def open_from_library(qtbot, tab, appid):
    SteamLibraryPage.FETCH_DELAY_MS = 0
    tab.open_steam()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    page.cards[appid].tapped.emit()
    detail = tab.currentWidget()
    assert isinstance(detail, GameDetailPage)
    return detail


def test_installed_game_shows_play_and_starts_it(qtbot):
    tab = make_tab(qtbot)
    tab.open_game(620)
    page = tab.currentWidget()
    assert isinstance(page, GameDetailPage)
    assert "Play" in page.main_button.text()
    facts = page.facts.text()
    assert "Installed" in facts and "11.2 GB" in facts and "1.95 €" in facts and "18 Apr 2011" in facts
    page.main_button.click()
    assert tab.service.client.actions == [("play", 620)]
    assert "Starting Portal 2" in page.status.text()


def test_not_installed_game_offers_download(qtbot):
    tab = make_tab(qtbot)
    page = open_from_library(qtbot, tab, 292030)
    assert "Download" in page.main_button.text()
    assert "Not installed" in page.facts.text()
    page.main_button.click()
    assert tab.service.client.actions == [("install", 292030)]
    page.options_button.click()
    assert page.uninstall_button.isHidden() and not page.no_options.isHidden()


def test_uninstall_requires_two_taps(qtbot):
    tab = make_tab(qtbot)
    tab.open_game(1145360)
    page = tab.currentWidget()
    assert page.options_panel.isHidden()
    page.options_button.click()
    assert not page.options_panel.isHidden()
    page.uninstall_button.click()
    assert tab.service.client.actions == []
    assert "again" in page.uninstall_button.text()
    page.uninstall_button.click()
    assert tab.service.client.actions == [("uninstall", 1145360)]
    assert "Confirm" in page.status.text()


def test_closing_options_disarms_uninstall(qtbot):
    tab = make_tab(qtbot)
    tab.open_game(620)
    page = tab.currentWidget()
    page.options_button.click()
    page.uninstall_button.click()
    page.options_button.click()
    assert page.uninstall_button.text() == "🗑 Uninstall"
    page.options_button.click()
    page.uninstall_button.click()
    assert tab.service.client.actions == []


def test_update_pending_shown(qtbot):
    tab = make_tab(qtbot)
    tab.games[620].update_pending = True
    tab.open_game(620)
    assert "update pending" in tab.currentWidget().facts.text()


def test_steam_unreachable(qtbot):
    tab = make_tab(qtbot)
    tab.service.client.play = lambda appid: False
    tab.open_game(620)
    page = tab.currentWidget()
    page.main_button.click()
    assert "Could not reach Steam" in page.status.text()


def test_back_from_detail_to_library(qtbot):
    tab = make_tab(qtbot)
    page = open_from_library(qtbot, tab, 620)
    tab.back()
    assert isinstance(tab.currentWidget(), SteamLibraryPage)


def test_open_unknown_game_is_ignored(qtbot):
    tab = make_tab(qtbot)
    tab.open_game(123456)
    assert tab.currentWidget() is tab.home


def test_home_card_opens_detail(qtbot):
    tab = make_tab(qtbot)
    card = tab.home.grid.itemAt(0).widget()
    card.tapped.emit()
    assert isinstance(tab.currentWidget(), GameDetailPage)


# --- background download (no Steam dialog) ---------------------------------------

from gamingcrypt.steam.installer import InstallProgress, InstallResult  # noqa: E402
from gamingcrypt.ui import game_detail  # noqa: E402
from tests.fakes import SilentInstallService  # noqa: E402


def silent_tab(qtbot, **kw):
    game_detail.PROGRESS_INTERVAL_MS = 10
    tab = GamesTab(SilentInstallService(**kw))
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: tab.home.installed != [])
    tab.games.update({g.appid: g for g in tab.service.games})
    return tab


def test_download_without_dialog_shows_progress_until_installed(qtbot):
    steps = [InstallProgress("queued"), InstallProgress("downloading", 512 * 1024**2, 2 * 1024**3),
             InstallProgress("installed", 2 * 1024**3, 2 * 1024**3)]
    tab = silent_tab(qtbot, progress_steps=steps)
    tab.open_game(292030)
    page = tab.currentWidget()
    seen = []
    page.main_button.click()
    assert not page.main_button.isEnabled() and page.main_button.text() == "Downloading…"
    qtbot.waitUntil(lambda: (seen.append(page.status.text()) or "installed ✓" in page.status.text()), timeout=3000)
    assert tab.service.installs == [292030]
    assert tab.service.client.actions == []  # Steam's install dialog was never opened
    assert any("Downloading 25%" in text for text in seen)
    assert "Play" in page.main_button.text() and page.main_button.isEnabled()
    assert page.game.installed


def test_download_failure_is_shown(qtbot):
    tab = silent_tab(qtbot, install_result=InstallResult(False, "Steam didn't close - close it and try again"))
    tab.open_game(292030)
    page = tab.currentWidget()
    page.main_button.click()
    qtbot.waitUntil(lambda: "didn't close" in page.status.text())
    assert "Download" in page.main_button.text() and page.main_button.isEnabled()


def test_download_cancelled_in_steam(qtbot):
    tab = silent_tab(qtbot, progress_steps=[InstallProgress("queued"), InstallProgress("missing")])
    tab.open_game(292030)
    page = tab.currentWidget()
    page.main_button.click()
    qtbot.waitUntil(lambda: "cancelled in Steam" in page.status.text(), timeout=3000)
    assert page.main_button.isEnabled()


def test_reopening_page_resumes_watching(qtbot):
    tab = silent_tab(qtbot, progress_steps=[InstallProgress("downloading", 1, 4)])
    tab.service.installs.append(292030)  # queued earlier
    tab.open_game(292030)
    page = tab.currentWidget()
    assert page.downloading
    qtbot.waitUntil(lambda: "Downloading 25%" in page.status.text())

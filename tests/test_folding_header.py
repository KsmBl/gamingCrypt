import pytest
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import FoldingHeader


@pytest.fixture
def page(qtbot, monkeypatch):
    monkeypatch.setattr(FoldingHeader, "DURATION_MS", 10)
    monkeypatch.setattr(FoldingHeader, "SETTLE_MS", 0)
    root = QWidget()
    layout = QVBoxLayout(root)
    header = QLabel("Header")
    header.setFixedWidth(300)
    layout.addWidget(header)
    scroll = QScrollArea()
    content = QWidget()
    content.setMinimumHeight(5000)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    qtbot.addWidget(root)
    root.resize(400, 600)
    root.show()
    qtbot.waitExposed(root)
    return root, header, scroll, FoldingHeader(scroll, header)


def test_folds_when_scrolling_down_and_back_when_scrolling_up(qtbot, page):
    root, header, scroll, fold = page
    bar = scroll.verticalScrollBar()
    bar.setValue(30)
    assert not fold.folded  # tiny scroll near the top
    bar.setValue(400)
    assert fold.folded
    qtbot.waitUntil(header.isHidden)  # hidden -> no controller focus on it either
    bar.setValue(395)
    assert fold.folded  # a few pixels of jitter don't unfold it
    bar.setValue(350)
    assert not fold.folded
    qtbot.waitUntil(lambda: header.isVisible() and header.maximumHeight() > 1000)


def test_unfolds_at_the_top(qtbot, page):
    root, header, scroll, fold = page
    bar = scroll.verticalScrollBar()
    bar.setValue(800)
    bar.setValue(0)
    assert not fold.folded


def test_scroll_jump_from_folding_itself_is_ignored(qtbot, page, monkeypatch):
    root, header, scroll, fold = page
    monkeypatch.setattr(FoldingHeader, "SETTLE_MS", 10_000)
    bar = scroll.verticalScrollBar()
    bar.setValue(400)
    assert fold.folded
    bar.setValue(300)  # the viewport grew -> value jumps; must not unfold right away
    assert fold.folded


def test_steam_library_header_folds(qtbot, monkeypatch):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.steam_page import SteamLibraryPage
    from tests.fakes import FakeService

    monkeypatch.setattr(FoldingHeader, "DURATION_MS", 10)
    monkeypatch.setattr(FoldingHeader, "SETTLE_MS", 0)
    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = FakeService(games=[SteamGame(i, f"Game {i:03}") for i in range(1, 60)])
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    tab.open_steam()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    qtbot.waitUntil(lambda: page.scroll.verticalScrollBar().maximum() > 500)
    page.scroll.verticalScrollBar().setValue(600)
    qtbot.waitUntil(page.header.isHidden)  # title + sort bar folded away
    page.scroll.verticalScrollBar().setValue(400)
    qtbot.waitUntil(page.header.isVisible)


def test_every_list_page_has_a_folding_header(qtbot):
    from gamingcrypt.ui.downloads_tab import DownloadsTab
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.store_page import StorePage
    from tests.fakes import FakeService

    service = FakeService()
    service.downloads = lambda: []
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    downloads = DownloadsTab(service)
    qtbot.addWidget(downloads)
    for page in (tab.home, StorePage(tab), downloads):
        assert isinstance(page.folding, FoldingHeader) and page.folding.header is page.header


def test_short_list_does_not_fold_away_for_good(qtbot, page):
    """Movies tab, few movies: folding made everything fit - no scroll bar left to bring it back."""
    root, header, scroll, fold = page
    header.setFixedHeight(150)
    content = scroll.widget()
    content.setMinimumHeight(10)
    content.resize(content.width(), scroll.viewport().height() + 100)  # scrolls only with the header there
    bar = scroll.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() == 100)
    bar.setValue(bar.maximum())
    assert not fold.folded and header.isVisible()


def test_unfolds_when_the_list_gets_short_while_folded(qtbot, page):
    root, header, scroll, fold = page
    bar = scroll.verticalScrollBar()
    bar.setValue(400)
    qtbot.waitUntil(header.isHidden)
    scroll.widget().setMinimumHeight(10)  # e.g. a search left one card
    scroll.widget().resize(scroll.widget().width(), 10)
    qtbot.waitUntil(lambda: not fold.folded and header.isVisible())

"""Emulated games' cards match Steam's; library cards fill their rows evenly."""

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QWidget

from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.widgets import FlowLayout


def test_rom_card_is_as_big_as_a_steam_card(qtbot, tmp_path):
    from gamingcrypt.ui.emulation_pages import RomCard
    from gamingcrypt.ui.game_widgets import GameCard

    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Super Mario World (USA).sfc").write_text("x")
    rom = RomCard(scan(paths, BY_ID["snes"])[0])
    steam = GameCard(SteamGame(620, "Portal 2", installed=True))
    for card in (rom, steam):
        qtbot.addWidget(card)
        card.show()
    assert rom.width() == steam.width() and rom.cover.size() == steam.cover.size()
    assert rom.sizeHint().height() == steam.sizeHint().height()


def stretched(qtbot, count, width, min_w=320, spacing=20):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, spacing=spacing, stretch=True)
    flow.setContentsMargins(0, 0, 0, 0)
    cards = []
    for _ in range(count):
        card = QWidget()
        card.setMinimumWidth(min_w)
        card.setFixedHeight(180)
        flow.addWidget(card)
        cards.append(card)
    flow.setGeometry(QRect(0, 0, width, flow.heightForWidth(width)))
    flow.host = host  # keep it alive
    return flow, cards


def test_library_cards_fill_the_row(qtbot):
    flow, cards = stretched(qtbot, 7, 1220)  # 3 fit (3 * 320 + 2 * 20 = 1000)
    widths = {c.geometry().width() for c in cards}
    assert max(widths) - min(widths) <= 2 and min(widths) >= 320
    assert cards[0].geometry().left() == 0 and cards[2].geometry().right() == 1219  # no gap on the right
    assert cards[3].geometry().left() == 0 and cards[3].geometry().top() == 200
    assert flow.heightForWidth(1220) == 3 * 180 + 2 * 20


def test_few_cards_keep_their_size(qtbot):
    _flow, cards = stretched(qtbot, 2, 1220)
    assert all(320 <= c.geometry().width() < 420 for c in cards) and cards[0].geometry().left() == 0


def test_home_library_cards_use_the_whole_width(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService())
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    home = tab.home
    qtbot.waitUntil(lambda: home.steam_card.width() > 0)
    cards = [home.favorites_card, home.steam_card, home.recent_card]
    rights = max(c.geometry().right() for c in cards)
    area = home.sources.contentsRect()
    margins = home.sources_row.contentsMargins()
    assert rights == area.right() - margins.right()  # the same gap as on the left
    assert cards[0].geometry().left() == area.left() + margins.left()
    assert len({c.width() for c in cards}) <= 2 and min(c.width() for c in cards) > 320

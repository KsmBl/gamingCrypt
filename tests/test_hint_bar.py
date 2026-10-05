"""Button hints at the bottom (gaming mode)."""

from PySide6.QtWidgets import QComboBox, QLineEdit, QSlider

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.game_widgets import GameCard
from gamingcrypt.ui.hint_bar import hints_for
from gamingcrypt.ui.shell import Shell
from gamingcrypt.ui.widgets import big_button
from tests.fakes import FakeService


def test_hints_follow_the_kind_of_control(qtbot):
    card = GameCard(SteamGame(620, "Portal 2", installed=True), FakeService())
    qtbot.addWidget(card)
    tab = big_button("Games", "tab")
    qtbot.addWidget(tab)
    assert hints_for(QLineEdit()).startswith("Ⓐ  Keyboard")
    assert hints_for(QSlider()).startswith("◀ ▶  Adjust")
    assert hints_for(QComboBox()).startswith("Ⓐ  Choose")
    assert hints_for(card).startswith("Ⓐ  Open game")
    assert hints_for(tab).startswith("Ⓐ  Open     ◀ ▶  Tabs")
    assert hints_for(None).startswith("Ⓐ  Select") and "⊞  Quick menu" in hints_for(None)


def test_bar_updates_with_the_highlight(qtbot):
    shell = Shell(show_hints=True)
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitExposed(shell)
    assert shell.hint_bar.isVisible()
    shell.tab_buttons["Games"].setFocus()
    qtbot.waitUntil(lambda: shell.hint_bar.text().startswith("Ⓐ  Open     ◀ ▶  Tabs"))
    shell.exit_button.setFocus()
    qtbot.waitUntil(lambda: shell.hint_bar.text().startswith("Ⓐ  Select"))


def test_only_in_gaming_mode(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.show_shell()
    assert not window.shell.hint_bar.isVisibleTo(window.shell)  # desktop: mouse / touch
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    from gamingcrypt.system import gamescope_ctl

    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda wid: True)
    window.show_shell()
    assert window.shell.hint_bar.isVisibleTo(window.shell)

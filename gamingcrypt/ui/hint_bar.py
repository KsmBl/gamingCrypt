"""Button hints at the bottom, like on a console: what A / B / the bumpers do right now."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QSlider, QWidget

COMMON = "LB / RB  Tabs     ⊞  Quick menu"
PAGES = "LT / RT  Page"  # in long lists (navigator.page)


def card_hint(widget: QWidget | None) -> str | None:
    """What A and X do on a card: open it, and its quick action."""
    from gamingcrypt.ui.emulation_pages import RomCard
    from gamingcrypt.ui.game_widgets import GameCard
    from gamingcrypt.ui.movies_tab import MovieCard
    from gamingcrypt.ui.shows_tab import EpisodeRow, ShowCard
    from gamingcrypt.ui.wine_pages import WindowsCard

    if isinstance(widget, (GameCard, RomCard, WindowsCard)):
        return "Ⓐ  Open game     Ⓧ  Favorite     Ⓑ  Back"
    if isinstance(widget, MovieCard):
        return "Ⓐ  Open movie     Ⓧ  Watched     Ⓑ  Back"
    if isinstance(widget, ShowCard):
        return "Ⓐ  Open show     Ⓧ  Watched     Ⓑ  Back"
    if isinstance(widget, EpisodeRow):
        return "Ⓐ  Play     Ⓧ  Watched     Ⓑ  Back"
    return None


def hints_for(widget: QWidget | None) -> str:
    card = card_hint(widget)
    if card is not None:
        first = card
    elif isinstance(widget, QLineEdit):
        first = "Ⓐ  Keyboard     Ⓑ  Back"
    elif isinstance(widget, QSlider):
        first = "◀ ▶  Adjust     Ⓑ  Back"
    elif isinstance(widget, QComboBox):
        first = "Ⓐ  Choose     Ⓑ  Back"
    elif isinstance(widget, QAbstractButton) and widget.objectName() == "tab":
        first = "Ⓐ  Open     ◀ ▶  Tabs"
    else:
        first = "Ⓐ  Select     Ⓑ  Back"
    if has_picture(widget):
        first += "     Ⓨ  Picture"
    if in_list(widget):
        first += f"     {PAGES}"
    return f"{first}     {COMMON}"


def in_list(widget: QWidget | None) -> bool:
    """A card in a grid or list that scrolls: the triggers page through it."""
    from PySide6.QtWidgets import QScrollArea

    from gamingcrypt.ui.cover_picker import ChoiceCard
    from gamingcrypt.ui.game_widgets import Tappable

    if not isinstance(widget, (Tappable, ChoiceCard)) and card_hint(widget) is None:
        return False
    node = widget.parentWidget()
    while node is not None:
        if isinstance(node, QScrollArea):
            return node.verticalScrollBar().maximum() > 0
        node = node.parentWidget()
    return False


def has_picture(widget: QWidget | None) -> bool:
    """A game's, movie's or show's card or page: Y chooses another picture."""
    if widget is None:
        return False
    from gamingcrypt.ui.cover_picker import CoverPicker, game_of, media_of

    node = widget
    while node is not None:
        if isinstance(node, CoverPicker):
            return False
        node = node.parentWidget()
    return game_of(widget, None) is not None or media_of(widget, None) is not None


class HintBar(QLabel):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("hintBar")
        self.setText(hints_for(None))
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._focus_changed)

    def _focus_changed(self, _old, new) -> None:
        if new is not None and self.window() is new.window():
            self.setText(hints_for(new))

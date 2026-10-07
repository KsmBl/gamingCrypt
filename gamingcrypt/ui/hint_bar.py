"""Button hints at the bottom, like on a console: what A / B / the bumpers do right now."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QSlider, QWidget

COMMON = "LB / RB  Tabs     ⊞  Quick menu"


def hints_for(widget: QWidget | None) -> str:
    from gamingcrypt.ui.game_widgets import GameCard

    if isinstance(widget, QLineEdit):
        first = "Ⓐ  Keyboard     Ⓑ  Back"
    elif isinstance(widget, QSlider):
        first = "◀ ▶  Adjust     Ⓑ  Back"
    elif isinstance(widget, QComboBox):
        first = "Ⓐ  Choose     Ⓑ  Back"
    elif isinstance(widget, GameCard):
        first = "Ⓐ  Open game     Ⓑ  Back"
    elif isinstance(widget, QAbstractButton) and widget.objectName() == "tab":
        first = "Ⓐ  Open     ◀ ▶  Tabs"
    else:
        first = "Ⓐ  Select     Ⓑ  Back"
    if has_picture(widget):
        first += "     Ⓨ  Picture"
    return f"{first}     {COMMON}"


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

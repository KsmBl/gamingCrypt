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
    return f"{first}     {COMMON}"


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

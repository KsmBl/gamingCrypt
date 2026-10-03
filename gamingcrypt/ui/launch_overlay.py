"""Full-window "Starting <game>…" shown until the game's window is up."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui import theme
from gamingcrypt.ui.widgets import big_button


class LaunchOverlay(QWidget):
    cancelled = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"LaunchOverlay {{ background: {theme.BG}; }}")
        layout = QVBoxLayout(self)
        layout.addStretch()
        self.label = QLabel()
        self.label.setObjectName("title")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        hint = QLabel("GamingCrypt steps aside as soon as the game is on screen\nand comes back when you quit it.")
        hint.setObjectName("subtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        self.back_button = big_button("Back to GamingCrypt")
        self.back_button.clicked.connect(self.cancelled.emit)
        layout.addWidget(self.back_button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.hide()

    def show_for(self, name: str) -> None:
        self.label.setText(f"Starting {name}…")
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

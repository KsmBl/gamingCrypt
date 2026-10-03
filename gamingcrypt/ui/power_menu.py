"""Power menu behind the ⏻ button: shut down, restart, desktop mode."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button, set_status


class PowerMenu(QWidget):
    shutdown = Signal()
    restart = Signal()
    desktop = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("PowerMenu { background: rgba(0, 0, 0, 170); }")
        outer = QVBoxLayout(self)
        outer.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(460)
        box = QVBoxLayout(card)
        box.setContentsMargins(28, 24, 28, 24)
        box.setSpacing(14)
        title = QLabel("Power")
        title.setObjectName("section")
        box.addWidget(title)
        self.shutdown_button = big_button("⏻  Shut down", "danger")
        self.restart_button = big_button("↻  Restart")
        self.desktop_button = big_button("🖥  Desktop mode")
        self.cancel_button = big_button("Cancel")
        for button, signal in ((self.shutdown_button, self.shutdown), (self.restart_button, self.restart),
                               (self.desktop_button, self.desktop)):
            button.clicked.connect(signal.emit)
            box.addWidget(button)
        hint = QLabel("Desktop mode closes GamingCrypt. Your games drive stays unlocked.")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.cancel_button.clicked.connect(self.close_menu)
        box.addWidget(self.cancel_button)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()
        self.hide()

    def open_menu(self) -> None:
        set_status(self.status, "")
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.cancel_button.setFocus()  # a controller press never lands on "Shut down" by accident

    def close_menu(self) -> None:
        self.hide()

    def show_error(self, message: str) -> None:
        set_status(self.status, message, error=True)

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self.close_menu()
            return True
        return False

    def mousePressEvent(self, event):  # noqa: N802
        # tap next to the menu closes it
        if not self.childAt(event.position().toPoint()):
            self.close_menu()

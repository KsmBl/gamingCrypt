"""Power menu behind the ⏻ button: shut down, restart, restart into another system, desktop mode."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button, set_status


class PowerMenu(QWidget):
    shutdown = Signal()
    sleep = Signal()
    lock = Signal()
    restart = Signal()
    desktop = Signal()
    boot_into = Signal(str)  # UEFI entry of another system (e.g. Windows)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card.setFixedWidth(460)
        box = self.box = QVBoxLayout(card)
        box.setContentsMargins(28, 24, 28, 24)
        box.setSpacing(14)
        title = QLabel("Power")
        title.setObjectName("section")
        box.addWidget(title)
        self.shutdown_button = big_button("⏻  Shut down", "danger")
        self.sleep_button = big_button("☾  Sleep")
        self.lock_button = big_button("🔒  Lock now")
        self.restart_button = big_button("↻  Restart")
        self.desktop_button = big_button("🖥  Desktop mode")
        self.cancel_button = big_button("Cancel")
        self.system_buttons: dict[str, object] = {}
        for button, signal in ((self.lock_button, self.lock), (self.sleep_button, self.sleep),
                               (self.shutdown_button, self.shutdown),
                               (self.restart_button, self.restart),
                               (self.desktop_button, self.desktop)):
            button.clicked.connect(signal.emit)
            box.addWidget(button)
        from gamingcrypt.session.mode import in_gaming_session

        hint = QLabel("Desktop mode switches to the desktop; log out there to come back. "
                      "Your games drive stays unlocked." if in_gaming_session()
                      else "Desktop mode closes GamingCrypt. Your games drive stays unlocked.")
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

    def set_systems(self, entries) -> None:
        """One "Restart into …" button per other installed system, below Restart."""
        for button in self.system_buttons.values():
            button.deleteLater()
        self.system_buttons = {}
        at = self.box.indexOf(self.restart_button) + 1
        for entry in entries:
            button = big_button(f"⊞  Restart into {entry.name}" if entry.windows else f"↻  Restart into {entry.name}")
            button.clicked.connect(lambda _c=False, num=entry.num: self.boot_into.emit(num))
            self.box.insertWidget(at, button)
            at += 1
            self.system_buttons[entry.num] = button

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

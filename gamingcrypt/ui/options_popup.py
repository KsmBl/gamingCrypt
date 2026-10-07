"""⚙ Options of a game's, movie's or show's page: a nearly full-size pop-up over the page
instead of a section that unfolds inside it. B, ✕ Close or a tap beside it closes it."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button, enable_touch_scroll

MARGIN = 28


class OptionsPopup(QWidget):
    closed = Signal()

    def __init__(self, page: QWidget, panel: QWidget, title: str):
        super().__init__(page)
        self.page, self.panel = page, panel
        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.card = QFrame()
        self.card.setObjectName("card")
        box = QVBoxLayout(self.card)
        box.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        self.close_button = big_button("✕  Close")
        self.close_button.clicked.connect(lambda: self.set_open(False))
        top.addWidget(self.close_button, alignment=Qt.AlignmentFlag.AlignTop)
        box.addLayout(top)
        panel.setObjectName("")  # (it was a card of its own inside the page)
        panel.layout().setContentsMargins(0, 8, 0, 0)
        panel.show()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(panel)
        column.addStretch()
        scroll.setWidget(holder)
        self.scroll = scroll
        box.addWidget(scroll, 1)
        outer.addWidget(self.card)
        page.installEventFilter(self)
        self.hide()

    def is_open(self) -> bool:
        return not self.isHidden()  # (also while the window isn't on screen)

    def set_open(self, on: bool) -> None:
        if on == self.is_open():
            return
        if not on:
            self.hide()
            self.closed.emit()
            return
        self.setGeometry(self.page.rect())
        self.raise_()
        self.show()
        from gamingcrypt.ui.widgets import settle_focus

        first = next((w for w in self.panel.findChildren(QWidget)
                      if w.focusPolicy() != Qt.FocusPolicy.NoFocus and w.isVisibleTo(self.panel)), None)
        settle_focus(self, first or self.close_button)  # the controller starts on the first option

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.page and event.type() == QEvent.Type.Resize and self.is_open():
            self.setGeometry(self.page.rect())
        return False

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))  # the page dimmed behind it

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self.card.geometry().contains(event.position().toPoint()):
            self.set_open(False)  # a tap beside it
        event.accept()

    def gamepad_back(self) -> bool:
        if self.is_open():
            self.set_open(False)
            return True
        return False


def options_popup(page: QWidget, panel: QWidget, button, title: str) -> OptionsPopup:
    """The page's Options pop-up; closing it un-checks ⚙ Options."""
    popup = OptionsPopup(page, panel, f"Options · {title}")
    popup.closed.connect(lambda: button.setChecked(False))
    return popup

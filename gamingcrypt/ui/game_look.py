"""What makes a game's page look like the game: its cover, blurred, behind everything - and its
facts as small chips instead of a list."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from gamingcrypt.ui.widgets import FlowLayout

# so little of the picture that any text stays readable on it, whatever colours the cover has
BACKDROP_OPACITY = 0.30
BLUR_SIZE = QSize(24, 36)  # shrunk to this and stretched again: a soft blur, and cheap
CHIP_MAX_W = 520


class Backdrop(QWidget):
    """Lies under everything on ``page`` and follows ``cover``'s picture. It fades out towards the
    bottom, where the hexagons of the background are. Painted once per picture and size."""

    def __init__(self, page: QWidget, cover):
        super().__init__(page)
        self.page, self.cover = page, cover
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.picture = QPixmap()
        self.setGeometry(page.rect())
        self.lower()
        page.installEventFilter(self)
        cover.pixmap_changed.connect(self.forget)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.page and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.page.rect())
            self.picture = QPixmap()
        return False

    def forget(self) -> None:
        self.picture = QPixmap()
        self.update()

    def render(self) -> QPixmap:  # noqa: A003
        size = self.size()
        out = QPixmap(size)
        out.fill(Qt.GlobalColor.transparent)
        source = self.cover.pixmap()
        if source is None or source.isNull() or size.isEmpty():
            return out
        small = source.scaled(BLUR_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        big = small.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(out)
        painter.setOpacity(BACKDROP_OPACITY)
        painter.drawPixmap(QPoint((size.width() - big.width()) // 2, 0), big)
        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        fade = QLinearGradient(0, 0, 0, size.height())
        fade.setColorAt(0.0, QColor(0, 0, 0, 255))
        fade.setColorAt(0.5, QColor(0, 0, 0, 255))
        fade.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(QRect(QPoint(0, 0), size), fade)
        painter.end()
        return out

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        if self.picture.isNull() or self.picture.size() != self.size():
            self.picture = self.render()
        QPainter(self).drawPixmap(0, 0, self.picture)


class FactChips(QWidget):
    """Facts as chips that wrap. Like a label: setText() and text(), one fact per line - a line
    without text gets no chip, and one too long for a chip is cut (all of it in its tooltip)."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.flow = FlowLayout(self, spacing=8)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self._text = ""
        self.setText(text)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:  # noqa: N802 - like QLabel
        if text == self._text:
            return
        self._text = text
        for chip in self.flow.take_all():
            chip.setParent(None)
            chip.deleteLater()
        for line in text.split("\n"):
            if line.strip():
                self.flow.addWidget(self._chip(line))
        self.flow.invalidate()
        self.updateGeometry()

    def _chip(self, line: str) -> QLabel:
        chip = QLabel(self)
        chip.setObjectName("factChip")
        chip.setTextFormat(Qt.TextFormat.PlainText)
        chip.ensurePolished()
        shown = chip.fontMetrics().elidedText(line, Qt.TextElideMode.ElideMiddle, CHIP_MAX_W)
        chip.setText(shown)
        if shown != line:
            chip.setToolTip(line)
        return chip

    def chips(self) -> list[QLabel]:
        return self.flow.widgets()

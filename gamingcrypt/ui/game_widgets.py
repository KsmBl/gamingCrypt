"""Cards and helpers for showing games."""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.webapi import format_price
from gamingcrypt.ui import theme
from gamingcrypt.ui.tasks import run_async

COVER_W, COVER_H = 200, 300


def format_date(ts: int | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d %b %Y")


def format_size(size: int) -> str:
    if not size:
        return "-"
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return "-"


def format_playtime(minutes: int) -> str:
    if not minutes:
        return "Never played"
    if minutes < 60:
        return f"{minutes} min played"
    return f"{minutes / 60:.1f} h played"


def meta_text(game: SteamGame, sort_key: str = "name") -> str:
    if sort_key == "release_date":
        return f"Released {format_date(game.release_date)}"
    if sort_key == "price":
        return format_price(game.price_cents, game.currency)
    if sort_key == "last_update":
        return f"Updated {format_date(game.last_updated)}"
    if sort_key == "playtime" or game.installed:
        return format_playtime(game.playtime_minutes)
    return "Not installed"


def placeholder_cover(name: str, w: int = COVER_W, h: int = COVER_H) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor(theme.SURFACE_HI))
    painter = QPainter(pix)
    painter.setPen(QColor(theme.TEXT_DIM))
    font = QFont()
    font.setPixelSize(int(h * 0.3))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, (name[:1] or "?").upper())
    painter.end()
    return pix


def load_cover(service, appid: int, label: QLabel, w: int = COVER_W, h: int = COVER_H) -> None:
    """Show the cached cover immediately, otherwise download it in the background."""

    def apply(path) -> None:
        if path is None:
            return
        pix = QPixmap(str(path))
        if not pix.isNull():
            label.setPixmap(pix.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation).copy(0, 0, w, h))

    local = service.local_image(appid)
    if local is not None:
        apply(local)
    else:
        run_async(lambda: service.download_image(appid), apply, owner=label)


class Tappable(QFrame):
    """A frame that emits ``tapped`` on a short tap (not after a flick-scroll)."""

    tapped = Signal()
    MAX_MOVE = 20

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._press: QPoint | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: N802
        self._press = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._press is not None and (event.globalPosition().toPoint() - self._press).manhattanLength() <= self.MAX_MOVE:
            self.tapped.emit()
        self._press = None
        super().mouseReleaseEvent(event)


class GameCard(Tappable):
    clicked = Signal(int)

    def __init__(self, game: SteamGame, service=None, sort_key: str = "name", parent: QWidget | None = None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        self.setFixedWidth(COVER_W + 20)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setPixmap(placeholder_cover(game.name))
        layout.addWidget(self.cover)
        self.title = QLabel(game.name)
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        self.title.setFixedHeight(58)
        self.title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title)
        self.meta = QLabel()
        self.meta.setObjectName("cardMeta")
        layout.addWidget(self.meta)
        self.set_sort_key(sort_key)
        self.tapped.connect(lambda: self.clicked.emit(self.game.appid))
        if service is not None:
            load_cover(service, game.appid, self.cover)

    def set_sort_key(self, sort_key: str) -> None:
        self.sort_key = sort_key
        prefix = "● " if self.game.installed else ""
        self.meta.setText(prefix + meta_text(self.game, sort_key))


class SourceCard(Tappable):
    """Big entry tile for a game source (Steam now, more later)."""

    def __init__(self, name: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedSize(320, 180)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        self.title = QLabel(name)
        self.title.setObjectName("title")
        layout.addWidget(self.title)
        layout.addStretch()
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("cardMeta")
        layout.addWidget(self.subtitle)

"""Small pictures for the library cards: the Steam logo, a star, a clock, and a little
drawing of each emulated console's controller (from console_pictures)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

from gamingcrypt.ui import console_pictures, theme

# Steam logo - Simple Icons (CC0), https://simpleicons.org
STEAM_PATH = "M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z"
STAR_COLOR = "#f5c518"


def _pixmap(w: int, h: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def steam(size: int) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    svg = (f'<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
           f'<path fill="{theme.TEXT}" d="{STEAM_PATH}"/></svg>')
    pixmap, painter = _pixmap(size, size)
    QSvgRenderer(QByteArray(svg.encode())).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


def star(size: int) -> QPixmap:
    pixmap, painter = _pixmap(size, size)
    font = QFont()
    font.setPixelSize(int(size * 0.95))
    painter.setFont(font)
    painter.setPen(QColor(STAR_COLOR))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "★")
    painter.end()
    return pixmap


def clock(size: int) -> QPixmap:
    pixmap, painter = _pixmap(size, size)
    pen = QPen(QColor(theme.TEXT), max(2, size // 14))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    c, r = size / 2, size / 2 - pen.width()
    painter.drawEllipse(QPointF(c, c), r, r)
    painter.drawLine(QPointF(c, c), QPointF(c, c - r * 0.6))
    painter.drawLine(QPointF(c, c), QPointF(c + r * 0.45, c + r * 0.2))
    painter.end()
    return pixmap


def console(system_id: str, w: int, h: int) -> QPixmap:
    """The controller drawing of the controls page, with its buttons, small."""
    pic = console_pictures.picture(system_id)
    pixmap, painter = _pixmap(w, h)
    scale = min(w / console_pictures.W, h / console_pictures.H)
    painter.translate((w - console_pictures.W * scale) / 2, (h - console_pictures.H * scale) / 2)
    painter.scale(scale, scale)
    console_pictures.paint(painter, pic, body="#5b6478", outline="#aab1c2")  # light: it's small on a dark card
    painter.setPen(Qt.PenStyle.NoPen)
    for name, (x, y, kind) in pic.buttons.items():
        if kind == "dir":
            continue  # the D-pad is drawn already
        bw, bh = console_pictures.SIZES[kind]
        painter.setBrush(QColor(pic.colors.get(name, "#2a2f3b")))
        painter.drawRoundedRect(QRectF(x - bw / 2, y - bh / 2, bw, bh), min(bw, bh) / 2, min(bw, bh) / 2)
    painter.end()
    return pixmap

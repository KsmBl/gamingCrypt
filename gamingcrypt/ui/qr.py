"""QR codes (for a phone's camera) as pixmaps - segno does the encoding."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap


def qr_pixmap(text: str, size: int = 220) -> QPixmap | None:
    """Black on white with a quiet zone, so phones read it on the dark UI; None without segno."""
    try:
        import segno
    except ImportError:
        return None
    rows = [list(row) for row in segno.make(text, error="m").matrix_iter(scale=1, border=3)]
    module = max(1, size // len(rows))
    side = module * len(rows)
    pixmap = QPixmap(side, side)
    pixmap.fill(QColor("white"))
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                painter.drawRect(QRect(x * module, y * module, module, module))
    painter.end()
    return pixmap


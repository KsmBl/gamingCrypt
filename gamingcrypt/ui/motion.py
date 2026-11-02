"""Page changes that move: the old screen slides and fades away, a game's cover flies from its card
to its place on the game's page. Can be switched off (Settings -> Device -> Appearance).

Only a picture moves: the new page is there at once, underneath - the highlight, the controller and
every tap work on it right away - and the picture on top lets everything through.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from gamingcrypt.ui import theme

DURATION_MS = 170
SLIDE = 0.2  # of the width

_config: dict | None = None  # None: not set up (tests, screenshots): nothing moves


def configure(config: dict | None) -> None:
    global _config
    _config = config


def enabled() -> bool:
    return _config is not None and bool((_config.get("appearance") or {}).get("motion", True))


def switched_off() -> bool:
    """Asked for no movement (not just "not set up")."""
    return _config is not None and not enabled()


class Transition(QWidget):
    """The old screen (and a flying cover) over ``host``, for a moment."""

    def __init__(self, host: QWidget, old: QPixmap, direction: int = 0, flight: tuple | None = None):
        """direction: 1 the old screen leaves to the left, -1 to the right, 0 it only fades.
        flight: (picture, where it starts in the host, the widget it flies to)."""
        super().__init__(host)
        self.old, self.direction, self.flight = old, direction, flight
        self.progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(host.rect())
        self.animation = QVariantAnimation(self)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setDuration(DURATION_MS)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._step)
        self.animation.finished.connect(self.finish)
        self.raise_()
        self.show()
        self.animation.start()

    def _step(self, value: float) -> None:
        self.progress = value
        self.update()

    def finish(self) -> None:
        if self.isHidden():
            return
        self.animation.stop()
        self.hide()
        self.deleteLater()

    def flight_rect(self) -> QRectF | None:
        """Where the cover is now."""
        if self.flight is None or not shiboken6.isValid(self.flight[2]):
            return None
        _picture, start, target = self.flight
        end = QRect(target.mapTo(self.parentWidget(), QPoint(0, 0)), target.size())
        t = self.progress
        return QRectF(start.x() + (end.x() - start.x()) * t, start.y() + (end.y() - start.y()) * t,
                      start.width() + (end.width() - start.width()) * t,
                      start.height() + (end.height() - start.height()) * t)

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setOpacity(1.0 - self.progress)
        painter.drawPixmap(QPoint(int(-self.direction * SLIDE * self.width() * self.progress), 0), self.old)
        rect = self.flight_rect()
        if rect is not None:
            painter.setOpacity(1.0)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setClipPath(theme.cut_path(rect, theme.CUT["cover"]))
            painter.drawPixmap(rect, self.flight[0], QRectF(self.flight[0].rect()))


def before(host: QWidget) -> QPixmap | None:
    """Call before the page changes: the picture of what's on screen now - None: nothing will move
    (switched off, not on screen). A movement still going on ends here."""
    if not enabled() or not host.isVisible() or host.size().isEmpty():
        return None
    for running in host.findChildren(Transition, options=Qt.FindChildOption.FindDirectChildrenOnly):
        running.finish()
    window = host.window()
    return window.grab(QRect(host.mapTo(window, QPoint(0, 0)), host.size()))


def slide(host: QWidget, old: QPixmap | None, direction: int) -> None:
    if old is not None:
        Transition(host, old, direction)


def fade(host: QWidget, old: QPixmap | None) -> None:
    slide(host, old, 0)


def fly(host: QWidget, old: QPixmap | None, picture: QPixmap, start: QRect, target: QWidget) -> None:
    """The old screen fades while ``picture`` goes from ``start`` to ``target``'s place."""
    if old is not None:
        Transition(host, old, 0, (picture, start, target))

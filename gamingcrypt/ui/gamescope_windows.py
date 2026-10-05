"""Gaming mode: every window GamingCrypt opens carries its gamescope app id.

In gamescope's Steam mode a window without an app id is never shown, and a popup
(the open list of a drop-down, override-redirect) only appears on top when it has
the app id of the focused window. Qt opens those lists as windows of their own, so
each one gets GamingCrypt's id right before it's mapped (Show comes before that).
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from gamingcrypt.system import gamescope_ctl

log = logging.getLogger("gamingcrypt.gamescope")


class WindowAppIds(QObject):
    def __init__(self, set_appid: Callable[[int], bool] | None = None, parent: QObject | None = None):
        super().__init__(parent)
        self.set_appid = set_appid or (lambda wid: gamescope_ctl.set_window_appid(wid))
        self.tagged: set[int] = set()

    def install(self, app: QApplication) -> "WindowAppIds":
        app.installEventFilter(self)
        return self

    def tag(self, widget: QWidget) -> None:
        wid = int(widget.winId())
        if wid in self.tagged:
            return  # the property stays on the X window across hide / show
        if self.set_appid(wid):
            self.tagged.add(wid)
        else:
            log.warning("could not give window %s its gamescope app id (xprop missing?)", wid)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
            self.tag(obj)
        return False

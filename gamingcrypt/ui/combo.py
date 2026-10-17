"""Drop-downs whose open list is part of GamingCrypt's window, on top of everything in it.

Qt opens a drop-down's list as a window of its own (a popup). Which window is in front is
then up to the compositor - under gamescope a list could end up behind GamingCrypt's
window (or what else it draws), out of sight. Here the list is a widget in the window
itself, raised over everything: nothing can cover it.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QListView, QWidget

MARGIN = 8  # from the window's edges


class ComboList(QListView):
    """The open list of a ComboBox (its model), inside the combo's window."""

    current: "ComboList | None" = None  # the one open right now (the controller sends it its keys)

    def __init__(self, combo: "ComboBox"):
        super().__init__(combo.window())
        self.combo = combo
        self.setObjectName("comboList")
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(self._chosen)
        self.entered.connect(self.setCurrentIndex)  # (the pointer's row lit, as in Qt's own list)
        from gamingcrypt.ui.widgets import enable_touch_scroll

        enable_touch_scroll(self)
        self.hide()

    def open(self) -> None:
        combo = self.combo
        self.setModel(combo.model())
        self.setModelColumn(combo.modelColumn())
        self.setRootIndex(combo.rootModelIndex())
        current = combo.model().index(combo.currentIndex(), combo.modelColumn(), combo.rootModelIndex())
        self.setCurrentIndex(current)
        self.setGeometry(self.place())
        self.scrollTo(current, QAbstractItemView.ScrollHint.PositionAtCenter)
        ComboList.current = self
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)

    def place(self) -> QRect:
        """Under the drop-down - over it when there's more room above; as many rows as fit."""
        combo, window = self.combo, self.parentWidget()
        self.ensurePolished()
        rows = combo.count()
        row = max(self.sizeHintForRow(0), 1) if rows else 1
        frame = 2 * self.frameWidth()  # (the style sheet's border and padding)
        wanted = min(rows, combo.maxVisibleItems()) * row + frame
        top_left = combo.mapTo(window, QPoint(0, 0))
        below = window.height() - MARGIN - (top_left.y() + combo.height())
        above = top_left.y() - MARGIN
        width = min(max(combo.width(), self.sizeHintForColumn(combo.modelColumn()) + frame + 24),
                    window.width() - 2 * MARGIN)
        x = max(MARGIN, min(top_left.x(), window.width() - MARGIN - width))
        if wanted <= below or below >= above:
            height = max(min(wanted, below), min(wanted, row + frame))
            return QRect(x, top_left.y() + combo.height(), width, height)
        height = min(wanted, above)
        return QRect(x, top_left.y() - height, width, height)

    def close_list(self, chosen: int | None = None) -> None:
        if ComboList.current is self:
            ComboList.current = None
        QApplication.instance().removeEventFilter(self)
        was_open = self.isVisible()
        self.hide()
        combo = self.combo
        if not shiboken6.isValid(combo):
            return
        if was_open and combo.isVisible():
            combo.setFocus(Qt.FocusReason.PopupFocusReason)  # (the controller goes on from there)
        if chosen is not None:
            combo.setCurrentIndex(chosen)
            combo.activated.emit(chosen)
            combo.textActivated.emit(combo.itemText(chosen))

    def _chosen(self, index: QModelIndex) -> None:
        if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.close_list(index.row())

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Select):
            self._chosen(self.currentIndex())
        elif event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Back, Qt.Key.Key_F4):
            self.close_list()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.TouchBegin) and isinstance(watched, QWidget):
            if watched is self or self.isAncestorOf(watched):
                return False
            self.close_list()  # a tap beside it closes it - and does nothing else (as Qt's own list)
            return True
        if kind in (QEvent.Type.Resize, QEvent.Type.Hide) and watched in (self.parentWidget(), self.combo):
            self.close_list()  # (where it was is gone)
        elif kind == QEvent.Type.WindowDeactivate and watched is self.parentWidget():
            self.close_list()
        return False


class ComboBox(QComboBox):
    """A drop-down whose list opens inside the window (see above)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list: ComboList | None = None

    def showPopup(self) -> None:  # noqa: N802 - Qt API
        if not self.count() or not self.isVisible():
            return
        if self._list is None or not shiboken6.isValid(self._list) or self._list.parentWidget() is not self.window():
            self._list = ComboList(self)
        self._list.open()

    def hidePopup(self) -> None:  # noqa: N802 - Qt API
        if self._list is not None and shiboken6.isValid(self._list) and self._list.isVisible():
            self._list.close_list()

    def list_open(self) -> bool:
        return self._list is not None and shiboken6.isValid(self._list) and self._list.isVisible()


def open_list() -> QWidget | None:
    """The drop-down list open right now - ours, or one of Qt's own (a popup window)."""
    current = ComboList.current
    if current is not None and shiboken6.isValid(current) and current.isVisible():
        return current
    return QApplication.activePopupWidget()

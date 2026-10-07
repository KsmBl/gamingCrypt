"""Hold a picture (a game's, movie's or show's card or page) to choose another one - or
⚙ Options → Change picture on its page."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap, QWindow
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt import cover_choice
from gamingcrypt.cover_choice import Choice, Source
from gamingcrypt.ui.game_widgets import Cover, Tappable, load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import (FlowLayout, KeyboardFocusFilter, OnScreenKeyboard, big_button,
                                   enable_touch_scroll, set_status)

HOLD_MS = 600
MAX_MOVE = 20  # more is scrolling, not holding
CHOICE_W, CHOICE_H = 150, 225


def game_types() -> tuple:
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.wine.library import WindowsGame

    return SteamGame, RomGame, WindowsGame


def game_of(widget: QWidget | None, stop: QWidget):
    """The game a cover belongs to: the nearest card or page (below ``stop``) with one."""
    types = game_types()
    while widget is not None and widget is not stop:
        game = getattr(widget, "game", None)
        if isinstance(game, types):
            return game
        widget = widget.parentWidget()
    return None


def media_of(widget: QWidget | None, stop: QWidget):
    """The movie or show a cover belongs to (an episode's picture isn't the show's)."""
    from gamingcrypt.movies.library import Movie
    from gamingcrypt.shows.library import Show

    while widget is not None and widget is not stop:
        if hasattr(widget, "episode"):
            return None
        for attribute in ("show_item", "movie"):
            item = getattr(widget, attribute, None)
            if isinstance(item, (Movie, Show)):
                return item
        widget = widget.parentWidget()
    return None


def picture_button(open_picker) -> QWidget:
    """⚙ Options → Change picture: the same as holding the picture (and with the controller)."""
    button = big_button("🖼  Change picture")
    button.clicked.connect(open_picker)
    return button


def load_game_cover(label: QLabel, game, tab, w: int, h: int) -> None:
    """Draw the game's cover into the label again - as its card does."""
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.wine.library import WindowsGame

    if isinstance(game, RomGame):
        from gamingcrypt.ui.emulation_pages import load_rom_cover

        load_rom_cover(label, game, getattr(tab, "covers", None), w, h)
    elif isinstance(game, WindowsGame):
        from gamingcrypt.ui.wine_pages import load_windows_cover

        load_windows_cover(label, game, getattr(tab, f"{game.KIND}_covers", None), w, h)
    else:
        label.setPixmap(placeholder_cover(game.name, w, h))
        load_cover(tab.service, game.appid, label, w, h)


class HoldToChoose(QObject):
    """Watches every press in a tab: held on a picture -> ``held(item)`` (``find`` says whose).

    The press is taken where it reaches the window: the touch-scroll areas hold presses
    back until the finger lifts (or scrolls), so the picture itself would get it too late.
    After a hold, the press and release the scroll area hands on are swallowed, so the
    card isn't opened as well."""

    held = Signal(object)

    def __init__(self, tab: QWidget, find=game_of):
        super().__init__(tab)
        self.tab, self.find = tab, find
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HOLD_MS)
        self.timer.timeout.connect(self._fire)
        self.start = QPoint()
        self.game = None
        self.fired = False
        from PySide6.QtWidgets import QApplication

        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease,
                        QEvent.Type.MouseButtonDblClick):
            return False
        if isinstance(obj, QWindow):  # the finger itself, before any widget
            if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self.fired = False
                self._pressed(event.globalPosition().toPoint())
            elif kind == QEvent.Type.MouseMove and self.timer.isActive():
                if (event.globalPosition().toPoint() - self.start).manhattanLength() > MAX_MOVE:
                    self.timer.stop()
            elif kind == QEvent.Type.MouseButtonRelease:
                self.timer.stop()
                if self.fired:
                    QTimer.singleShot(0, self._done)  # after what the release hands on to widgets
            return False
        return self.fired and kind != QEvent.Type.MouseMove  # held: no tap on the card as well

    def _done(self) -> None:
        self.fired = False

    def _pressed(self, pos: QPoint) -> None:
        from PySide6.QtWidgets import QApplication

        widget = QApplication.widgetAt(pos)
        if widget is None or not self.tab.isVisible() or not self.tab.isAncestorOf(widget):
            return
        cover = widget
        while cover is not None and not isinstance(cover, Cover):
            cover = cover.parentWidget()
            if cover is self.tab:
                return
        parent = cover
        while parent is not None and parent is not self.tab:
            if isinstance(parent, CoverPicker):
                return  # the pictures to choose from
            parent = parent.parentWidget()
        game = self.find(cover, self.tab) if cover is not None else None
        if game is None:
            return
        self.game, self.start = game, pos
        self.timer.start()

    def _fire(self) -> None:
        self.fired = True
        self.held.emit(self.game)


class ChoiceCard(Tappable):
    def __init__(self, choice: Choice):
        super().__init__()
        self.choice, self.data = choice, None
        self.setObjectName("card")
        self.setFixedWidth(CHOICE_W + 20)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        self.cover = Cover()
        self.cover.setFixedSize(CHOICE_W, CHOICE_H)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setPixmap(placeholder_cover(choice.name, CHOICE_W, CHOICE_H))
        layout.addWidget(self.cover)
        name = QLabel(choice.name)
        name.setObjectName("cardMeta")
        name.setWordWrap(True)
        name.setFixedHeight(40)
        name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(name)

    def show_picture(self, data: bytes | None) -> bool:
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            return False
        self.data = data
        self.cover.setPixmap(pixmap.scaled(CHOICE_W, CHOICE_H, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        return True


class CoverPicker(QWidget):
    chosen = Signal(bytes)  # a picture, or cover_choice.DRAWN

    def __init__(self, tab, item, source: Source, get=None, parent: QWidget | None = None, title: str = ""):
        super().__init__(parent)
        self.tab, self.item, self.source = tab, item, source
        self.get = get or cover_choice._default_get
        self.cards: list[ChoiceCard] = []
        self.searching = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(f"Picture for {title or item.name}")
        title.setObjectName("title")
        top.addWidget(title, 1)
        self.drawn_button = big_button("Drawn cover")
        self.drawn_button.setToolTip("No picture: the card shows the first letter")
        self.drawn_button.clicked.connect(lambda: self.chosen.emit(cover_choice.DRAWN))
        top.addWidget(self.drawn_button)
        layout.addLayout(top)
        row = QHBoxLayout()
        self.search = QLineEdit(source.query)
        self.search.setPlaceholderText("🔍  Search by name")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.do_search)
        row.addWidget(self.search, 1)
        search_button = big_button("Search", "primary")
        search_button.clicked.connect(self.do_search)
        row.addWidget(search_button)
        layout.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        grid = QWidget()
        self.grid = FlowLayout(grid, spacing=16)
        scroll.setWidget(grid)
        layout.addWidget(scroll, 1)
        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.do_search)
        self.keyboard.dismissable = True
        self.keyboard.hide()
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)
        self.do_search()

    def do_search(self) -> None:
        query = self.search.text().strip()
        if self.searching:
            return
        self.keyboard.hide()
        self.searching = True
        set_status(self.status, f'Looking for pictures of "{query}"…' if query else "Looking for pictures…")
        run_async(lambda: self.source.search(query), self._found,
                  lambda exc: self._found(exc), owner=self)

    def _found(self, result) -> None:
        self.searching = False
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = []
        if isinstance(result, Exception):
            set_status(self.status, "No network - pictures can't be looked up right now", error=True)
            return
        for choice in result:
            card = ChoiceCard(choice)
            card.tapped.connect(lambda c=card: self.choose(c))
            self.grid.addWidget(card)
            self.cards.append(card)
            run_async(lambda c=choice: cover_choice.download(c, self.get), lambda data, c=card: self._loaded(c, data),
                      lambda _e, c=card: self._loaded(c, None), owner=self, pool=self.pool)
        set_status(self.status, "Tap a picture to use it" if result
                   else "Nothing found - try another name, or use the drawn cover")

    def _loaded(self, card: ChoiceCard, data) -> None:
        if card not in self.cards:
            return  # an earlier search
        if not card.show_picture(data):
            card.hide()  # nothing behind that address
            if not any(c.isVisibleTo(self) for c in self.cards):
                set_status(self.status, "Nothing found - try another name, or use the drawn cover")

    def choose(self, card: ChoiceCard) -> None:
        if card.data is None:
            set_status(self.status, "That picture is still loading")
            return
        self.chosen.emit(card.data)


def open_picker(tab, item, refresh, notice, title: str = "") -> CoverPicker | None:
    """The picker on the tab's stack; the chosen picture is saved, then ``refresh(item)``
    draws it again where it's shown. ``notice(text)``: why it can't be changed."""
    from PySide6.QtGui import QPixmapCache

    source = cover_choice.source_for(item, tab)
    if source is None:
        notice("This picture can't be changed while the drive is locked")
        return None
    page = CoverPicker(tab, item, source, title=title)

    def chosen(data: bytes) -> None:
        try:
            cover_choice.save(source.path, data)
        except OSError as exc:
            set_status(page.status, f"Couldn't save the picture: {exc}", error=True)
            return
        QPixmapCache.clear()  # the same file name, a new picture
        tab.back()
        refresh(item)

    page.chosen.connect(chosen)
    tab.push(page)
    page.search.setFocus()
    return page

"""Movies tab: every video in <drive>/Movies as a card, its page, the player and uploads.

Cover and info come from the internet once (movies/metadata) and are kept next to the
movie; watched / stopped-at is kept there too (movies/library).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

from gamingcrypt.movies import library
from gamingcrypt.movies.library import Movie
from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import COVER_H, COVER_W, Tappable, card_margins, format_size, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.upload_page import UploadPage
from gamingcrypt.ui.widgets import (FlowLayout, FoldingHeader, KeyboardFocusFilter, OnScreenKeyboard, big_button,
                                   enable_touch_scroll, focus_and_reveal, set_status)

POLL_MS = 5000  # how often the player is asked where it is


def movie_cover(movie: Movie, w: int, h: int) -> QPixmap:
    """The cover (or a letter), marked: ✓ watched, a bar how far it was watched."""
    pixmap = QPixmap(str(movie.cover_path)) if movie.cover_path.exists() else QPixmap()
    if pixmap.isNull():
        pixmap = placeholder_cover(movie.title, w, h)
    else:
        scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        pixmap = scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
    info = movie.info
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if info.watched:
        size = max(28, w // 6)
        rect = QRectF(w - size - 8, 8, size, size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SUCCESS))
        painter.drawEllipse(rect)
        font = QFont()
        font.setPixelSize(int(size * 0.6))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "✓")
    if info.resume_at and info.total:
        bar = max(6, h // 40)
        painter.fillRect(QRectF(0, h - bar, w, bar), QColor(0, 0, 0, 170))
        painter.fillRect(QRectF(0, h - bar, w * min(1.0, info.resume_at / info.total), bar), QColor(theme.ACCENT))
    painter.end()
    return pixmap


def facts(movie: Movie) -> str:
    """"1999 · 2 h 16 min · FSK 16"."""
    info = movie.info
    parts = [str(movie.year) if movie.year else "", library.format_length(info.minutes), info.fsk]
    return " · ".join(p for p in parts if p)


class MovieCard(Tappable):
    clicked = Signal(object)

    def __init__(self, movie: Movie, parent: QWidget | None = None):
        super().__init__(parent)
        self.movie = movie
        self.setObjectName("card")
        self.setFixedWidth(COVER_W + 20)  # as big as a game's card
        layout = QVBoxLayout(self)
        card_margins(layout)
        layout.setSpacing(6)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        layout.addWidget(self.cover)
        self.title = QLabel()
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        self.title.setFixedHeight(58)
        self.title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title)
        self.meta = QLabel()
        self.meta.setObjectName("cardMeta")
        layout.addWidget(self.meta)
        self.tapped.connect(lambda: self.clicked.emit(self.movie))
        self.update_movie()

    def update_movie(self) -> None:
        self.title.setText(self.movie.title)
        self.meta.setText(facts(self.movie) or format_size(self.movie.size))
        self.cover.setPixmap(movie_cover(self.movie, COVER_W, COVER_H))


class MoviesHome(QWidget):
    def __init__(self, tab: "MoviesTab"):
        super().__init__()
        self.tab = tab
        self.cards: dict[str, MovieCard] = {}
        self.shown: list[str] = []  # keys, in order
        self.watch_state = "all"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        self.header = QWidget()
        header = QVBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        top = QHBoxLayout()
        title = QLabel("Movies")
        title.setObjectName("title")
        top.addWidget(title)
        self.count_label = QLabel("")
        self.count_label.setObjectName("subtitle")
        top.addWidget(self.count_label)
        top.addStretch()
        self.add_button = big_button("⬆  Add movies", "primary")
        self.add_button.clicked.connect(tab.open_upload)
        top.addWidget(self.add_button)
        header.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search title, actor or director")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        header.addWidget(self.search)
        filters = QHBoxLayout()
        self.state_buttons = {}
        for key, label in library.STATES.items():
            button = big_button(label, checkable=True)
            button.clicked.connect(lambda _=False, k=key: self.set_state(k))
            self.state_buttons[key] = button
            filters.addWidget(button)
        self.genre_combo = QComboBox()
        self.genre_combo.addItem("All genres", "")
        self.genre_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.genre_combo, 1)
        self.age_combo = QComboBox()
        self.age_combo.addItem("Any age", None)
        for age in library.AGES:
            self.age_combo.addItem(f"Up to FSK {age}", age)
        self.age_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.age_combo)
        self.sort_combo = QComboBox()
        for key, label in library.SORTS.items():
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.sort_combo)
        header.addLayout(filters)
        self.notice = QLabel("")
        self.notice.setObjectName("status")
        self.notice.setWordWrap(True)
        self.notice.hide()
        header.addWidget(self.notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 10, 0, 10)
        self.grid_widget = QWidget()
        self.grid = FlowLayout(self.grid_widget)
        box.addWidget(self.grid_widget)
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("subtitle")
        self.empty_label.setWordWrap(True)
        box.addWidget(self.empty_label)
        box.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.folding = FoldingHeader(scroll, self.header)

        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.keyboard.hide)
        self.keyboard.dismissable = True
        self.keyboard.hide()
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)
        self.set_state("all")

    def show_notice(self, text: str, error: bool = False) -> None:
        set_status(self.notice, text, error=error)
        self.notice.setVisible(bool(text))

    def set_state(self, key: str) -> None:
        self.watch_state = key
        for k, button in self.state_buttons.items():
            button.setChecked(k == key)
        self.refresh()

    def set_movies(self, movies: list[Movie]) -> None:
        keys = {m.key for m in movies}
        for key in [k for k in self.cards if k not in keys]:
            self.cards.pop(key).deleteLater()
        for movie in movies:
            card = self.cards.get(movie.key)
            if card is None:
                card = self.cards[movie.key] = MovieCard(movie)
                card.clicked.connect(self.tab.open_movie)
            else:
                card.movie = movie
                card.update_movie()
        self.update_genres(movies)
        self.refresh()

    def update_genres(self, movies: list[Movie]) -> None:
        current = self.genre_combo.currentData()
        self.genre_combo.blockSignals(True)
        self.genre_combo.clear()
        self.genre_combo.addItem("All genres", "")
        for genre in library.genres(movies):
            self.genre_combo.addItem(genre, genre)
        self.genre_combo.setCurrentIndex(max(0, self.genre_combo.findData(current)))
        self.genre_combo.blockSignals(False)

    def update_movie(self, movie: Movie) -> None:
        card = self.cards.get(movie.key)
        if card is not None:
            card.movie = movie
            card.update_movie()

    def refresh(self) -> None:
        movies = self.tab.movies
        shown = library.sort_movies(library.filter_movies(
            movies, self.search.text(), self.watch_state, self.genre_combo.currentData() or "",
            self.age_combo.currentData()), self.sort_combo.currentData() or "title")
        focused = self.window().focusWidget() if self.window() else None
        for card in self.grid.take_all():
            card.hide()
        for movie in shown:
            card = self.cards.get(movie.key)
            if card is not None:
                self.grid.addWidget(card)
                card.show()
        self.grid.invalidate()
        self.shown = [m.key for m in shown]
        if isinstance(focused, MovieCard) and focused.isVisible():
            focus_and_reveal(focused)
        self.count_label.setText(f"{len(movies)} movie{'s' if len(movies) != 1 else ''}" if movies else "")
        if self.tab.root is None:
            self.empty_label.setText("Unlock your encrypted drive to see your movies")
        elif not movies:
            self.empty_label.setText("No movies yet - add some with ⬆ Add movies (from a PC or phone in the same "
                                     "Wi-Fi), or put them into the Movies folder on your drive")
        elif not shown:
            self.empty_label.setText("No movie matches")
        else:
            self.empty_label.setText("")


class RemoveMovieConfirm(QFrame):
    removed = Signal(str)
    cancelled = Signal()

    def __init__(self, movie: Movie, root: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.movie, self.root = movie, root
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        extra = len(library.related_files(movie))
        self.question = QLabel(f"Really remove {movie.title}?\nThe movie file and its cover, info and subtitles "
                               f"({extra + 1} file{'s' if extra else ''}, {format_size(library.removal_size(movie))})"
                               " are deleted from the drive.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        row = QHBoxLayout()
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.confirm)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        row.addWidget(self.remove_button)
        row.addWidget(self.cancel_button)
        row.addStretch()
        layout.addLayout(row)

    def gamepad_back(self) -> bool:
        self.cancelled.emit()
        return True

    def confirm(self) -> None:
        self.remove_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        movie, root = self.movie, self.root
        run_async(lambda: library.remove(movie, root),
                  lambda freed: self.removed.emit(f"{movie.title} removed, {format_size(freed)} freed"),
                  lambda exc: self.removed.emit(f"Could not remove it: {exc}"), owner=self)


class MoviePage(QWidget):
    """Title, facts, description, cast - Play / Resume, watched, remove."""

    def __init__(self, tab: "MoviesTab", movie: Movie, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.movie = tab, movie
        self.confirm: RemoveMovieConfirm | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        top.addStretch()
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(36)
        self.cover = QLabel()
        self.cover.setFixedSize(300, 450)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.facts = QLabel()
        self.facts.setObjectName("detailMeta")
        self.facts.setWordWrap(True)
        info.addWidget(self.facts)
        self.progress = QLabel()
        self.progress.setObjectName("cardTitle")
        info.addWidget(self.progress)
        self.actions = QWidget()  # wraps to a second row when the screen is too narrow for all
        actions = FlowLayout(self.actions, spacing=16)
        actions.setContentsMargins(0, 0, 0, 0)
        self.main_button = big_button("", "primary")
        self.main_button.setMinimumWidth(220)
        self.main_button.clicked.connect(lambda: self.play(from_start=False))
        actions.addWidget(self.main_button)
        self.restart_button = big_button("⟲  From the start")
        self.restart_button.clicked.connect(lambda: self.play(from_start=True))
        actions.addWidget(self.restart_button)
        self.watched_button = big_button("")
        self.watched_button.clicked.connect(self.toggle_watched)
        actions.addWidget(self.watched_button)
        self.options_button = big_button("⚙ Options", checkable=True)
        self.options_button.toggled.connect(self.toggle_options)
        actions.addWidget(self.options_button)
        info.addWidget(self.actions)
        self.options_panel = QFrame()
        self.options_panel.setObjectName("card")
        self.options_layout = QVBoxLayout(self.options_panel)
        self.options_layout.setContentsMargins(22, 18, 22, 18)
        self.file_label = QLabel()
        self.file_label.setObjectName("cardMeta")
        self.file_label.setWordWrap(True)
        self.options_layout.addWidget(self.file_label)
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.ask_remove)
        self.options_layout.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_panel.hide()
        info.addWidget(self.options_panel)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        info.addWidget(self.status)
        self.plot = QLabel()
        self.plot.setWordWrap(True)
        info.addWidget(self.plot)
        self.people = QLabel()
        self.people.setObjectName("detailMeta")
        self.people.setWordWrap(True)
        info.addWidget(self.people)
        from gamingcrypt.movies.player import CONTROLS

        controls = QLabel("While it plays: " + CONTROLS)
        controls.setObjectName("cardMeta")
        controls.setWordWrap(True)
        info.addWidget(controls)
        info.addStretch()
        body.addLayout(info, 1)
        content = QWidget()
        content.setLayout(body)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        enable_touch_scroll(self.scroll)
        layout.addWidget(self.scroll, 1)
        self.update_movie()

    def update_movie(self, movie: Movie | None = None) -> None:
        movie = self.movie = movie or self.movie
        info = movie.info
        self.title.setText(movie.title)
        self.cover.setPixmap(movie_cover(movie, 300, 450))
        genres = ", ".join(info.genres)
        self.facts.setText("\n".join(p for p in (facts(movie), genres) if p) or "No info found online")
        resume = info.resume_at
        if resume:
            total = f" of {library.format_time(info.total)}" if info.total else ""
            self.progress.setText(f"Stopped at {library.format_time(resume)}{total}")
        else:
            self.progress.setText("✓ Watched" if info.watched else "")
        self.progress.setVisible(bool(self.progress.text()))
        self.main_button.setText(f"▶  Resume at {library.format_time(resume)}" if resume else "▶  Play")
        self.restart_button.setVisible(bool(resume))
        self.watched_button.setText("Mark as unwatched" if info.watched else "✓ Mark as watched")
        self.actions.layout().invalidate()  # buttons shown / hidden, other texts: new rows
        self.plot.setText(info.plot or "No description found.")
        lines = []
        if info.directors:
            lines.append("Director: " + ", ".join(info.directors))
        if info.actors:
            lines.append("Cast:\n" + "\n".join(f"{name}  ·  {role}" if role else name for name, role in info.actors))
        self.people.setText("\n\n".join(lines))
        self.people.setVisible(bool(lines))
        self.file_label.setText(f"{movie.key}  ·  {format_size(movie.size)}")

    def play(self, from_start: bool = False) -> None:
        ok, message = self.tab.play(self.movie, from_start)
        set_status(self.status, "" if ok else message, error=not ok)

    def toggle_watched(self) -> None:
        movie, watched = self.movie, not self.movie.info.watched
        run_async(lambda: library.set_watched(movie, watched), lambda _i: self.tab.movie_changed(movie),
                  lambda exc: set_status(self.status, f"Could not save it: {exc}", error=True), owner=self)

    def toggle_options(self, visible: bool) -> None:
        self.options_panel.setVisible(visible)
        if visible:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.options_panel, 0, 20))
        else:
            self.close_confirm()

    def ask_remove(self) -> None:
        if self.confirm is not None or self.tab.root is None:
            return
        self.confirm = RemoveMovieConfirm(self.movie, self.tab.root)
        self.confirm.cancelled.connect(self.close_confirm)
        self.confirm.removed.connect(self.removed)
        self.options_layout.addWidget(self.confirm)
        self.confirm.show()
        self.remove_button.hide()
        self.confirm.cancel_button.setFocus()  # the safe choice first
        QTimer.singleShot(0, lambda: self.confirm is not None and self.scroll.ensureWidgetVisible(self.confirm, 0, 20))

    def close_confirm(self) -> None:
        if self.confirm is not None:
            self.confirm.deleteLater()
            self.confirm = None
            self.remove_button.show()
            self.remove_button.setFocus()

    def removed(self, message: str) -> None:
        self.tab.home.show_notice(message)
        self.tab.back()
        self.tab.reload()

    def game_session_ended(self, appid: int, failed: bool) -> None:
        if appid == self.movie.appid and failed:
            set_status(self.status, "The player didn't start", error=True)


class MovieUploadPage(UploadPage):
    TITLE = "Add movies"
    HINT = ("Movies from a PC or phone in the same Wi-Fi - they land on your encrypted drive (the Movies folder). "
            "Cover, description, actors and FSK rating are looked up by the file name, e.g. "
            "\"The Matrix (1999).mkv\". Both ways work only while this page is open.")
    FOLDERS = ("Video files: mkv, mp4, avi, mov, webm, … · subtitles named like the movie "
               "(e.g. \"The Matrix (1999).de.srt\") are used too")

    def __init__(self, root: Path, **kwargs):
        from gamingcrypt.emulation.upload_server import UploadServer

        kwargs.setdefault("server_factory", lambda folder, received: UploadServer(
            None, received, folders=lambda: {"movies": ("Movies", folder)}))
        super().__init__(Path(root), **kwargs)

    def prepare(self) -> None:
        self.paths.mkdir(parents=True, exist_ok=True)

    def share_folder(self) -> str:
        return str(self.paths)


class Playback(QObject):
    """Where the running movie is: asked every few seconds, kept in its .nfo."""

    changed = Signal(object)  # the movie, after it ended

    def __init__(self, parent: QObject | None = None, position=None, socket_path=None):
        super().__init__(parent)
        from gamingcrypt.movies import player

        self.position = position or player.position
        self.socket_path = socket_path or player.socket_path
        self.movie: Movie | None = None
        self.session: object | None = None
        self.lock = threading.Lock()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._polling = False

    def start(self, movie: Movie) -> None:
        self.movie, self.session = movie, object()
        self.timer.start(POLL_MS)

    def poll(self) -> None:
        movie, session, sock = self.movie, self.session, self.socket_path()
        if movie is None or self._polling:
            return
        self._polling = True

        def work():
            where = self.position(sock)
            if where is None:
                return
            with self.lock:
                if self.session is session:  # not ended meanwhile
                    library.set_progress(movie, *where)

        def done(_r=None) -> None:
            self._polling = False

        run_async(work, done, done, owner=self)

    def finish(self, appid: int) -> None:
        movie = self.movie
        if movie is None or movie.appid != appid:
            return
        self.timer.stop()
        self.movie = self.session = None

        def work():
            with self.lock:
                return library.finish_watching(movie)

        run_async(work, lambda _i: self.changed.emit(movie), lambda _e: self.changed.emit(movie), owner=self)


class MoviesTab(QStackedWidget):
    def __init__(self, root: str | Path = "", parent: QWidget | None = None, languages=("en", "de"),
                 lookup=None):
        super().__init__(parent)
        self.root = Path(root) if root else None
        self.languages = tuple(languages)
        if lookup is None:
            from gamingcrypt.movies.metadata import Lookup

            lookup = Lookup(languages=self.languages)
        self.lookup = lookup
        self.movies: list[Movie] = []
        self.player_launcher = None  # set by the app: (movie, start seconds) -> (ok, message)
        self.upload_page_factory = None  # tests: a stand-in upload page
        self.playback = Playback(self)
        self.playback.changed.connect(self.movie_changed)
        self._looking_up = False
        self._came_from: list = []
        self.home = MoviesHome(self)
        self.addWidget(self.home)
        self.reload()

    # navigation ----------------------------------------------------------------------
    def push(self, page: QWidget) -> None:
        self._came_from.append(self.window().focusWidget() if self.window() else None)
        self.addWidget(page)
        self.setCurrentWidget(page)

    def back(self) -> None:
        page = self.currentWidget()
        if page is self.home:
            return
        self.removeWidget(page)
        page.deleteLater()
        self.setCurrentIndex(self.count() - 1)
        previous = self._came_from.pop() if self._came_from else None
        if previous is not None and shiboken6.isValid(previous) and previous.isVisible():
            focus_and_reveal(previous)

    def gamepad_back(self) -> bool:
        if self.currentWidget() is self.home:
            return False
        self.back()
        return True

    def back_button(self) -> QWidget:
        button = big_button("‹ Back")
        button.clicked.connect(self.back)
        return button

    def open_movie(self, movie: Movie) -> None:
        page = MoviePage(self, movie)
        self.push(page)
        page.main_button.setFocus()

    def open_upload(self) -> None:
        if self.root is None:
            self.home.show_notice("Unlock your encrypted drive first", error=True)
            return
        page = (self.upload_page_factory or MovieUploadPage)(self.root)
        page.closed.connect(self._upload_closed)
        self.push(page)

    def _upload_closed(self) -> None:
        self.back()
        self.reload()  # new movies show up right away

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self.currentWidget() is self.home:
            self.reload()  # copied in over the network share meanwhile

    # data ----------------------------------------------------------------------------
    def reload(self) -> None:
        root = self.root
        if root is None:
            self.home.refresh()
            return

        def work():
            import os

            if not root.exists() and os.path.ismount(root.parent):
                root.mkdir(exist_ok=True)  # an unlocked drive: the folder to put movies in
            return library.scan(root)

        run_async(work, self._loaded, lambda _e: self._loaded([]), owner=self)

    def _loaded(self, movies: list[Movie]) -> None:
        self.movies = movies
        self.home.set_movies(movies)
        self.look_up_missing()

    def look_up_missing(self) -> None:
        """One movie after the other, in the background: cover and info from the internet."""
        if self._looking_up:
            return
        from gamingcrypt.movies import metadata

        now = time.time()
        waiting = [m for m in self.movies if metadata.needs_lookup(m, now)]
        if not waiting:
            if self.home.notice.text().startswith("Looking up"):
                self.home.show_notice("")
            return
        movie = waiting[0]
        self._looking_up = True
        self.home.show_notice(f"Looking up cover and info online… ({len(waiting)} to go)")

        def done(online: bool) -> None:
            self._looking_up = False
            if not online:
                self.home.show_notice("No internet - covers and info come when you're online again")
                return
            self.movie_changed(movie)
            self.look_up_missing()

        def failed(_exc) -> None:
            self._looking_up = False
            self.home.show_notice("")

        run_async(lambda: metadata.update(movie, self.lookup), done, failed, owner=self)

    def movie_changed(self, movie: Movie) -> None:
        """New info or watching state: the card, the open page, the filters."""
        info = library.read_info(movie.info_path)
        movie = next((m for m in self.movies if m.key == movie.key), movie)  # a reload may have made new ones
        movie.info = info
        self.home.update_movie(movie)
        self.home.update_genres(self.movies)
        self.home.refresh()
        for index in range(self.count()):
            page = self.widget(index)
            if isinstance(page, MoviePage) and page.movie.key == movie.key:
                page.update_movie(movie)

    def by_appid(self, appid: int) -> Movie | None:
        return next((m for m in self.movies if m.appid == appid), None)

    # playing ---------------------------------------------------------------------------
    def play(self, movie: Movie, from_start: bool = False) -> tuple[bool, str]:
        if self.player_launcher is None:
            return False, "The movie player isn't set up"
        start = 0 if from_start else movie.info.resume_at
        ok, message = self.player_launcher(movie, start)
        if ok:
            self.playback.start(movie)
        return ok, message

    def movie_ended(self, appid: int) -> None:
        self.playback.finish(appid)

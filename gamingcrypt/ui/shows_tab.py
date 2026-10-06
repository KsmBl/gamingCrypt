"""Shows tab: one card per show (not per episode), its page with seasons and episodes.

Built on the Movies tab (search, filters, sliding bar, upload, player, watched marks) - see
movies_tab. Smart bits: "Continue" plays the episode that comes next (or the one stopped in
the middle), an episode that ran to its end starts the following one, the card shows how
many episodes are still unwatched.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gamingcrypt.movies import library as movies
from gamingcrypt.shows import library
from gamingcrypt.shows.library import Episode, Show
from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import COVER_H, COVER_W, Cover, Tappable, card_margins, format_size, placeholder_cover
from gamingcrypt.ui.movies_tab import (MoviesHome, MoviesTab, MovieUploadPage, RemoveMovieConfirm, movie_cover)
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, enable_touch_scroll, set_status

THUMB_W, THUMB_H = 256, 144


def show_cover(show: Show, w: int, h: int) -> QPixmap:
    """The poster, with how many episodes are left (✓ when all are watched) and a bar how far."""
    pixmap = QPixmap(str(show.cover_path)) if show.cover_path.exists() else QPixmap()
    if pixmap.isNull():
        pixmap = placeholder_cover(show.title, w, h)
    else:
        scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
        pixmap = scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h)
    regular = show.regular
    left = show.unwatched
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    size = max(28, w // 6)
    rect = QRectF(w - size - 8, 8, size, size)
    if regular and left == 0:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SUCCESS))
        painter.drawEllipse(rect)
        label = "✓"
    elif regular and left < len(regular):  # started: how many are still to watch
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(rect.adjusted(-8 if left > 9 else 0, 0, 0, 0), size / 2, size / 2)
        label = str(left)
    else:
        label = ""
    if label:
        font = QFont()
        font.setPixelSize(int(size * 0.55))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect.adjusted(-8 if len(label) > 1 else 0, 0, 0, 0), Qt.AlignmentFlag.AlignCenter, label)
    if regular and 0 < left < len(regular):
        bar = max(6, h // 40)
        painter.fillRect(QRectF(0, h - bar, w, bar), QColor(0, 0, 0, 170))
        painter.fillRect(QRectF(0, h - bar, w * (len(regular) - left) / len(regular), bar), QColor(theme.ACCENT))
    painter.end()
    return pixmap


def show_facts(show: Show) -> str:
    """"2008-2013 · 5 seasons · 62 episodes · FSK 16"."""
    seasons = [s for s in show.seasons if s]
    count = len(show.episodes)
    parts = [library.years(show), f"{len(seasons)} season{'s' if len(seasons) != 1 else ''}" if seasons else "",
             f"{count} episode{'s' if count != 1 else ''}", show.info.fsk]
    return " · ".join(p for p in parts if p)


class ShowCard(Tappable):
    clicked = Signal(object)

    def __init__(self, show: Show, parent: QWidget | None = None):
        super().__init__(parent)
        self.show_item = show
        self.setObjectName("card")
        self.setFixedWidth(COVER_W + 20)
        layout = QVBoxLayout(self)
        card_margins(layout)
        layout.setSpacing(6)
        self.cover = Cover()
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
        self.tapped.connect(lambda: self.clicked.emit(self.show_item))
        self.update_item()

    @property
    def movie(self) -> Show:  # what the shared list code calls the card's item
        return self.show_item

    def set_item(self, show: Show) -> None:
        self.show_item = show
        self.update_item()

    def update_item(self) -> None:
        show = self.show_item
        self.title.setText(show.title)
        seasons = [s for s in show.seasons if s]
        self.meta.setText(" · ".join(p for p in (
            library.years(show),
            f"{len(seasons)} season{'s' if len(seasons) != 1 else ''}" if len(seasons) > 1
            else f"{len(show.episodes)} episode{'s' if len(show.episodes) != 1 else ''}") if p))
        self.cover.setPixmap(show_cover(show, COVER_W, COVER_H))


class ShowsHome(MoviesHome):
    ADD, SEARCH = "⬆  Add shows", "🔍  Search show, actor"
    NOUN, NOUNS = "show", "shows"
    EMPTY = ("No shows yet - add episodes with ⬆ Add shows (from a PC or phone in the same Wi-Fi), or put them "
             "into the Shows folder on your drive: one folder per show, or named like \"Show S01E02.mkv\"")

    def sorts(self) -> dict:
        return library.SORTS

    def make_card(self, item):
        card = ShowCard(item)
        card.clicked.connect(self.tab.open_show)
        return card

    def filtered(self, items, query, watch_state, genre, max_age):
        return library.sort_shows(library.filter_shows(items, query, watch_state, genre, max_age),
                                  self.sort_combo.currentData() or "title")

    def all_genres(self, items) -> list[str]:
        return library.genres(items)


class EpisodeRow(Tappable):
    """One episode: its picture (✓ / how far), number and title, length, air date, summary."""

    play_requested = Signal(object)
    watched_toggled = Signal(object)

    def __init__(self, episode: Episode, parent: QWidget | None = None):
        super().__init__(parent)
        self.episode = episode
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 16, 12)
        row.setSpacing(18)
        self.thumb = Cover()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        row.addWidget(self.thumb, alignment=Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.name = QLabel()
        self.name.setObjectName("cardTitle")
        self.name.setWordWrap(True)
        text.addWidget(self.name)
        self.meta = QLabel()
        self.meta.setObjectName("cardMeta")
        text.addWidget(self.meta)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("cardMeta")
        self.summary.setMaximumHeight(66)  # three lines - the page stays a list
        text.addWidget(self.summary)
        text.addStretch()
        row.addLayout(text, 1)
        self.watched_button = big_button("")
        self.watched_button.clicked.connect(lambda: self.watched_toggled.emit(self.episode))
        row.addWidget(self.watched_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.tapped.connect(lambda: self.play_requested.emit(self.episode))
        self.update_episode()

    def update_episode(self, episode: Episode | None = None) -> None:
        episode = self.episode = episode or self.episode
        info = episode.info
        self.thumb.setPixmap(movie_cover(episode, THUMB_W, THUMB_H))
        self.name.setText(f"{episode.number}. {episode.name}")
        aired = ""
        if info.aired:
            from datetime import date

            try:
                aired = date.fromisoformat(info.aired).strftime("%d %b %Y")
            except ValueError:
                aired = info.aired
        stopped = f"stopped at {movies.format_time(info.resume_at)}" if info.resume_at else ""
        self.meta.setText(" · ".join(p for p in (episode.code, movies.format_length(info.minutes), aired, stopped)
                                     if p))
        self.summary.setText(info.plot)
        self.summary.setVisible(bool(info.plot))
        self.watched_button.setText("✓ Watched" if info.watched else "Mark watched")
        self.watched_button.setObjectName("primary" if info.watched else "")
        self.watched_button.style().unpolish(self.watched_button)
        self.watched_button.style().polish(self.watched_button)


class ShowPage(QWidget):
    """The show: poster, facts, Continue, description, cast - and its seasons' episodes."""

    def __init__(self, tab: "ShowsTab", show: Show, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.show_item = tab, show
        self.confirm: RemoveMovieConfirm | None = None
        self.season_number: int | None = None
        self.rows: dict[str, EpisodeRow] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        top.addStretch()
        layout.addLayout(top)
        content = QWidget()
        page = QVBoxLayout(content)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(18)
        body = QHBoxLayout()
        body.setSpacing(36)
        self.cover = Cover()
        self.cover.setFixedSize(300, 450)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(14)  # not the 36 px between cover and text it would take over
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
        self.progress.setWordWrap(True)
        info.addWidget(self.progress)
        self.actions = QWidget()
        actions = FlowLayout(self.actions, spacing=16)
        actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)  # only its rows
        self.main_button = big_button("", "primary")
        self.main_button.setMinimumWidth(220)
        self.main_button.clicked.connect(self.play_next)
        actions.addWidget(self.main_button)
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
        self.files_label = QLabel()
        self.files_label.setObjectName("cardMeta")
        self.files_label.setWordWrap(True)
        self.options_layout.addWidget(self.files_label)
        self.remove_button = big_button("🗑 Remove show", "danger")
        self.remove_button.clicked.connect(self.ask_remove)
        self.options_layout.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_panel.hide()
        info.addWidget(self.options_panel)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()  # no empty line under the buttons
        info.addWidget(self.status)
        self.plot = QLabel()
        self.plot.setWordWrap(True)
        info.addWidget(self.plot)
        self.people = QLabel()
        self.people.setObjectName("detailMeta")
        self.people.setWordWrap(True)
        info.addWidget(self.people)
        info.addStretch()
        body.addLayout(info, 1)
        page.addLayout(body)
        # seasons and their episodes, the whole width
        self.seasons = QWidget()
        self.season_row = FlowLayout(self.seasons, spacing=12)
        self.season_row.setContentsMargins(0, 0, 0, 0)
        page.addWidget(self.seasons)
        self.episode_list = QVBoxLayout()
        self.episode_list.setSpacing(12)
        page.addLayout(self.episode_list)
        page.addStretch()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        enable_touch_scroll(self.scroll)
        layout.addWidget(self.scroll, 1)
        self.season_buttons: dict[int, object] = {}
        self.set_show(show)

    # the show ---------------------------------------------------------------------------
    def set_show(self, show: Show) -> None:
        self.show_item = show
        info = show.info
        self.title.setText(show.title)
        self.cover.setPixmap(show_cover(show, 300, 450))
        self.facts.setText("\n".join(p for p in (show_facts(show), ", ".join(info.genres)) if p))
        regular = show.regular
        done = len(regular) - show.unwatched
        nxt = library.next_up(show)
        if done and nxt is not None:
            self.progress.setText(f"{done} of {len(regular)} watched · next: {nxt.code} {nxt.name}")
        elif not regular or done == 0:
            self.progress.setText("")
        else:
            self.progress.setText("✓ All watched")
        self.progress.setVisible(bool(self.progress.text()))
        if nxt is None:
            self.main_button.setText("▶  Watch again from the start")
        elif nxt.info.resume_at:
            self.main_button.setText(f"▶  Continue {nxt.code} at {movies.format_time(nxt.info.resume_at)}")
        elif done:
            self.main_button.setText(f"▶  Continue with {nxt.code}")
        else:
            self.main_button.setText(f"▶  Play {nxt.code}")
        self.watched_button.setText("Mark as unwatched" if regular and not show.unwatched
                                    else "✓ Mark all as watched")
        self.actions.layout().invalidate()
        self.plot.setText(info.plot or "No description found.")
        cast = "\n".join(f"{name}  ·  {role}" if role else name for name, role in info.actors)
        self.people.setText(f"Cast:\n{cast}" if cast else "")
        self.people.setVisible(bool(cast))
        where = show.folder.name if show.folder is not None else "the Shows folder"
        self.files_label.setText(f"{len(show.episodes)} episode files in {where}  ·  {format_size(show.size)}")
        self._seasons(nxt)

    def _seasons(self, nxt: Episode | None) -> None:
        show = self.show_item
        for button in self.season_row.take_all():
            button.deleteLater()
        self.season_buttons = {}
        for number in show.seasons:
            button = big_button("Specials" if number == 0 else f"Season {number}", choice=True)
            button.clicked.connect(lambda _=False, n=number: self.show_season(n))
            self.season_row.addWidget(button)
            self.season_buttons[number] = button
        self.seasons.setVisible(len(show.seasons) > 1)
        wanted = self.season_number if self.season_number in show.seasons else None
        if wanted is None:
            wanted = nxt.season if nxt is not None else (show.seasons[0] if show.seasons else None)
        if wanted is not None:
            self.show_season(wanted)

    def show_season(self, number: int) -> None:
        self.season_number = number
        for n, button in self.season_buttons.items():
            button.setChecked(n == number)
        while self.episode_list.count():
            item = self.episode_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = {}
        for episode in self.show_item.season(number):
            row = EpisodeRow(episode)
            row.play_requested.connect(lambda e: self.play(e))
            row.watched_toggled.connect(self.toggle_episode_watched)
            self.episode_list.addWidget(row)
            self.rows[episode.key] = row

    # actions ----------------------------------------------------------------------------
    def play_next(self) -> None:
        nxt = library.next_up(self.show_item)
        if nxt is None and self.show_item.regular:
            self.play(self.show_item.regular[0], from_start=True)
        elif nxt is not None:
            self.play(nxt)

    def play(self, episode: Episode, from_start: bool = False) -> None:
        ok, message = self.tab.play(episode, from_start)
        self.say("" if ok else message, error=not ok)

    def toggle_watched(self) -> None:
        show, watched = self.show_item, bool(self.show_item.unwatched)
        run_async(lambda: library.set_show_watched(show, watched), lambda _r: self.tab.reload(),
                  lambda exc: self.say(f"Could not save it: {exc}", error=True), owner=self)

    def toggle_episode_watched(self, episode: Episode) -> None:
        watched = not episode.info.watched
        run_async(lambda: movies.set_watched(episode, watched), lambda _r: self.tab.reload(),
                  lambda exc: self.say(f"Could not save it: {exc}", error=True), owner=self)

    def toggle_options(self, visible: bool) -> None:
        self.options_panel.setVisible(visible)
        if visible:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.options_panel, 0, 20))
        else:
            self.close_confirm()

    def ask_remove(self) -> None:
        if self.confirm is not None:
            return
        show = self.show_item
        files = library.show_files(show)
        question = (f"Really remove {show.title}?\nAll {len(show.episodes)} episodes with their pictures, info and "
                    f"subtitles ({len(files)} files, {format_size(library.removal_size(show))}) are deleted "
                    "from the drive.")
        self.confirm = RemoveMovieConfirm(show, show.root, question=question, work=lambda: library.remove(show))
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
        if failed and appid in self.show_item.appids:
            self.say("The player didn't start", error=True)

    def say(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)
        self.status.setVisible(bool(text))


class ShowUploadPage(MovieUploadPage):
    TITLE = "Add shows"
    HINT = ("Episodes from a PC or phone in the same Wi-Fi - they land on your encrypted drive (the Shows folder). "
            "Name them like \"Breaking Bad S01E02.mkv\" (or 1x02): they're put together into their show, and "
            "pictures, descriptions and cast are looked up. Both ways work only while this page is open.")
    FOLDERS = ("In the browser: \"Shows\" (sorted by the names) or the folder of a show you already have · "
               "the network share is the Shows folder: one folder per show, \"Season 1\" folders inside work too")

    def __init__(self, root: Path, **kwargs):
        from gamingcrypt.emulation.upload_server import UploadServer

        kwargs.setdefault("server_factory", lambda folder, received: UploadServer(
            None, received, folders=lambda: upload_folders(folder)))
        super().__init__(Path(root), **kwargs)


def upload_folders(root: Path) -> dict[str, tuple[str, Path]]:
    """The Shows folder, and every show's own folder."""
    found = {"shows": ("Shows (sorted by the names in the files)", root)}
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        folders = []
    found.update({f"shows/{p.name}": (f"Show: {p.name}", p) for p in folders})
    return found


class ShowsTab(MoviesTab):
    HOME = ShowsHome
    UPLOAD = ShowUploadPage
    NOTICE_LOOKUP = "Looking up shows online… ({count} to go)"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.playback.played_to_the_end.connect(self.play_following)

    def make_lookup(self):
        from gamingcrypt.shows.metadata import ShowLookup

        return ShowLookup(languages=self.languages)

    def scan(self, root: Path) -> list:
        return library.scan(root)

    def needs_lookup(self, item, now: float) -> bool:
        from gamingcrypt.shows import metadata

        return metadata.needs_lookup(item, now)

    def update_item(self, item) -> bool:
        from gamingcrypt.shows import metadata

        return metadata.update(item, self.lookup)

    @property
    def shows(self) -> list[Show]:
        return self.items

    # pages ------------------------------------------------------------------------------
    def open_show(self, show: Show) -> None:
        page = ShowPage(self, show)
        self.push(page)
        page.main_button.setFocus()

    open_movie = open_show

    def _loaded(self, items: list) -> None:
        super()._loaded(items)
        for index in range(self.count()):  # what's open shows the new state
            page = self.widget(index)
            if isinstance(page, ShowPage):
                show = next((s for s in items if s.key == page.show_item.key), None)
                if show is not None:
                    page.set_show(show)

    def looked_up(self, item) -> None:
        self.reload()  # the show and its episodes are new: read them again (looks up the next one after)

    def movie_changed(self, episode) -> None:
        self.reload()  # watched / stopped at: card, page and filters

    # playing ----------------------------------------------------------------------------
    def by_appid(self, appid: int) -> Episode | None:
        return next((e for s in self.items for e in s.episodes if e.appid == appid), None)

    def show_of(self, episode: Episode) -> Show | None:
        return next((s for s in self.items if any(e.key == episode.key for e in s.episodes)), None)

    def play_following(self, episode: Episode) -> None:
        """It ran to its end: the next episode, like a TV."""
        show = self.show_of(episode)
        nxt = library.following(show, episode) if show is not None else None
        if nxt is not None:
            self.play(nxt, from_start=not nxt.info.resume_at)

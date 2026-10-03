"""Search the Steam store and install new games."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.steam.webapi import StoreItem, format_price
from gamingcrypt.ui.game_widgets import load_cover, placeholder_cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import KeyboardFocusFilter, OnScreenKeyboard, big_button, enable_touch_scroll, set_status

ROW_COVER_W, ROW_COVER_H = 80, 120


def price_text(item: StoreItem) -> str:
    text = format_price(item.price_cents, item.currency)
    if item.discounted:
        percent = round(100 - item.price_cents * 100 / item.original_cents)
        text += f"  (-{percent}%)"
    return text


class StoreRow(QFrame):
    def __init__(self, page: "StorePage", item: StoreItem):
        super().__init__()
        self.page = page
        self.item = item
        self.setObjectName("card")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(18)
        cover = QLabel()
        cover.setFixedSize(ROW_COVER_W, ROW_COVER_H)
        cover.setPixmap(placeholder_cover(item.name, ROW_COVER_W, ROW_COVER_H))
        load_cover(page.service, item.appid, cover, ROW_COVER_W, ROW_COVER_H)
        layout.addWidget(cover)
        text = QVBoxLayout()
        name = QLabel(item.name)
        name.setObjectName("cardTitle")
        name.setWordWrap(True)
        text.addWidget(name)
        self.price = QLabel(price_text(item))
        self.price.setObjectName("cardMeta")
        text.addWidget(self.price)
        layout.addLayout(text, 1)
        self.action, label, style = page.action_for(item)
        self.button = big_button(label, style)
        self.button.setMinimumWidth(220)
        self.button.clicked.connect(lambda: page.run_action(self.item, self.action))
        layout.addWidget(self.button)


class StorePage(QWidget):
    def __init__(self, tab, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab = tab
        self.service = tab.service
        self.rows: list[StoreRow] = []
        self.searching = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel("Steam Store")
        title.setObjectName("title")
        top.addWidget(title)
        top.addStretch()
        layout.addLayout(top)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search the Steam store")
        self.search.returnPressed.connect(self.do_search)
        search_row.addWidget(self.search, 1)
        search_button = big_button("Search", "primary")
        search_button.clicked.connect(self.do_search)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        results = QWidget()
        self.results_layout = QVBoxLayout(results)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.addStretch()
        scroll.setWidget(results)
        layout.addWidget(scroll, 1)

        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.do_search)
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)

    # actions ----------------------------------------------------------------
    def action_for(self, item: StoreItem) -> tuple[str, str, str]:
        owned = self.tab.games.get(item.appid)
        if owned is not None and owned.installed:
            return "play", "▶  Play", "primary"
        if owned is not None or item.price_cents == 0:
            return "install", "⬇  Install", "primary"
        return "buy", "Buy in Steam", ""

    def run_action(self, item: StoreItem, action: str) -> None:
        client = self.service.client
        if action == "play":
            ok, message = client.play(item.appid), f"Starting {item.name}…"
        elif action == "install":
            ok, message = client.install(item.appid), f"Installing {item.name} - Steam takes over"
        else:
            ok, message = client.open_store(item.appid), "Opened the store page in Steam"
        set_status(self.status, message if ok else "Could not reach Steam - is it installed?", error=not ok)

    # search -----------------------------------------------------------------
    def do_search(self) -> None:
        term = self.search.text().strip()
        if not term or self.searching:
            return
        self.keyboard.hide()
        self.searching = True
        set_status(self.status, f'Searching for "{term}"…')
        run_async(lambda: self.service.search_store(term), self._results, self._failed, owner=self)

    def _clear(self) -> None:
        for row in self.rows:
            self.results_layout.removeWidget(row)
            row.deleteLater()
        self.rows = []

    def _results(self, items: list[StoreItem]) -> None:
        self.searching = False
        self._clear()
        for item in items:
            row = StoreRow(self, item)
            self.rows.append(row)
            self.results_layout.insertWidget(self.results_layout.count() - 1, row)
        set_status(self.status, "" if items else "Nothing found")

    def _failed(self, exc: Exception) -> None:
        self.searching = False
        set_status(self.status, f"Store not reachable: {exc}", error=True)

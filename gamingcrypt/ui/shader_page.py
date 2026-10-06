"""Shaders of an emulated system (its page: ✨ Shaders) or of one game (its Options): tick and
untick them, the preview next to the list shows the combination on a picture of the game."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gamingcrypt.emulation import shaders
from gamingcrypt.emulation.systems import SHORT, System
from gamingcrypt.ui import shader_preview
from gamingcrypt.ui.widgets import big_button, enable_touch_scroll, set_status

PREVIEW = QSize(600, 450)  # at most - smaller when the screen has less room


class ShaderRow(QPushButton):
    """One shader: ☑ / ☐ and its name; says which one it is when the controller is on it."""

    focused = Signal(str)

    def __init__(self, shader: shaders.Shader, parent: QWidget | None = None):
        super().__init__(parent)
        self.shader = shader
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(self._text)
        self._text(False)

    def _text(self, on: bool) -> None:
        self.setText(f"{'☑' if on else '☐'}  {self.shader.name}")

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().focusInEvent(event)
        self.focused.emit(self.shader.id)


class ShaderPage(QWidget):
    """system: the combination every game of the system gets. game (default = the system's): the
    game's own one or the system's."""

    changed = Signal()

    def __init__(self, tab, system: System, picture: QImage, chosen: list[str] | None,
                 save: Callable[[list[str] | None], None], default: list[str] | None = None,
                 game_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.system, self.picture, self.save = system, picture, save
        self.for_game = default is not None
        self.default = shaders.clean(default or [])
        self.own = not self.for_game or chosen is not None
        self.ids = shaders.clean(chosen if chosen is not None else self.default)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(f"Shaders · {game_name or system.name}")
        title.setObjectName("title")
        top.addWidget(title, 1)
        self.clear_button = big_button("Untick all")
        self.clear_button.clicked.connect(self.clear)
        top.addWidget(self.clear_button)
        layout.addLayout(top)
        short = SHORT.get(system.id, system.name)
        self.same_button = self.own_button = None
        if self.for_game:
            choice = QHBoxLayout()
            self.same_button = big_button(f"Same as {short}", choice=True)
            self.same_button.clicked.connect(lambda: self.use_own(False))
            choice.addWidget(self.same_button)
            self.own_button = big_button("Own for this game", choice=True)
            self.own_button.clicked.connect(lambda: self.use_own(True))
            choice.addWidget(self.own_button)
            choice.addStretch()
            layout.addLayout(choice)
        body = QHBoxLayout()
        body.setSpacing(30)
        listing = QWidget()
        rows = QVBoxLayout(listing)
        rows.setContentsMargins(0, 0, 12, 0)
        rows.setSpacing(8)
        self.rows: dict[str, ShaderRow] = {}
        for group, heading in shaders.GROUPS.items():
            label = QLabel(heading)
            label.setObjectName("section")
            rows.addWidget(label)
            if group == "upscale":
                hint = QLabel("Bigger pixel art, smoothed or sharp - not together with a screen effect")
                hint.setObjectName("cardMeta")
                hint.setWordWrap(True)
                rows.addWidget(hint)
            elif group == "screen":
                hint = QLabel("The look of an old TV or a handheld's screen - not together with an upscaler")
                hint.setObjectName("cardMeta")
                hint.setWordWrap(True)
                rows.addWidget(hint)
            for shader in (s for s in shaders.SHADERS if s.group == group):
                row = ShaderRow(shader)
                row.clicked.connect(lambda on, i=shader.id: self.tick(i, on))
                row.focused.connect(self.explain)
                rows.addWidget(row)
                self.rows[shader.id] = row
        rows.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(listing)
        scroll.setMinimumWidth(420)
        enable_touch_scroll(scroll)
        body.addWidget(scroll, 1)
        side = QVBoxLayout()
        side.setSpacing(10)
        self.preview = QLabel()
        self.preview.setMinimumSize(320, 240)
        self.preview.setMaximumSize(PREVIEW)
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)  # not the picture's size
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.preview, 1)
        self.summary = QLabel("")
        self.summary.setObjectName("cardTitle")
        self.summary.setWordWrap(True)
        side.addWidget(self.summary)
        self.about = QLabel("")
        self.about.setObjectName("cardMeta")
        self.about.setWordWrap(True)
        side.addWidget(self.about)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        body.addLayout(side, 1)
        layout.addLayout(body, 1)
        if shaders.folder() is None:
            set_status(self.status, shaders.MISSING, error=True)
        else:
            set_status(self.status, "The preview shows roughly how it looks - the game shows it exactly")
        self.refresh()

    # what's chosen ----------------------------------------------------------------------------
    def tick(self, shader_id: str, on: bool) -> None:
        if not self.own:
            self.own = True  # changing the system's: from now on the game's own
        self.ids = shaders.toggle(self.ids, shader_id, on)
        self.store()
        self.explain(shader_id)

    def use_own(self, own: bool) -> None:
        self.own = own
        if not own:
            self.ids = list(self.default)
        self.store()

    def clear(self) -> None:
        self.own = True
        self.ids = []
        self.store()

    def store(self) -> None:
        self.save(self.ids if self.own or not self.for_game else None)
        self.refresh()
        self.changed.emit()

    # showing it --------------------------------------------------------------------------------
    def refresh(self) -> None:
        for shader_id, row in self.rows.items():
            row.blockSignals(True)
            row.setChecked(shader_id in self.ids)
            row.blockSignals(False)
            row._text(shader_id in self.ids)
        if self.same_button is not None:
            self.same_button.setChecked(not self.own)
            self.own_button.setChecked(self.own)
            self.same_button.setText(f"Same as {SHORT.get(self.system.id, self.system.name)}: "
                                     f"{shaders.describe(self.default)}")
        self.summary.setText(shaders.describe(self.ids) if self.ids else "No shaders - the picture as it is")
        self.draw_preview()

    def draw_preview(self) -> None:
        size = self.preview.size().boundedTo(PREVIEW).expandedTo(QSize(320, 240))
        self._drawn = (size, tuple(self.ids))
        self.preview.setPixmap(QPixmap.fromImage(shader_preview.render(self.picture, self.ids, size)))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        from PySide6.QtCore import QTimer

        # after the layout gave the preview its room
        QTimer.singleShot(0, lambda: self._drawn != (self.preview.size().boundedTo(PREVIEW).expandedTo(
            QSize(320, 240)), tuple(self.ids)) and self.draw_preview())

    def explain(self, shader_id: str) -> None:
        shader = shaders.BY_ID[shader_id]
        note = " - one upscaler or screen effect at a time" if shader.final else ""
        self.about.setText(f"{shader.name}: {shader.description}{note}")

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        from gamingcrypt.ui.widgets import settle_focus

        first = self.own_button if self.for_game and self.own else self.same_button
        settle_focus(self, first or next(iter(self.rows.values())))

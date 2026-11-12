"""Y on a page with a search field (the games, a library, the movies, the store): its keyboard opens
- what's looked for is typed right away, from wherever the highlight is. On a game's or movie's own
page (no search there) Y keeps choosing another picture (GamesTab / MoviesTab.gamepad_north)."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QLineEdit, QWidget


def search_on_page(widget: QWidget | None) -> QLineEdit | None:
    """The search field of the page the widget is on - None where there's none."""
    node = widget
    while node is not None:
        edit = getattr(node, "search", None)
        if isinstance(edit, QLineEdit) and edit.isVisible() and edit.isEnabled():
            return edit
        node = node.parentWidget()
    return None


def open_search(edit: QLineEdit) -> None:
    """Its keyboard, with the highlight on the first key (as A on the field does)."""
    from gamingcrypt.ui.keyboard_overlay import page_keyboard
    from gamingcrypt.ui.widgets import focus_and_reveal

    keyboard = page_keyboard(edit)
    keys = [k for k in keyboard.findChildren(QAbstractButton) if k.isVisible()] if keyboard is not None else []
    focus_and_reveal(keys[0] if keys else edit)

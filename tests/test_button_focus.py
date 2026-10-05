"""The controller highlight (focus frame) must not cut off a button's text - it did
on tight buttons like "Details" or "⚙ Options" ("Detail")."""

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QWidget

from gamingcrypt.ui import theme
from gamingcrypt.ui.widgets import big_button

FRAME = 6  # skip the frame itself when looking for text


def text_pixels(button) -> int:
    image = button.grab().toImage()
    count = 0
    for y in range(FRAME, image.height() - FRAME):
        for x in range(FRAME, image.width() - FRAME):
            if QColor(image.pixel(x, y)).lightness() > 200:
                count += 1
    return count


@pytest.mark.parametrize("text,name,checkable", [
    ("Details", "", False),
    ("⚙ Options", "", True),
    ("Cancel", "", False),
    ("Keep playing", "", False),
    ("▶  Play", "primary", False),
    ("✕  Force quit", "danger", False),
])
def test_focus_frame_keeps_the_text_whole(qtbot, text, name, checkable):
    host = QWidget()
    host.setStyleSheet(theme.STYLESHEET)
    qtbot.addWidget(host)
    row = QHBoxLayout(host)
    button = big_button(text, name, checkable=checkable)
    other = big_button("x")
    row.addWidget(button)
    row.addWidget(other)
    row.addStretch()
    host.show()
    qtbot.waitExposed(host)
    other.setFocus()
    qtbot.waitUntil(other.hasFocus)
    size, unfocused = button.size(), text_pixels(button)
    button.setFocus()
    qtbot.waitUntil(button.hasFocus)
    assert button.size() == size  # the highlight doesn't move anything around
    assert text_pixels(button) >= unfocused * 0.97, "the focus frame cuts the text off"

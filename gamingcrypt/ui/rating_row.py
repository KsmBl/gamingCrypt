"""A game's Options -> "Age rating": the admin's own rating for it, where there's none (or a
wrong one) - what users with an age get to see goes by it (gamingcrypt/ratings.py)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from gamingcrypt import ratings
from gamingcrypt.ui.combo import ComboBox


def rating_row(tab, game) -> QWidget | None:
    """None: nobody to rate for (no user has an age, or it isn't the admin looking)."""
    if not getattr(tab, "rate_games", False):
        return None
    row = QWidget()
    row.setObjectName("menuRow")
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    caption = QLabel("Age rating")
    caption.setObjectName("cardMeta")
    line.addWidget(caption)
    combo = ComboBox()
    found = ratings.automatic(game, tab)
    combo.addItem(f"Automatic: from {found}" if found is not None else "Automatic: not rated - hidden from users "
                                                                      "with an age", None)
    for step in ratings.STEPS:
        combo.addItem(f"From {step}", step)
    rated = getattr(tab, "rating_profiles", None) or tab.profiles
    own = ratings.manual(rated.get(game.appid))
    combo.setCurrentIndex(max(0, combo.findData(own)))
    combo.currentIndexChanged.connect(
        lambda _i: rated.set(game.appid, ratings.MANUAL,
                             None if combo.currentData() is None else str(combo.currentData())))
    line.addWidget(combo, 1)
    row.combo = combo
    return row

"""The "Graphics" choice in a game's Options: automatic clock, or full speed while it runs
(fewer micro-stutters, a bit more battery - system/gpu_speed). AMD graphics only."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gamingcrypt.system import gpu_speed
from gamingcrypt.ui.combo import ComboBox

CAPTION = "Graphics"
CHOICES = (("Automatic speed", False), ("Full speed (smoother)", True))


def gpu_combo(profiles, appid: int, said: Callable[[str], None] | None = None,
              sys_root: Path = Path("/sys")) -> ComboBox | None:
    """None on graphics that have no such switch."""
    if not gpu_speed.available(sys_root):
        return None
    combo = ComboBox()
    for text, full in CHOICES:
        combo.addItem(text, full)
    combo.setCurrentIndex(1 if profiles.get(appid).get(gpu_speed.PROFILE_KEY) else 0)

    def chosen(_index: int) -> None:
        full = bool(combo.currentData())
        try:
            profiles.set(appid, gpu_speed.PROFILE_KEY, True if full else None)
        except OSError as exc:
            if said:
                said(f"Could not save: {exc}")
            return
        if said:
            said("Graphics at full speed while it runs - from the next start" if full
                 else "Graphics speed automatic again - from the next start")

    combo.currentIndexChanged.connect(chosen)
    return combo

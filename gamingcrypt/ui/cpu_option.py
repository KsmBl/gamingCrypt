"""The "CPU cores" choice in a Windows game's Options: all cores, or the quiet ones
(system/cpu_cores - fewer micro-stutters in games that tie their main thread to the first core)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from gamingcrypt.system import cpu_cores
from gamingcrypt.ui.combo import ComboBox

CAPTION = "CPU cores"
CHOICES = (("All cores", False), ("Quiet cores (smoother)", True))


def cpu_combo(profiles, appid: int, said: Callable[[str], None] | None = None,
              sys_root: Path = Path("/sys")) -> ComboBox | None:
    """None on a CPU with too few cores for it."""
    if not cpu_cores.available(sys_root):
        return None
    combo = ComboBox()
    for text, quiet in CHOICES:
        combo.addItem(text, quiet)
    combo.setCurrentIndex(1 if profiles.get(appid).get(cpu_cores.PROFILE_KEY) else 0)

    def chosen(_index: int) -> None:
        quiet = bool(combo.currentData())
        try:
            profiles.set(appid, cpu_cores.PROFILE_KEY, True if quiet else None)
        except OSError as exc:
            if said:
                said(f"Could not save: {exc}")
            return
        if said:
            said("The game stays off the busy first core - from the next start" if quiet
                 else "The game uses all cores again - from the next start")

    combo.currentIndexChanged.connect(chosen)
    return combo

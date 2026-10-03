from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SteamGame:
    appid: int
    name: str
    installed: bool = False
    install_dir: str = ""
    library_path: str = ""
    size_on_disk: int = 0
    # Unix timestamps (0/None = unknown)
    last_updated: int | None = None
    last_played: int | None = None
    release_date: int | None = None
    playtime_minutes: int = 0
    # Price in cents of the store currency; 0 = free, None = unknown / not sold
    price_cents: int | None = None
    currency: str = ""
    update_pending: bool = False
    description: str = ""

    @property
    def playtime_hours(self) -> float:
        return round(self.playtime_minutes / 60, 1)

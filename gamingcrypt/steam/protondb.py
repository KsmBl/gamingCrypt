"""How well a game runs on Linux, from ProtonDB's public summaries (cached for a week)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import requests

URL = "https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
MAX_AGE_S = 7 * 24 * 3600
TIERS = {"platinum": "Platinum", "gold": "Gold", "silver": "Silver", "bronze": "Bronze", "borked": "Borked",
         "native": "Native"}
ICONS = {"platinum": "★", "gold": "●", "silver": "◐", "bronze": "◔", "borked": "✕", "native": "🐧"}


def label(tier: str | None) -> str:
    if not tier:
        return ""
    return f"ProtonDB: {ICONS.get(tier, '')} {TIERS.get(tier, tier.capitalize())}".replace("  ", " ")


class ProtonDB:
    def __init__(self, cache_dir: Path, get: Callable | None = None, now: Callable[[], float] = time.time):
        self.path = Path(cache_dir) / "protondb.json"
        self.get = get or (lambda url: requests.get(url, timeout=10))
        self.now = now

    def _cache(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def cached(self, appid: int) -> str | None:
        """Known tier ("" = ProtonDB has no reports) without asking the network, or None."""
        entry = self._cache().get(str(appid))
        if not isinstance(entry, dict) or self.now() - entry.get("at", 0) > MAX_AGE_S:
            return None
        return entry.get("tier", "")

    def tier(self, appid: int) -> str:
        known = self.cached(appid)
        if known is not None:
            return known
        tier = ""
        try:
            response = self.get(URL.format(appid=int(appid)))
            if response.status_code == 200:
                data = response.json()
                tier = str(data.get("tier") or data.get("trendingTier") or "").lower()
            elif response.status_code != 404:  # 404 = no reports; other errors: ask again later
                return ""
        except (requests.RequestException, ValueError, AttributeError):
            return ""  # offline: nothing to show, nothing cached
        cache = self._cache()
        cache[str(appid)] = {"tier": tier, "at": self.now()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(cache))
        except OSError:
            pass
        return tier

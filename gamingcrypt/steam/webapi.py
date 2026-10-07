"""Steam Web API (owned games, needs a key) and the public store endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import re

import requests

API = "https://api.steampowered.com"
STORE = "https://store.steampowered.com/api"
TIMEOUT = 15

DATE_FORMATS = ["%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y", "%b %Y", "%B %Y", "%Y"]


class SteamAPIError(RuntimeError):
    pass


@dataclass
class StoreItem:
    appid: int
    name: str
    price_cents: int | None
    currency: str
    image_url: str
    original_cents: int | None = None

    @property
    def discounted(self) -> bool:
        return self.original_cents is not None and self.price_cents is not None and self.price_cents < self.original_cents


def parse_release_date(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return int(dt.timestamp())
    return None


STORAGE_RE = re.compile(
    r"(?:Storage|Hard Drive|Hard Disk(?: Space)?|Disk Space|HDD)\s*:\s*([\d]+(?:[.,]\d+)?)\s*(TB|GB|MB)",
    re.I,
)
UNITS = {"TB": 1024**4, "GB": 1024**3, "MB": 1024**2}


def parse_storage(*requirements) -> int | None:
    """Disk space from the store's system requirements (Linux first, then Windows).

    Steam's store API has no size field, but every game states "Storage: 20 GB available space".
    """
    for req in requirements:
        if not isinstance(req, dict):
            continue  # Steam sends [] when a platform has no requirements
        for part in ("minimum", "recommended"):
            text = re.sub(r"<[^>]+>", " ", str(req.get(part) or ""))
            match = STORAGE_RE.search(text)
            if match:
                return int(float(match.group(1).replace(",", ".")) * UNITS[match.group(2).upper()])
    return None


def format_price(cents: int | None, currency: str = "") -> str:
    if cents is None:
        return "-"
    if cents == 0:
        return "Free"
    symbol = {"EUR": "€", "USD": "$", "GBP": "£"}.get(currency, currency + " " if currency else "")
    value = f"{cents / 100:.2f}"
    return f"{value} €" if symbol == "€" else f"{symbol}{value}"


class SteamWebAPI:
    def __init__(self, api_key: str = "", steam_id: str = "", country: str = "de",
                 language: str = "english", session: Any = None):
        self.api_key = api_key
        self.steam_id = steam_id
        self.country = country
        self.language = language
        self.session = session or requests.Session()

    @property
    def can_list_owned(self) -> bool:
        return bool(self.api_key and self.steam_id)

    def _get(self, url: str, params: dict) -> Any:
        try:
            response = self.session.get(url, params=params, timeout=TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SteamAPIError(str(exc)) from exc

    def owned_games(self) -> list[dict]:
        if not self.can_list_owned:
            raise SteamAPIError("Steam API key / SteamID not configured")
        data = self._get(f"{API}/IPlayerService/GetOwnedGames/v1/", {
            "key": self.api_key,
            "steamid": self.steam_id,
            "include_appinfo": 1,
            "include_played_free_games": 1,
            "format": "json",
        })
        games = (data or {}).get("response", {}).get("games", [])
        return [
            {
                "appid": int(g["appid"]),
                "name": g.get("name", f"App {g['appid']}"),
                "playtime": int(g.get("playtime_forever", 0)),
                "last_played": int(g.get("rtime_last_played", 0)),
            }
            for g in games if "appid" in g
        ]

    def app_details(self, appid: int) -> dict:
        data = self._get(f"{STORE}/appdetails", {"appids": appid, "cc": self.country, "l": self.language})
        entry = (data or {}).get(str(appid), {})
        if not entry.get("success"):
            return {}
        d = entry.get("data", {})
        price = d.get("price_overview") or {}
        release = d.get("release_date") or {}
        return {
            "name": d.get("name", ""),
            "is_free": bool(d.get("is_free")),
            "price_cents": 0 if d.get("is_free") else price.get("final"),
            "currency": price.get("currency", ""),
            "release_date": None if release.get("coming_soon") else parse_release_date(release.get("date")),
            "description": d.get("short_description", ""),
            "header_image": d.get("header_image", ""),
            "storage_bytes": parse_storage(d.get("linux_requirements"), d.get("pc_requirements")),
            "genres": [g["description"] for g in d.get("genres") or [] if g.get("description")],
        }

    def latest_news_date(self, appid: int) -> int | None:
        data = self._get(f"{API}/ISteamNews/GetNewsForApp/v2/", {
            "appid": appid, "count": 1, "feeds": "steam_community_announcements",
        })
        items = (data or {}).get("appnews", {}).get("newsitems", [])
        return int(items[0]["date"]) if items and "date" in items[0] else None

    def search_store(self, term: str) -> list[StoreItem]:
        if not term.strip():
            return []
        data = self._get(f"{STORE}/storesearch/", {"term": term, "cc": self.country, "l": self.language})
        items = []
        for it in (data or {}).get("items", []):
            if it.get("type", "app") != "app" or "id" not in it:
                continue
            price = it.get("price") or {}
            items.append(StoreItem(
                appid=int(it["id"]),
                name=it.get("name", ""),
                price_cents=price.get("final") if price else 0,
                original_cents=price.get("initial") if price else None,
                currency=price.get("currency", ""),
                image_url=it.get("tiny_image", ""),
            ))
        return items

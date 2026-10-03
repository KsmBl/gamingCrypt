"""Glue between local Steam data, the web APIs and on-disk caches."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from gamingcrypt.steam import installer, library, library_setup
from gamingcrypt.steam.client import SteamClient
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.webapi import SteamAPIError, SteamWebAPI, StoreItem

METADATA_TTL = 7 * 24 * 3600
IMAGE_URLS = [
    "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
    "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
]
LOCAL_IMAGE_NAMES = ["{appid}_library_600x900.jpg", "{appid}/library_600x900.jpg", "{appid}_header.jpg", "{appid}/header.jpg"]


class SteamService:
    def __init__(self, steam_cfg: dict, cache_dir: Path, api: SteamWebAPI | None = None,
                 client: SteamClient | None = None, home: Path | None = None, now=time.time):
        self.cfg = steam_cfg
        self.cache_dir = Path(cache_dir)
        self.api = api or SteamWebAPI(steam_cfg.get("api_key", ""), steam_cfg.get("steam_id", ""),
                                      steam_cfg.get("country", "de"), steam_cfg.get("language", "english"))
        self._client = client
        self.home = home
        self.now = now
        # Preferred library for new installs (the encrypted drive), set by the app.
        self.install_library = ""
        self._lock = threading.Lock()
        self._metadata: dict[str, dict] = self._read_json("steam_metadata.json", {})

    # helpers ----------------------------------------------------------------
    @property
    def client(self) -> SteamClient:
        if self._client is None:
            self._client = SteamClient(self.cfg.get("command") or None)
        return self._client

    def _sync_account(self) -> None:
        """Settings may change the key at runtime; the SteamID is detected from Steam itself."""
        if self.cfg.get("api_key"):
            self.api.api_key = self.cfg["api_key"]
        if self.cfg.get("steam_id"):
            self.api.steam_id = self.cfg["steam_id"]
        elif not self.api.steam_id:
            user = self.account()
            if user:
                self.api.steam_id = user["steam_id"]

    def account(self) -> dict | None:
        root = self.root
        return library.logged_in_user(root) if root is not None else None

    @property
    def full_library_available(self) -> bool:
        self._sync_account()
        return self.api.can_list_owned

    @property
    def root(self) -> Path | None:
        return library.find_steam_root(self.cfg.get("root", ""), self.home)

    def _read_json(self, name: str, default: Any) -> Any:
        try:
            return json.loads((self.cache_dir / name).read_text())
        except (OSError, ValueError):
            return default

    def _write_json(self, name: str, data: Any) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data))
        tmp.replace(self.cache_dir / name)

    # library ----------------------------------------------------------------
    def owned_games(self) -> list[dict]:
        """Owned games from the Web API, falling back to the last cached answer when offline."""
        self._sync_account()
        if not self.api.can_list_owned:
            return []
        try:
            owned = self.api.owned_games()
        except SteamAPIError:
            return self._read_json("owned_games.json", [])
        self._write_json("owned_games.json", owned)
        return owned

    def load_library(self, include_owned: bool = True) -> list[SteamGame]:
        """Blocking: installed games + (optionally) every owned game, with cached metadata."""
        root = self.root
        games: dict[int, SteamGame] = {}
        playtime: dict[int, dict[str, int]] = {}
        if root is not None:
            for game in library.installed_games(root):
                games[game.appid] = game
            playtime = library.local_playtime(root)
        if include_owned:
            for entry in self.owned_games():
                if not library.is_game(entry["appid"], entry["name"]):
                    continue
                game = games.setdefault(entry["appid"], SteamGame(entry["appid"], entry["name"]))
                game.playtime_minutes = max(game.playtime_minutes, entry.get("playtime", 0))
                game.last_played = max(game.last_played or 0, entry.get("last_played", 0)) or None
        for appid, local in playtime.items():
            if appid in games:
                game = games[appid]
                game.playtime_minutes = max(game.playtime_minutes, local["playtime"])
                game.last_played = max(game.last_played or 0, local["last_played"]) or None
        for game in games.values():
            self.apply_metadata(game)
        return list(games.values())

    def installed_games(self) -> list[SteamGame]:
        return [g for g in self.load_library(include_owned=False) if g.installed]

    # metadata ---------------------------------------------------------------
    def apply_metadata(self, game: SteamGame) -> SteamGame:
        meta = self._metadata.get(str(game.appid))
        if not meta:
            return game
        game.release_date = meta.get("release_date")
        game.price_cents = meta.get("price_cents")
        game.currency = meta.get("currency", "")
        game.description = meta.get("description", "")
        if not game.last_updated:
            game.last_updated = meta.get("last_update")
        return game

    def needs_metadata(self, game: SteamGame) -> bool:
        meta = self._metadata.get(str(game.appid))
        return not meta or self.now() - meta.get("fetched_at", 0) > METADATA_TTL

    def fetch_metadata(self, appid: int) -> dict:
        """Blocking network fetch of release date, price and latest update; cached on disk."""
        details = self.api.app_details(appid)
        try:
            news = self.api.latest_news_date(appid)
        except SteamAPIError:
            news = None
        meta = {
            "release_date": details.get("release_date"),
            "price_cents": details.get("price_cents"),
            "currency": details.get("currency", ""),
            "description": details.get("description", ""),
            "last_update": news,
            "fetched_at": int(self.now()),
        }
        with self._lock:
            self._metadata[str(appid)] = meta
            self._write_json("steam_metadata.json", self._metadata)
        return meta

    # images -----------------------------------------------------------------
    def local_image(self, appid: int) -> Path | None:
        cached = self.cache_dir / "images" / f"{appid}.jpg"
        if cached.is_file():
            return cached
        root = self.root
        if root is not None:
            for pattern in LOCAL_IMAGE_NAMES:
                path = root / "appcache" / "librarycache" / pattern.format(appid=appid)
                if path.is_file():
                    return path
        return None

    def download_image(self, appid: int) -> Path | None:
        existing = self.local_image(appid)
        if existing:
            return existing
        target = self.cache_dir / "images" / f"{appid}.jpg"
        for url in IMAGE_URLS:
            try:
                response = self.api.session.get(url.format(appid=appid), timeout=15)
            except Exception:  # noqa: BLE001 - any network problem -> no image
                continue
            if getattr(response, "status_code", 0) == 200 and response.content:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(response.content)
                return target
        return None

    # diagnostics ------------------------------------------------------------
    def diagnose(self, unlock_cfg: dict | None = None) -> list[str]:
        """Human readable report of what GamingCrypt sees (``gamingcrypt --diagnose``)."""
        import os

        lines = []
        root = self.root
        if root is None:
            checked = [self.cfg["root"]] if self.cfg.get("root") else [str(p) for p in library.default_roots(self.home)]
            lines.append("Steam: NOT FOUND - checked:")
            lines += [f"  {p}" for p in checked]
        else:
            lines.append(f"Steam: {root}")
            for folder in library.library_folders(root):
                steamapps = folder / "steamapps"
                count = len(list(steamapps.glob("appmanifest_*.acf"))) if steamapps.is_dir() else 0
                state = "ok" if steamapps.is_dir() else "missing steamapps (not mounted?)"
                mounted = " [mount point]" if os.path.ismount(folder) else ""
                lines.append(f"  library {folder}{mounted}: {count} manifests, {state}")
            lines.append(f"  installed games (without tools): {len(library.installed_games(root))}")
        user = self.account()
        self._sync_account()
        lines.append(f"Steam account: {user['name']} ({user['steam_id']})" if user else "Steam account: not detected")
        lines.append(f"SteamID used: {self.api.steam_id or '-'}")
        lines.append(f"Web API key: {'set' if self.api.api_key else 'NOT SET (only installed games are listed)'}")
        if self.api.can_list_owned:
            try:
                lines.append(f"Owned games via Web API: {len(self.api.owned_games())}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"Owned games via Web API: ERROR {exc}")
        if unlock_cfg is not None:
            mp = os.path.expanduser(unlock_cfg.get("mount_point", ""))
            lines.append(f"Volume: {unlock_cfg.get('volume') or '-'}")
            lines.append(f"Mount point: {mp or '-'} ({'mounted' if mp and os.path.ismount(mp) else 'NOT mounted'})")
        return lines

    # installing without Steam's dialog ----------------------------------------
    def target_library(self) -> Path | None:
        """The encrypted drive if it's mounted and a Steam library, else Steam's own folder."""
        import os

        root = self.root
        if root is None:
            return None
        path = self.install_library
        if path and os.path.ismount(path) and library_setup.is_registered(root, Path(path)):
            return Path(path)
        return root

    @property
    def silent_install(self) -> bool:
        return bool(self.cfg.get("silent_install", True))

    def install_game(self, appid: int, name: str) -> installer.InstallResult:
        self._sync_account()
        target = self.target_library()
        return installer.install(self.root, target or Path("/nonexistent"), appid, name, self.client,
                                 owner=self.api.steam_id or "")

    def install_progress(self, appid: int) -> installer.InstallProgress:
        return installer.progress(self.root, appid)

    # library folder on the encrypted drive -----------------------------------
    def ensure_library(self, path: str) -> library_setup.LibraryResult:
        return library_setup.ensure_library(self.root, path, self.client)

    # store ------------------------------------------------------------------
    def search_store(self, term: str) -> list[StoreItem]:
        return self.api.search_store(term)

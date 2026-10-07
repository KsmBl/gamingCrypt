"""When emulated games were played and for how long - Emulation/config/playtime.json."""

from __future__ import annotations

import json
import time
from typing import Callable

from gamingcrypt.emulation.library import EmulationPaths, RomGame


class PlayLog:
    def __init__(self, paths: EmulationPaths, now: Callable[[], float] = time.time):
        self.path = paths.config / "playtime.json"
        self.now = now
        self.started: dict[int, float] = {}

    def _all(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)

    @staticmethod
    def _seconds(entry: dict) -> int:
        """(older entries kept whole minutes only)"""
        return int(entry.get("seconds", int(entry.get("minutes", 0)) * 60))

    def get(self, appid: int) -> tuple[int | None, int]:
        """(last played timestamp, minutes played)."""
        entry = self._all().get(str(appid), {})
        return entry.get("last_played"), self._seconds(entry) // 60

    def start(self, game: RomGame) -> None:
        now = self.now()
        self.started[game.appid] = now
        data = self._all()
        entry = data.setdefault(str(game.appid), {})
        entry.update(system=game.system.id, file=game.path.name, last_played=int(now), playing_since=now)
        self._write(data)

    def _add(self, appid: int, ending: bool) -> int:
        """The time since the start / the last tick goes onto the game; seconds added.
        After a restart of GamingCrypt the start is read back from the file."""
        data = self._all()
        entry = data.get(str(appid))
        since = self.started.get(appid)
        if since is None and entry is not None:
            since = entry.get("playing_since")
        if since is None or entry is None:
            self.started.pop(appid, None)
            return 0
        now = self.now()
        added = max(0, int(now - since))
        entry["seconds"] = self._seconds(entry) + added
        entry.pop("minutes", None)
        entry["last_played"] = int(now)
        if ending:
            entry.pop("playing_since", None)
            self.started.pop(appid, None)
        else:
            entry["playing_since"] = now
            self.started[appid] = now
        self._write(data)
        return added

    def tick(self, appid: int) -> None:
        """While it runs (every minute): the time so far is kept - a restart of GamingCrypt or
        of gaming mode in the middle of a game loses at most that minute."""
        self._add(appid, ending=False)

    def finish(self, appid: int) -> int:
        """The game ended: add the time. Returns the minutes of this session."""
        return round(self._add(appid, ending=True) / 60)

    def apply(self, games) -> None:
        """Fill last_played / minutes into scanned games."""
        data = self._all()
        for game in games:
            entry = data.get(str(game.appid), {})
            game.last_played = entry.get("last_played")
            game.minutes = self._seconds(entry) // 60

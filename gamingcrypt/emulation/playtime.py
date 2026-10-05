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

    def get(self, appid: int) -> tuple[int | None, int]:
        """(last played timestamp, minutes played)."""
        entry = self._all().get(str(appid), {})
        return entry.get("last_played"), int(entry.get("minutes", 0))

    def start(self, game: RomGame) -> None:
        now = self.now()
        self.started[game.appid] = now
        data = self._all()
        entry = data.setdefault(str(game.appid), {"minutes": 0})
        entry.update(system=game.system.id, file=game.path.name, last_played=int(now))
        self._write(data)

    def finish(self, appid: int) -> int:
        """The game ended: add the time. Returns the minutes of this session."""
        started = self.started.pop(appid, None)
        if started is None:
            return 0
        minutes = max(0, round((self.now() - started) / 60))
        data = self._all()
        entry = data.setdefault(str(appid), {"minutes": 0})
        entry["minutes"] = int(entry.get("minutes", 0)) + minutes
        entry["last_played"] = int(self.now())
        self._write(data)
        return minutes

    def apply(self, games) -> None:
        """Fill last_played / minutes into scanned games."""
        data = self._all()
        for game in games:
            entry = data.get(str(game.appid), {})
            game.last_played = entry.get("last_played")
            game.minutes = int(entry.get("minutes", 0))

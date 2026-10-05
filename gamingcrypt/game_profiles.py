"""Per-game settings that GamingCrypt applies while the game runs: power limit and
FPS limit (gaming mode). Stored next to the config as game-profiles.json."""

from __future__ import annotations

import json
from pathlib import Path

FPS_CHOICES = [0, 30, 40, 45, 60]  # 0 = no limit


def default_path() -> Path:
    from gamingcrypt.config import config_dir

    return config_dir() / "game-profiles.json"


class GameProfiles:
    def __init__(self, path: Path | None = None):
        self.path = path or default_path()

    def _all(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, appid: int) -> dict:
        profile = self._all().get(str(int(appid)), {})
        return profile if isinstance(profile, dict) else {}

    def set(self, appid: int, key: str, value) -> None:
        data = self._all()
        profile = data.setdefault(str(int(appid)), {})
        if value in (None, 0, ""):
            profile.pop(key, None)  # back to the default
        else:
            profile[key] = value
        if not profile:
            data.pop(str(int(appid)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)

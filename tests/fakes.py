"""Test doubles for HTTP sessions."""

import requests


class FakeResponse:
    def __init__(self, payload=None, status=200, content=b""):
        self.payload = payload
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    """Maps URL substrings to responses (or exceptions); records requests."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append((url, params))
        for fragment, response in self.routes.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response(params) if callable(response) else response
        return FakeResponse(status=404)


from gamingcrypt.steam.models import SteamGame  # noqa: E402


class FakeClient:
    def __init__(self):
        self.actions = []

    def play(self, appid):
        self.actions.append(("play", appid))
        return True

    def install(self, appid):
        self.actions.append(("install", appid))
        return True

    def uninstall(self, appid):
        self.actions.append(("uninstall", appid))
        return True

    def open_store(self, appid):
        self.actions.append(("store", appid))
        return True


def sample_games():
    return [
        SteamGame(620, "Portal 2", installed=True, playtime_minutes=1234, size_on_disk=12_000_000_000,
                  last_updated=1600000000, release_date=1303084800, price_cents=195, currency="EUR"),
        SteamGame(1145360, "Hades", installed=True, playtime_minutes=60, last_updated=1700000000),
        SteamGame(292030, "The Witcher 3", playtime_minutes=6000, release_date=1431993600, price_cents=2999,
                  currency="EUR"),
        SteamGame(400, "Portal", playtime_minutes=10),
    ]


class FakeService:
    """In-memory replacement for SteamService used by the UI tests."""

    full_library_available = True

    def __init__(self, games=None, store_items=None, metadata=None):
        self.games = games if games is not None else sample_games()
        self.store_items = store_items or []
        self.metadata = metadata or {}
        self.fetched = []
        self.client = FakeClient()
        self.store_queries = []

    def installed_games(self):
        return [g for g in self.games if g.installed]

    def load_library(self, include_owned=True):
        return list(self.games)

    def local_image(self, appid):
        return None

    def download_image(self, appid):
        return None

    def needs_metadata(self, game):
        return game.appid in self.metadata and game.appid not in self.fetched

    def fetch_metadata(self, appid):
        self.fetched.append(appid)
        return self.metadata[appid]

    def apply_metadata(self, game):
        meta = self.metadata.get(game.appid)
        if meta and game.appid in self.fetched:
            game.price_cents = meta.get("price_cents")
            game.release_date = meta.get("release_date")
            game.currency = meta.get("currency", "")
            game.store_size = meta.get("storage_bytes")
        return game

    def search_store(self, term):
        self.store_queries.append(term)
        return [i for i in self.store_items if term.lower() in i.name.lower()]


class SilentInstallService(FakeService):
    """FakeService that downloads without the Steam dialog, with scripted progress."""

    silent_install = True

    def __init__(self, progress_steps=None, install_result=None, **kw):
        super().__init__(**kw)
        from gamingcrypt.steam.installer import InstallProgress, InstallResult

        self.installs = []
        self.install_result = install_result or InstallResult(True, "Download started in the background")
        self.progress_steps = list(progress_steps or [InstallProgress("installed", 10, 10)])
        self.missing = InstallProgress("missing")

    def install_game(self, appid, name):
        self.installs.append(appid)
        return self.install_result

    def install_progress(self, appid):
        if appid not in self.installs:
            return self.missing
        return self.progress_steps.pop(0) if len(self.progress_steps) > 1 else self.progress_steps[0]


def solid_image(path, color: str = "#d03020"):
    """A one-colour cover picture, to tell a real cover from the drawn letter."""
    from PySide6.QtGui import QColor, QImage

    image = QImage(60, 90, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    image.save(str(path))
    return path


def cover_color(label) -> str:
    """The colour in the middle of a cover label's picture."""
    image = label.pixmap().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name()

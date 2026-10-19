"""Age ratings: which games a user with an age gets to see (gamingcrypt/users.py).

The steps are the German ones (FSK / USK): 0, 6, 12, 16, 18. A game's rating is

* what the admin set on its page (Options -> Age rating), else
* a Steam game: the USK rating on its store page (the German store's own where there's no USK
  one; the store's age gate otherwise) - also for a Windows / Linux game matched to a Steam game;
* an emulated game: libretro-database's ESRB rating, as the nearest step.

A user with an age sees the games rated for that age or below. A game nobody has a rating for
isn't shown to them: the admin rates it, then it is.
"""

from __future__ import annotations

STEPS = (0, 6, 12, 16, 18)
# ESRB -> the step that's at least as careful (there's no 10 and no 13 / 17 among the steps)
ESRB = {"EC": 0, "E": 6, "KA": 6, "K-A": 6, "E10+": 12, "E10": 12, "T": 12, "M": 16, "AO": 18}
MANUAL = "rating"  # in the game's profile: the admin's own rating, as text ("0" is a rating too)


def step_for(age) -> int | None:
    """The lowest step that covers an age given in years (13 -> 16, 17 -> 18)."""
    try:
        age = int(str(age).strip())
    except (TypeError, ValueError):
        return None
    if age < 0:
        return None
    return next((step for step in STEPS if age <= step), STEPS[-1])


def from_esrb(code: str | None) -> int | None:
    return ESRB.get((code or "").strip().upper())


def from_store(details: dict) -> int | None:
    """From Steam's appdetails (asked with the German store's country code)."""
    ratings = details.get("ratings") if isinstance(details.get("ratings"), dict) else {}
    for board in ("usk", "steam_germany"):
        entry = ratings.get(board)
        found = step_for(entry.get("rating")) if isinstance(entry, dict) else None
        if found is not None:
            return found
    gate = step_for(details.get("required_age"))
    return gate if gate else None  # (0: no age gate - that's not a rating)


def manual(profile: dict) -> int | None:
    value = profile.get(MANUAL)
    return step_for(value) if value not in (None, "") else None


def automatic(game, tab) -> int | None:
    """The rating found for the game by itself (no network) - None: unknown."""
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.wine.library import WindowsGame

    if isinstance(game, RomGame):
        facts = getattr(tab, "rom_facts", None)
        return from_esrb(facts.rating(game)) if facts is not None else None
    if getattr(game, "AGE", None) is not None:
        return game.AGE  # its own (Minecraft)
    stored = getattr(tab.service, "stored_metadata", None)
    if stored is None:
        return None
    if isinstance(game, WindowsGame):
        from gamingcrypt.game_facts import steam_appid_of

        appid = steam_appid_of(game, tab)
        return stored(appid).get("age") if appid else None
    return stored(game.appid).get("age")


def age_of(game, tab) -> int | None:
    rated = getattr(tab, "rating_profiles", None) or getattr(tab, "profiles", None)  # (the admin's)
    own = manual(rated.get(game.appid)) if rated is not None else None
    return own if own is not None else automatic(game, tab)


def allowed(game, tab) -> bool:
    """May whoever uses the tab see this game?"""
    limit = getattr(tab, "age_limit", None)
    if limit is None:
        return True
    age = age_of(game, tab)
    return age is not None and age <= limit


class RatedService:
    """The Steam service for a user who isn't the admin. What it lists is theirs:
    - when a game was played last, and for how long, is what *they* played (Steam itself only
      knows it per Steam account - GamingCrypt keeps it with the user, see app.game_started);
    - with an age: the games rated for older ones (or not at all) aren't in it.
    Everything else is the service's own."""

    _OWN = ("_service", "_tab", "unrated")

    def __init__(self, service, tab):
        object.__setattr__(self, "_service", service)
        object.__setattr__(self, "_tab", tab)
        object.__setattr__(self, "unrated", [])  # installed, no rating known (yet): looked up next

    def __getattr__(self, name):
        return getattr(self._service, name)

    def __setattr__(self, name, value) -> None:
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self._service, name, value)

    def _rated(self, games: list) -> list:
        profiles = getattr(self._tab, "profiles", None)
        played = profiles._all() if profiles is not None else {}
        for game in games:
            own = played.get(str(game.appid)) or {}
            game.last_played = own.get("last_played")
            game.playtime_minutes = int(own.get("minutes", 0) or 0)
        if getattr(self._tab, "age_limit", None) is None:
            return games
        self.unrated = [g for g in games if getattr(g, "installed", False) and age_of(g, self._tab) is None]
        return [g for g in games if allowed(g, self._tab)]

    def installed_games(self):
        return self._rated(self._service.installed_games())

    def load_library(self, *args, **kwargs):
        return self._rated(self._service.load_library(*args, **kwargs))

    def search_store(self, term: str):
        return [item for item in self._service.search_store(term) if allowed(item, self._tab)]

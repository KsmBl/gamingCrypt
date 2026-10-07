"""Upscaling algorithm and resolution: a system's (every game of it that has no choice of its
own - the system page's 🔍 Upscaling) and a game's own (its Options).

A game's profile: no "scaler" / "resolution" = its system's; OFF = none / native by choice.
The system's choice is made for every core of the system: what a core can't do is left out
when the game starts (retroarch.launch - an algorithm it hasn't, the nearest lower resolution).
"""

from __future__ import annotations

OFF = "none"


def system_choice(config: dict, system_id: str) -> dict:
    """{"scaler": …, "resolution": …} of the system (empty: none, native)."""
    value = (config.get("upscaling") or {}).get(system_id)
    return dict(value) if isinstance(value, dict) else {}


def set_system_choice(config: dict, system_id: str, scaler: str | None, resolution: str | None) -> None:
    table = config.setdefault("upscaling", {})
    choice = {k: v for k, v in (("scaler", scaler), ("resolution", resolution)) if v}
    if choice:
        table[system_id] = choice
    else:
        table.pop(system_id, None)


def _pick(profile: dict, system: dict, key: str) -> str | None:
    value = profile[key] if key in profile else system.get(key)
    return None if value in (None, OFF, "1x") else value


def for_game(config: dict, profile: dict, system_id: str) -> tuple[str | None, str | None]:
    """(algorithm, resolution) the game starts with - its own, else its system's."""
    system = system_choice(config, system_id)
    return _pick(profile, system, "scaler"), _pick(profile, system, "resolution")


def describe_system(config: dict, system_id: str) -> str:
    """"xBRZ 3x", "2x", "None" - what "System default" stands for."""
    from gamingcrypt.emulation import scalers

    choice = system_choice(config, system_id)
    scaler = scalers.BY_ID.get(choice.get("scaler") or "")
    resolution = choice.get("resolution")
    parts = [scaler.name if scaler else "", resolution or ""]
    return " ".join(p for p in parts if p) or "None"

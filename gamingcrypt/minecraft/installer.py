"""Getting an instance ready to play: Minecraft itself (portablemc) - and for one with controller
support Fabric and its mods (Modrinth) for the Minecraft version Controlify is made for."""

from __future__ import annotations

import subprocess
from typing import Callable

from gamingcrypt.minecraft import mods, portable
from gamingcrypt.minecraft.library import LATEST, MinecraftInstance


def install(paths: portable.Paths, instance: MinecraftInstance, progress: Callable[[float, str], None],
            popen=subprocess.Popen, get: mods.Get = mods.get_json, fetch=mods.get_bytes,
            releases: Callable[[portable.Paths], list[str]] = portable.releases) -> tuple[bool, str, str]:
    """-> (ok, message, the version to start). The mods and the Minecraft version they're for are
    noted in the instance (saved by the caller)."""
    if not instance.controller:
        ok, message, version = portable.install(paths, instance, progress, popen=popen)
        if ok:
            instance.game_version = version
        return ok, message, version
    game_version = instance.version
    try:
        if game_version == LATEST:
            progress(0.0, "Looking for the newest Minecraft with controller support…")
            game_version = mods.newest_supported(releases(paths), get)
            if game_version is None:
                return False, "No Minecraft release with controller support (Controlify) found - is the device online?", ""
        progress(0.0, "Looking for the controller mods…")
        files, missing = mods.resolve([mods.CONTROLLER, *mods.EXTRAS], game_version, get)
    except (OSError, ValueError, mods.requests.RequestException) as exc:
        return False, f"Modrinth (the mods) can't be reached - is the device online? ({exc})", ""
    if missing:
        return False, (f"Controlify isn't there for Minecraft {game_version} (yet) - make an instance with "
                       "another version, or without controller support"), ""
    ok, message, version = portable.install(paths, instance, progress, popen=popen, spec=f"fabric:{game_version}")
    if not ok:
        return ok, message, version
    try:
        instance.mods = mods.download(files, instance.path / mods.MODS, instance.mods, fetch, progress)
        instance.projects = {f.filename: f.project for f in files if f.filename in instance.mods}
    except (OSError, ValueError, mods.requests.RequestException) as exc:
        return False, f"The controller mods didn't download: {exc}", ""
    instance.game_version = game_version
    return True, "Installed", version


def describe(instance: MinecraftInstance) -> str:
    """What it is, for its page: "Minecraft 1.21.4 · with controller support"."""
    version = instance.game_version or (instance.installed if not instance.controller else "")
    name = f"Minecraft {version}" if version else f"Minecraft ({instance.describe_version()})"
    return f"{name} · with controller support (Controlify)" if instance.controller else name


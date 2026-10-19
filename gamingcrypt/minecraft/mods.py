"""Mods from Modrinth (api.modrinth.com): what an instance with controller support gets - Controlify
(the whole game with a controller, an on-screen keyboard in chat and on signs) and Sodium (a faster
game on a handheld) - with the mods they need themselves (Fabric API, YetAnotherConfigLib …).

The files go into the instance's mods folder, each checked against Modrinth's SHA-512.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

API = "https://api.modrinth.com/v2"
LOADER = "fabric"
CONTROLLER = "controlify"  # needed: no controller support without it
EXTRAS = ("sodium",)  # when there's one for the version
MODS = "mods"
TIMEOUT = 60

Get = Callable[[str, dict], object]  # (url, params) -> the JSON


def user_agent() -> str:
    from gamingcrypt import __version__

    return f"KsmBl/gamingCrypt/{__version__} (github.com/KsmBl/gamingCrypt)"  # (Modrinth asks for one)


def get_json(url: str, params: dict | None = None):
    response = requests.get(url, params=params, headers={"User-Agent": user_agent()}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def get_bytes(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": user_agent()}, timeout=TIMEOUT)
    response.raise_for_status()
    return response.content


@dataclass(frozen=True)
class ModFile:
    project: str  # Modrinth project id (or slug, for the ones asked for by name)
    filename: str
    url: str
    sha512: str


def versions(project: str, game_version: str | None, get: Get = get_json, loader: str = LOADER) -> list[dict]:
    """The project's versions for the loader (and game version) - releases first, newest first."""
    params = {"loaders": json.dumps([loader])}
    if game_version:
        params["game_versions"] = json.dumps([game_version])
    found = get(f"{API}/project/{project}/version", params)
    found = [v for v in found if isinstance(v, dict)] if isinstance(found, list) else []
    newest = sorted(found, key=lambda v: v.get("date_published", ""), reverse=True)
    return sorted(newest, key=lambda v: v.get("version_type") != "release")  # (stable: keeps the order)


def supported(project: str = CONTROLLER, get: Get = get_json) -> set[str]:
    """Every game version the project has a build for."""
    return {g for v in versions(project, None, get) for g in v.get("game_versions", [])}


def newest_supported(releases: list[str], get: Get = get_json) -> str | None:
    """The newest release (releases: newest first) Controlify is made for."""
    have = supported(CONTROLLER, get)
    return next((r for r in releases if r in have), None)


def _file(project: str, version: dict) -> ModFile | None:
    files = version.get("files") or []
    chosen = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not chosen or not chosen.get("url"):
        return None
    return ModFile(project, chosen["filename"], chosen["url"], (chosen.get("hashes") or {}).get("sha512", ""))


def resolve(projects: list[str], game_version: str, get: Get = get_json,
            required: tuple[str, ...] = (CONTROLLER,)) -> tuple[list[ModFile], list[str]]:
    """The files for these projects and everything they need -> (files, needed ones not found)."""
    files: dict[str, ModFile] = {}
    missing: list[str] = []
    queue = [(p, p in required) for p in projects]
    seen: set[str] = set()
    while queue:
        project, needed = queue.pop(0)
        if project in seen:
            continue
        seen.add(project)
        found = versions(project, game_version, get)
        if not found:
            if needed:
                missing.append(project)
            continue
        version = found[0]
        chosen = _file(version.get("project_id") or project, version)
        if chosen is None:
            if needed:
                missing.append(project)
            continue
        files[chosen.project] = chosen
        seen.add(chosen.project)  # (by its id too: a dependency names it so)
        for dependency in version.get("dependencies") or []:
            if dependency.get("dependency_type") == "required" and dependency.get("project_id"):
                queue.append((dependency["project_id"], needed))
    return list(files.values()), missing


def sha512(data: bytes) -> str:
    return hashlib.sha512(data).hexdigest()


def download(files: list[ModFile], folder: Path, before: list[str] = (), fetch: Callable[[str], bytes] = get_bytes,
             progress: Callable[[float, str], None] = lambda f, t: None) -> list[str]:
    """Into the mods folder; the files put there last time (before) that aren't wanted any more
    go. -> the file names now there. A file that doesn't match its checksum: ValueError."""
    folder.mkdir(parents=True, exist_ok=True)
    for index, mod in enumerate(files):
        target = folder / mod.filename
        progress(index / max(1, len(files)), f"Downloading {mod.filename}…")
        if target.exists() and (not mod.sha512 or sha512(target.read_bytes()) == mod.sha512):
            continue
        data = fetch(mod.url)
        if mod.sha512 and sha512(data) != mod.sha512:
            raise ValueError(f"{mod.filename} didn't download completely - try again")
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.replace(target)
    wanted = {m.filename for m in files}
    for name in before:
        if name not in wanted and "/" not in name:
            (folder / name).unlink(missing_ok=True)  # (an older version of one of ours)
    return sorted(wanted)


# the Mods page: any mod from Modrinth, for the instance's Minecraft ---------------------------------
@dataclass(frozen=True)
class Found:
    project: str
    title: str
    description: str
    downloads: int
    author: str


def search(query: str, game_version: str, get: Get = get_json, limit: int = 20) -> list[Found]:
    """Fabric mods for this Minecraft version, the most downloaded first."""
    facets = [[f"categories:{LOADER}"], [f"versions:{game_version}"], ["project_type:mod"]]
    params = {"query": query, "limit": limit, "facets": json.dumps(facets)}
    if not query.strip():
        params["index"] = "downloads"  # (nothing asked for: the popular ones)
    found = get(f"{API}/search", params)
    hits = found.get("hits", []) if isinstance(found, dict) else []
    return [Found(h.get("project_id", ""), h.get("title", ""), h.get("description", ""), int(h.get("downloads") or 0),
                  h.get("author", "")) for h in hits if isinstance(h, dict) and h.get("project_id")]


def installed(folder: Path) -> list[str]:
    """The mod files in the folder - put there here or by hand."""
    try:
        return sorted((p.name for p in folder.iterdir() if p.suffix == ".jar"), key=str.casefold)
    except OSError:
        return []


def add(project: str, game_version: str, folder: Path, get: Get = get_json,
        fetch: Callable[[str], bytes] = get_bytes) -> list[ModFile]:
    """One more mod and what it needs -> their files (now in the folder). Not there for the
    version: LookupError."""
    files, missing = resolve([project], game_version, get, required=(project,))
    if missing:
        raise LookupError(f"not there for Minecraft {game_version}")
    download(files, folder, (), fetch)  # (nothing of ours goes)
    return files


def remove(name: str, folder: Path, ours: list[str]) -> list[str]:
    (folder / name).unlink(missing_ok=True)
    return [n for n in ours if n != name]


def friendly(name: str) -> str:
    """"sodium-fabric-0.6.13+mc1.21.4.jar" -> "sodium fabric" - a file name as a mod's name."""
    import re

    stem = name.removesuffix(".jar")
    words = re.split(r"[-_+ ]", stem)
    kept = []
    for word in words:
        loader_word = kept and word.lower() in ("fabric", "lts")  # ("fabric-api": its first word is its name)
        if re.match(r"^v?\d", word) or word.lower().startswith("mc1") or loader_word:
            break
        kept.append(word)
    return " ".join(kept).strip() or stem

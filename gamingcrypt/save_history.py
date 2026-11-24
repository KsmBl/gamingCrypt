"""Every version of a user's saves of a Windows game - only the save files (save_locations), not the
Wine prefix around them. The ground for syncing between devices: each version knows which device
made it and which version it came from, so "newer" never depends on a clock, and two devices that
both played on from the same saves are told apart from one that simply played on.

On the drive, with the prefixes (encrypted like them):
<library>/.save-history/<user, "admin">/<game>/
    versions/<device>-<counter>.json   what was where: {"home/AppData/…/user1.dat": {"hash", "size"}, …}
    objects/<ab>/<sha256>              each file's content, once however many versions have it
    state.json                         which version the files on this device are ("head"), and the
                                       hashes of the files as they were then (not hashed again unchanged)

A version's files are kept for the newest KEEP versions (and the head and every tip); older ones stay
as names, so the family tree stays whole. A folder made elsewhere (another device: copied in by a later
sync) is simply more versions and objects here.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt import save_locations
from gamingcrypt.save_locations import SAVE, Location
from gamingcrypt.wine import library as wine

HISTORY = ".save-history"
ADMIN_FOLDER = "admin"
KEEP = 20
PLAYED, RESTORED, CHOSEN, FOUND = "played", "restored", "chosen", "found"  # why a version was made
SAME, NEWER, CONFLICT = "same", "newer", "conflict"

_lock = threading.RLock()


class HistoryError(Exception):
    """Why it didn't work, for the user - the saves are as they were."""


# --- this device -------------------------------------------------------------------------------

def device(folder: Path | None = None) -> tuple[str, str]:
    """(this device's id, its name) - made once, kept with the settings."""
    if folder is None:
        from gamingcrypt.config import config_dir

        folder = config_dir()
    path = Path(folder) / "device.json"
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"]), str(data.get("name") or data["id"])
    except (OSError, ValueError):
        pass
    data = {"id": uuid.uuid4().hex[:12], "name": socket.gethostname() or "This device"}
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, data)
    return data["id"], data["name"]


# --- a version ---------------------------------------------------------------------------------

@dataclass
class Version:
    id: str
    device: str
    device_name: str
    counter: int
    parents: list[str]
    made: float
    why: str
    files: dict[str, dict] = field(default_factory=dict)  # "root/path" -> {"hash", "size"}
    kept: bool = True  # its files are still here

    @property
    def size(self) -> int:
        return sum(int(f.get("size", 0)) for f in self.files.values())

    def content(self) -> dict[str, str]:
        return {key: f["hash"] for key, f in self.files.items()}

    def plain(self) -> dict:
        return {"id": self.id, "device": self.device, "device_name": self.device_name, "counter": self.counter,
                "parents": self.parents, "made": self.made, "why": self.why, "files": self.files,
                "kept": self.kept}

    @classmethod
    def read(cls, data: dict) -> "Version":
        return cls(str(data["id"]), str(data["device"]), str(data.get("device_name") or data["device"]),
                   int(data["counter"]), [str(p) for p in data.get("parents") or []], float(data["made"]),
                   str(data.get("why") or PLAYED), dict(data.get("files") or {}), bool(data.get("kept", True)))


def _write_json(path: Path, data) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(temp, path)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _key(root: str, relative: str) -> str:
    return f"{root}/{relative}"


def _split(key: str) -> tuple[str, str]:
    root, _, relative = key.partition("/")
    return root, relative


# --- a user's history of a game ----------------------------------------------------------------

class History:
    def __init__(self, game, user: str = "", places: list[Location] | None = None,
                 me: tuple[str, str] | None = None, keep: int = KEEP):
        self.game, self.user = game, user
        self.folder = wine.library_root(game) / HISTORY / (user or ADMIN_FOLDER) / game.path.name
        places = places if places is not None else []
        self.places = [p for p in places if p.kind == SAVE]
        self.settings = [p for p in places if p.kind != SAVE]  # (also when they're in a save folder)
        self.me = me or device()
        self.keep = keep

    # what's stored -------------------------------------------------------------------------
    def versions(self) -> dict[str, Version]:
        found = {}
        try:
            files = list((self.folder / "versions").glob("*.json"))
        except OSError:
            return {}
        for file in files:
            try:
                version = Version.read(json.loads(file.read_text()))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # half copied in, or not ours
            found[version.id] = version
        return found

    def _state(self) -> dict:
        try:
            data = json.loads((self.folder / "state.json").read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _set_state(self, head: str | None, seen: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        _write_json(self.folder / "state.json", {"head": head, "seen": seen})

    @property
    def head(self) -> str | None:
        return self._state().get("head")

    def _object(self, digest: str) -> Path:
        return self.folder / "objects" / digest[:2] / digest

    def _store(self, path: Path, digest: str) -> None:
        target = self._object(digest)
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{digest}.{uuid.uuid4().hex[:8]}")
        try:
            with open(path, "rb") as source, open(temp, "wb") as copy:
                for block in iter(lambda: source.read(1 << 20), b""):
                    copy.write(block)
            if _hash(temp) != digest:  # it changed while it was copied: not this version's
                raise HistoryError(f"{path.name} changed while it was saved - try again")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)

    def newest_first(self) -> list[Version]:
        return sorted(self.versions().values(), key=lambda v: (v.made, v.counter), reverse=True)

    # the files on this device --------------------------------------------------------------
    def _roots(self) -> dict[str, Path]:
        roots = {}
        for root in save_locations.ROOTS:
            folder = save_locations.base(self.game, self.user, root)
            if folder is not None:
                roots[root] = folder
        return roots

    def current(self) -> tuple[dict[str, dict], dict]:
        """(the save files now: "root/path" -> {"hash", "size"}, the hashes to remember). A file
        unchanged since it was last looked at (size and time) isn't read again."""
        roots = self._roots()
        seen = self._state().get("seen") or {}
        files, now_seen = {}, {}
        settings = set(save_locations.files(self.game, self.user, self.settings)) if self.settings else set()
        for path in save_locations.files(self.game, self.user, self.places):
            if path in settings:
                continue
            for root, folder in roots.items():
                try:
                    relative = path.relative_to(folder).as_posix()
                except ValueError:
                    continue
                break
            else:
                continue
            key = _key(root, relative)
            try:
                facts = path.stat()
            except OSError:
                continue
            before = seen.get(key)
            if before and before[0] == facts.st_size and before[1] == facts.st_mtime_ns:
                digest = before[2]
            else:
                digest = _hash(path)
            files[key] = {"hash": digest, "size": facts.st_size}
            now_seen[key] = [facts.st_size, facts.st_mtime_ns, digest]
        return files, now_seen

    # new versions --------------------------------------------------------------------------
    def _next_counter(self, versions: dict[str, Version]) -> int:
        return max((v.counter for v in versions.values() if v.device == self.me[0]), default=0) + 1

    def _add(self, files: dict[str, dict], parents: list[str], why: str, versions: dict[str, Version],
             sources: dict[str, Path] | None = None) -> Version:
        """A new version of these files - their content stored first (from ``sources``, else it's there)."""
        for key, facts in files.items():
            if sources and key in sources:
                self._store(sources[key], facts["hash"])
            elif not self._object(facts["hash"]).exists():
                raise HistoryError("A file of that version isn't here any more")
        counter = self._next_counter(versions)
        version = Version(f"{self.me[0]}-{counter:06d}", self.me[0], self.me[1], counter, parents,
                          time.time(), why, files)
        (self.folder / "versions").mkdir(parents=True, exist_ok=True)
        _write_json(self.folder / "versions" / f"{version.id}.json", version.plain())
        versions[version.id] = version
        return version

    def record(self, why: str = PLAYED) -> Version | None:
        """The saves as they are now as a new version - None when nothing changed (or there are none
        and never were)."""
        with _lock:
            versions = self.versions()
            head = versions.get(self.head) if self.head else None
            files, seen = self.current()
            if head is not None and head.content() == {k: f["hash"] for k, f in files.items()}:
                self._set_state(head.id, seen)
                return None
            if head is None and not files:
                return None
            roots = self._roots()
            sources = {key: roots[_split(key)[0]] / _split(key)[1] for key in files}
            version = self._add(files, [head.id] if head else [], why, versions, sources)
            self._set_state(version.id, seen)
            self._prune(versions)
            return version

    # the family tree -----------------------------------------------------------------------
    @staticmethod
    def ancestors(versions: dict[str, Version], start: str) -> set[str]:
        """``start`` and every version it came from."""
        found, todo = set(), [start]
        while todo:
            current = todo.pop()
            if current in found:
                continue
            found.add(current)
            version = versions.get(current)
            if version is not None:
                todo.extend(version.parents)
        return found

    def tips(self, versions: dict[str, Version] | None = None) -> list[Version]:
        """The versions nothing came from yet - one when every device agrees."""
        versions = self.versions() if versions is None else versions
        parents = {p for v in versions.values() for p in v.parents}
        return sorted((v for v in versions.values() if v.id not in parents), key=lambda v: (v.made, v.id))

    def check(self) -> tuple[str, list[Version]]:
        """Before playing: (SAME, []), (NEWER, [that version]) - played on elsewhere from these saves -
        or (CONFLICT, [this device's, the others' …]) - played on here and elsewhere. What changed here
        since is a version first."""
        with _lock:
            self.record(FOUND)
            versions = self.versions()
            head = self.head
            mine = self.ancestors(versions, head) if head else set()
            others = [tip for tip in self.tips(versions) if tip.id not in mine]
            if not others:
                return SAME, []
            if len(others) == 1 and head is not None and head in self.ancestors(versions, others[0].id):
                return NEWER, others
            if head is None and len(others) == 1:
                return NEWER, others  # none here yet
            here = [versions[head]] if head in versions else []
            return CONFLICT, here + others

    # putting a version's files in place ----------------------------------------------------
    def _install(self, target: Version, versions: dict[str, Version]) -> None:
        """The files of ``target`` where they belong: each written complete next to its place, then
        swapped in. Files of the head that ``target`` doesn't have are removed - others are left alone."""
        if not target.kept:
            raise HistoryError("The files of that version aren't kept any more")
        for facts in target.files.values():
            if not self._object(facts["hash"]).exists():
                raise HistoryError("A file of that version is missing - nothing was changed")
        head = versions.get(self.head) if self.head else None
        roots = self._roots()
        seen = dict(self._state().get("seen") or {})
        for key, facts in target.files.items():
            root, relative = _split(key)
            folder = roots.get(root) or self._make_root(root)
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.gamingcrypt")
            try:
                with open(self._object(facts["hash"]), "rb") as source, open(temp, "wb") as copy:
                    for block in iter(lambda: source.read(1 << 20), b""):
                        copy.write(block)
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
            stat = path.stat()
            seen[key] = [stat.st_size, stat.st_mtime_ns, facts["hash"]]
        for key in (head.files if head else {}):
            if key in target.files:
                continue
            root, relative = _split(key)
            if root in roots:
                (roots[root] / relative).unlink(missing_ok=True)
            seen.pop(key, None)
        self._set_state(target.id, seen)

    def _make_root(self, root: str) -> Path:
        """The game hasn't run here yet: the Windows user's folder as Proton makes it."""
        if root == "home":
            folder = save_locations.drive_c(self.game, self.user) / "users" / "steamuser"
        elif root == "drive_c":
            folder = save_locations.drive_c(self.game, self.user)
        else:
            folder = Path(self.game.path)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def take(self, version_id: str) -> None:
        """Play on from a newer version (check() said NEWER): its files here, it's the head."""
        with _lock:
            versions = self.versions()
            target = versions.get(version_id)
            if target is None:
                raise HistoryError("That version isn't there any more")
            if not target.kept:
                raise HistoryError("The files of that version aren't kept any more")
            self._install(target, versions)
            self._prune(versions)

    def choose(self, version_id: str) -> Version:
        """After a CONFLICT: ``version_id``'s saves are the ones from now on - a new version after every
        tip, so the other devices see it's decided. The others' stay in the history."""
        with _lock:
            versions = self.versions()
            target = versions.get(version_id)
            if target is None:
                raise HistoryError("That version isn't there any more")
            if not target.kept:
                raise HistoryError("The files of that version aren't kept any more")
            parents = [tip.id for tip in self.tips(versions)]
            chosen = self._add(dict(target.files), parents, CHOSEN, versions)
            self._install(chosen, versions)
            self._prune(versions)
            return chosen

    def go_back(self, version_id: str) -> Version:
        """An older version's saves again - as a new version, so the newer ones stay too."""
        with _lock:
            self.record(FOUND)
            versions = self.versions()
            target = versions.get(version_id)
            if target is None:
                raise HistoryError("That version isn't there any more")
            if not target.kept:
                raise HistoryError("The files of that version aren't kept any more")
            if self.head and target.id == self.head:
                raise HistoryError("Those are the saves already")
            back = self._add(dict(target.files), [self.head] if self.head else [], RESTORED, versions)
            self._install(back, versions)
            self._prune(versions)
            return back

    # tidying -------------------------------------------------------------------------------
    def _prune(self, versions: dict[str, Version]) -> None:
        """The files of the newest ``keep`` versions, the head's and every tip's stay - older versions
        only as names. Objects nothing kept needs any more go."""
        by_age = sorted(versions.values(), key=lambda v: (v.made, v.counter), reverse=True)
        keep = {v.id for v in by_age[:self.keep]} | {t.id for t in self.tips(versions)}
        if self.head:
            keep.add(self.head)
        for version in by_age:
            if version.id not in keep and version.kept:
                version.kept = False
                _write_json(self.folder / "versions" / f"{version.id}.json", version.plain())
        needed = {f["hash"] for v in versions.values() if v.kept for f in v.files.values()}
        try:
            shelves = list((self.folder / "objects").iterdir())
        except OSError:
            return
        for shelf in shelves:
            for item in list(shelf.iterdir()) if shelf.is_dir() else []:
                if item.name not in needed:
                    item.unlink(missing_ok=True)


def for_game(game, user: str = "") -> History:
    """The history with the game's places as they're known now (the list's, and what playing found)."""
    from gamingcrypt.saves import PrefixSaves

    return History(game, user, PrefixSaves(game).places()[1])

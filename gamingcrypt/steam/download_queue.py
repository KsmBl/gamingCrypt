"""GamingCrypt's own download queue on top of Steam's.

Steam only picks up changes to its app manifests when it starts and rewrites
them when it exits. So the order is kept here, and it's enforced by marking
every download except the top one as paused (StateFlags bit 512) while Steam is
closed, then starting Steam again (minimised). Partially downloaded data stays.
Steam is never restarted while a game is running.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Callable

from gamingcrypt.steam import installer, library_setup, running, vdf
from gamingcrypt.steam.installer import STATE_UPDATE_PAUSED, Download, InstallResult


def _load_state(path: Path) -> dict:
    return vdf.load(path)


def _flags(data: dict) -> int:
    try:
        return int(vdf.iget(data, "AppState", "StateFlags", default=0) or 0)
    except ValueError:
        return 0


def _set_flags(path: Path, flags: int) -> None:
    data = _load_state(path)
    state = vdf.iget(data, "AppState")
    for key in list(state):
        if key.lower() == "stateflags":
            state[key] = str(flags)
            break
    else:
        state["StateFlags"] = str(flags)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(vdf.dumps(data))
    tmp.replace(path)


class DownloadQueue:
    def __init__(self, root_fn: Callable[[], Path | None], cache_dir: Path, client_fn: Callable[[], object],
                 is_running: Callable[[], bool] = library_setup.steam_running,
                 games_running: Callable[[], set[int]] = running.running_appids,
                 sleep: Callable[[float], None] = time.sleep):
        self.root_fn = root_fn
        self.path = Path(cache_dir) / "download_order.json"
        self.client_fn = client_fn
        self.is_running = is_running
        self.games_running = games_running
        self.sleep = sleep

    # order -------------------------------------------------------------------
    def saved_order(self) -> list[int]:
        try:
            return [int(a) for a in json.loads(self.path.read_text())]
        except (OSError, ValueError, TypeError):
            return []

    def save_order(self, order: list[int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(order))

    def order(self, items: list[Download]) -> list[Download]:
        """Known downloads in the user's order, new ones appended (running first)."""
        saved = self.saved_order()
        by_id = {d.appid: d for d in items}
        ordered = [by_id[a] for a in saved if a in by_id]
        ordered += [d for d in items if d.appid not in saved]
        self.save_order([d.appid for d in ordered])
        return ordered

    def move(self, items: list[Download], appid: int, delta: int) -> list[Download]:
        ordered = self.order(items)
        ids = [d.appid for d in ordered]
        if appid not in ids:
            return ordered
        i = ids.index(appid)
        j = max(0, min(len(ids) - 1, i + delta))
        ids.insert(j, ids.pop(i))
        self.save_order(ids)
        return self.order(items)

    # enforcing "only the top one downloads" -----------------------------------------
    def wanted_paused(self, ordered: list[Download]) -> dict[int, bool]:
        return {d.appid: index > 0 for index, d in enumerate(ordered)}

    def needs_apply(self, ordered: list[Download]) -> bool:
        root = self.root_fn()
        if root is None or len(ordered) < 1:
            return False
        for appid, paused in self.wanted_paused(ordered).items():
            path = installer.find_manifest(root, appid)
            if path is None:
                continue
            try:
                is_paused = bool(_flags(_load_state(path)) & STATE_UPDATE_PAUSED)
            except (OSError, vdf.VDFError):
                continue
            if is_paused != paused:
                return True
        return False

    def apply(self, ordered: list[Download]) -> InstallResult:
        """Pause everything but the top download, resume the top one, restart Steam."""
        root = self.root_fn()
        if root is None:
            return InstallResult(False, "Steam wasn't found on this device")
        if self.games_running():
            return InstallResult(False, "Waiting until your game is closed")
        client = self.client_fn()
        if not library_setup.close_steam(client, self.is_running, self.sleep):
            return InstallResult(False, "Steam didn't close - close it and try again")
        try:
            for appid, paused in self.wanted_paused(ordered).items():
                path = installer.find_manifest(root, appid)
                if path is None:
                    continue
                flags = _flags(_load_state(path))
                new = flags | STATE_UPDATE_PAUSED if paused else flags & ~STATE_UPDATE_PAUSED
                if new != flags:
                    _set_flags(path, new)
        except (OSError, vdf.VDFError) as exc:
            return InstallResult(False, f"Could not change the queue: {exc}")
        finally:
            client.start_silent()  # downloads continue in the background
        top = ordered[0].name if ordered else ""
        return InstallResult(True, f"Downloading {top} first" if top else "Queue updated")

    # cancel -------------------------------------------------------------------------
    def cancel(self, download: Download) -> InstallResult:
        """Stop a download and delete what it downloaded.

        New install: everything goes (like an uninstall). Update of an installed game:
        only the partial update data goes, the game stays and the update stays paused.
        """
        root = self.root_fn()
        if root is None:
            return InstallResult(False, "Steam wasn't found on this device")
        if self.games_running():
            return InstallResult(False, "Close your game first")
        path = installer.find_manifest(root, download.appid)
        if path is None:
            return InstallResult(True, f"{download.name} is no longer downloading")
        client = self.client_fn()
        if not download.is_update:
            result = installer.uninstall(root, download.appid, client, self.is_running, self.sleep)
            if result.ok:
                self.save_order([a for a in self.saved_order() if a != download.appid])
                return InstallResult(True, f"Cancelled {download.name} and deleted its files")
            return result
        if not library_setup.close_steam(client, self.is_running, self.sleep):
            return InstallResult(False, "Steam didn't close - close it and try again")
        try:
            steamapps = path.parent
            for partial in (steamapps / "downloading" / str(download.appid),
                            steamapps / "temp" / str(download.appid)):
                if partial.is_dir():
                    shutil.rmtree(partial)
            _set_flags(path, _flags(_load_state(path)) | STATE_UPDATE_PAUSED)
        except (OSError, vdf.VDFError) as exc:
            return InstallResult(False, f"Could not cancel: {exc}")
        finally:
            client.start_silent()
        return InstallResult(True, f"Update of {download.name} cancelled - the installed game stays")

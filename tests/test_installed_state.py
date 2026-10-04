"""Regression: games whose download was cancelled showed up as installed."""

from gamingcrypt.steam import installer, library, vdf
from gamingcrypt.steam.download_queue import DownloadQueue
from gamingcrypt.steam.installer import STATE_UPDATE_PAUSED


def manifest(folder, appid, name, flags, size=0):
    path = folder / "steamapps" / f"appmanifest_{appid}.acf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vdf.dumps({"AppState": {"appid": str(appid), "name": name, "StateFlags": str(flags),
                                            "installdir": name, "SizeOnDisk": str(size),
                                            "BytesToDownload": "1000"}}))
    return path


def test_only_fully_installed_games_are_installed(steam_root):
    manifest(steam_root, 10, "Queued", 1026)
    manifest(steam_root, 11, "Cancelled", 1026 | STATE_UPDATE_PAUSED, size=300_000_000)  # partial data
    manifest(steam_root, 12, "Downloading", 1026 | (1 << 20), size=50_000)
    games = {g.appid: g for g in library.installed_games(steam_root)}
    assert set(games) == {620, 1145360}  # only the really installed ones
    assert games[1145360].update_pending  # installed + update waiting (flags 6) still counts
    pending = {g.appid: g for g in library.installed_games(steam_root, include_pending=True)}
    assert not pending[11].installed and not pending[11].update_pending


def test_partial_first_download_is_not_an_update(steam_root):
    """SizeOnDisk already grows during a first download - that made cancel keep everything."""
    manifest(steam_root, 11, "Cancelled", 1026 | STATE_UPDATE_PAUSED, size=300_000_000)
    item = next(d for d in installer.downloads(steam_root) if d.appid == 11)
    assert not item.is_update


def test_cancel_of_such_a_download_now_deletes_it(steam_root, tmp_path):
    path = manifest(steam_root, 11, "Cancelled", 1026 | STATE_UPDATE_PAUSED, size=300_000_000)
    (steam_root / "steamapps/common/Cancelled").mkdir(parents=True)

    class Client:
        def shutdown(self):
            return True

        def start_silent(self):
            return True

    q = DownloadQueue(lambda: steam_root, tmp_path / "c", Client, is_running=lambda: False,
                      games_running=set, sleep=lambda s: None)
    item = next(d for d in installer.downloads(steam_root) if d.appid == 11)
    assert q.cancel(item).ok
    assert not path.exists() and not (steam_root / "steamapps/common/Cancelled").exists()

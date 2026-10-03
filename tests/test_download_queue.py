import pytest

from gamingcrypt.steam import installer, vdf
from gamingcrypt.steam.download_queue import DownloadQueue
from gamingcrypt.steam.installer import STATE_UPDATE_PAUSED, Download, InstallResult


def manifest(folder, appid, name, flags, size=0):
    path = folder / "steamapps" / f"appmanifest_{appid}.acf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vdf.dumps({"AppState": {"appid": str(appid), "name": name, "StateFlags": str(flags),
                                            "installdir": name.replace(" ", ""), "SizeOnDisk": str(size),
                                            "BytesDownloaded": "0", "BytesToDownload": "1000"}}))
    return path


def flags(path):
    return int(vdf.load(path)["AppState"]["StateFlags"])


class Client:
    def __init__(self):
        self.calls = []

    def shutdown(self):
        self.calls.append("shutdown")
        return True

    def start_silent(self):
        self.calls.append("start_silent")
        return True


@pytest.fixture
def setup(steam_root, tmp_path):
    # the fixture's Hades (on the second library) has an update queued - not needed here
    (steam_root.parent / "crypt/SteamLibrary/steamapps/appmanifest_1145360.acf").unlink()
    a = manifest(steam_root, 1, "Alpha", 1026)
    b = manifest(steam_root, 2, "Bravo", 1026)
    c = manifest(steam_root, 3, "Charlie", 1026 | STATE_UPDATE_PAUSED)
    client = Client()
    running = {"steam": True}

    def is_running():
        state = running["steam"]
        running["steam"] = False  # closes after shutdown
        return state

    q = DownloadQueue(lambda: steam_root, tmp_path / "cache", lambda: client, is_running=is_running,
                      games_running=set, sleep=lambda s: None)
    return q, steam_root, client, (a, b, c), running


def items(root):
    return installer.downloads(root)


def test_order_keeps_user_order_and_appends_new(setup):
    q, root, *_ = setup
    # before the user reorders: Steam-like (running, paused, queued)
    assert [d.appid for d in q.order(items(root))] == [3, 1, 2]
    q.move(items(root), 2, -2)
    assert [d.appid for d in q.order(items(root))] == [2, 3, 1]
    manifest(root, 4, "Delta", 1026)
    assert [d.appid for d in q.order(items(root))] == [2, 3, 1, 4]  # new download at the end
    q.move(items(root), 4, 99)  # moving past the end is harmless
    assert [d.appid for d in q.order(items(root))] == [2, 3, 1, 4]


def test_apply_pauses_all_but_the_top(setup):
    q, root, client, (a, b, c), running = setup
    ordered = q.move(items(root), 3, -2)  # Charlie (paused) to the top
    assert q.needs_apply(ordered)
    result = q.apply(ordered)
    assert result.ok and "Charlie" in result.message
    assert not flags(c) & STATE_UPDATE_PAUSED  # top downloads
    assert flags(a) & STATE_UPDATE_PAUSED and flags(b) & STATE_UPDATE_PAUSED
    assert flags(a) & 1026 == 1026  # still wanted, only waiting
    assert client.calls == ["shutdown", "start_silent"]
    assert not q.needs_apply(q.order(items(root)))


def test_never_restarts_steam_during_a_game(setup):
    q, root, client, *_ = setup
    q.games_running = lambda: {620}
    result = q.apply(q.order(items(root)))
    assert not result.ok and "game" in result.message and client.calls == []


def test_cancel_new_install_deletes_everything(setup):
    q, root, client, (a, b, c), running = setup
    game = root / "steamapps/common/Bravo"
    (game / "data").mkdir(parents=True)
    (root / "steamapps/downloading/2").mkdir(parents=True)
    bravo = next(d for d in items(root) if d.appid == 2)
    result = q.cancel(bravo)
    assert result.ok and "deleted" in result.message
    assert not b.exists() and not game.exists() and not (root / "steamapps/downloading/2").exists()
    assert 2 not in q.saved_order()


def test_cancel_update_keeps_the_game(setup):
    q, root, client, (a, b, c), running = setup
    upd = manifest(root, 5, "Echo", 4 | 1026, size=5000)  # installed, update running
    game = root / "steamapps/common/Echo"
    game.mkdir(parents=True)
    (game / "game.bin").write_text("installed")
    partial = root / "steamapps/downloading/5"
    partial.mkdir(parents=True)
    echo = next(d for d in items(root) if d.appid == 5)
    assert echo.is_update
    result = q.cancel(echo)
    assert result.ok and "installed game stays" in result.message
    assert (game / "game.bin").exists() and upd.exists()
    assert not partial.exists()
    assert flags(upd) & STATE_UPDATE_PAUSED  # Steam doesn't just start it again
    assert client.calls == ["shutdown", "start_silent"]


def test_cancel_refused_during_a_game(setup):
    q, root, client, *_ = setup
    q.games_running = lambda: {1}
    assert not q.cancel(items(root)[0]).ok and client.calls == []


# --- tab -----------------------------------------------------------------------------

from gamingcrypt.ui import downloads_tab  # noqa: E402
from gamingcrypt.ui.downloads_tab import DownloadsTab  # noqa: E402
from tests.fakes import FakeService  # noqa: E402

A = Download(1, "Alpha", "downloading", 100, 1000, False)
B = Download(2, "Bravo", "paused", 0, 1000, False)
C = Download(3, "Charlie", "queued", 0, 1000, True)


class QueueService(FakeService):
    def __init__(self):
        super().__init__()
        self.list = [A, B, C]
        self.applied = []
        self.cancelled = []
        self.needs = False

    def downloads(self):
        return list(self.list)

    def move_download(self, appid, delta):
        ids = [d.appid for d in self.list]
        i = ids.index(appid)
        item = self.list.pop(i)
        self.list.insert(max(0, min(len(self.list), i + delta)), item)
        return list(self.list)

    def queue_needs_apply(self, items):
        return self.needs

    def apply_download_order(self, items):
        self.applied.append([d.appid for d in items])
        return InstallResult(True, f"Downloading {items[0].name} first")

    def cancel_download(self, d):
        self.cancelled.append(d.appid)
        self.list = [x for x in self.list if x.appid != d.appid]
        return InstallResult(True, f"Cancelled {d.name} and deleted its files")


def queue_tab(qtbot, monkeypatch):
    monkeypatch.setattr(downloads_tab, "APPLY_DELAY_MS", 10)
    service = QueueService()
    tab = DownloadsTab(service)
    tab.timer.stop()
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: len(tab.rows) == 3)
    return tab, service


def test_rows_have_order_controls_and_waiting_state(qtbot, monkeypatch):
    tab, service = queue_tab(qtbot, monkeypatch)
    top, second = tab.rows[1], tab.rows[2]
    assert not top.up_button.isEnabled() and not tab.rows[3].down_button.isEnabled()
    assert "Waiting" in second.state.text()  # paused because it's not at the top
    assert "Downloading" in top.state.text()


def test_move_to_top_applies_after_a_moment(qtbot, monkeypatch):
    tab, service = queue_tab(qtbot, monkeypatch)
    tab.rows[3].up_button.click()
    tab.rows[3].up_button.click()  # several quick taps ...
    assert [d.appid for d in tab.items] == [3, 1, 2]
    assert tab.list.indexOf(tab.rows[3]) == 0
    qtbot.waitUntil(lambda: bool(service.applied))
    assert service.applied == [[3, 1, 2]]  # ... one restart
    qtbot.waitUntil(lambda: "Charlie first" in tab.message.text())


def test_cancel_needs_two_taps(qtbot, monkeypatch):
    tab, service = queue_tab(qtbot, monkeypatch)
    row = tab.rows[2]
    row.cancel_button.click()
    assert service.cancelled == [] and row.cancel_button.text() == "Sure?"
    row.cancel_button.click()
    qtbot.waitUntil(lambda: service.cancelled == [2])
    qtbot.waitUntil(lambda: 2 not in tab.rows)
    assert "deleted" in tab.message.text()


def test_automatic_apply_is_limited_if_steam_ignores_it(qtbot, monkeypatch):
    tab, service = queue_tab(qtbot, monkeypatch)
    service.needs = True  # Steam keeps running the "wrong" download
    for _ in range(6):
        tab.refresh()
        qtbot.waitUntil(lambda: not tab.loading and not tab.applying)
        qtbot.wait(30)
    assert len(service.applied) == downloads_tab.MAX_AUTO_APPLY
    assert "doesn't follow the order" in tab.message.text()


def test_nothing_downloaded_yet_reads_naturally():
    from gamingcrypt.ui.downloads_tab import describe

    assert describe(Download(1, "G", "queued", 0, 2 * 1024**3, False)) == "Install · Queued · 0 B of 2.0 GB"

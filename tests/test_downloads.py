import pytest

from gamingcrypt.steam import installer, vdf
from gamingcrypt.steam.installer import Download, classify
from gamingcrypt.ui import downloads_tab
from gamingcrypt.ui.downloads_tab import DownloadsTab, describe
from gamingcrypt.ui.shell import Shell
from tests.fakes import FakeService


def manifest(folder, appid, name, flags, done=0, total=0, size=0):
    path = folder / "steamapps" / f"appmanifest_{appid}.acf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vdf.dumps({"AppState": {"appid": str(appid), "name": name, "StateFlags": str(flags),
                                            "BytesDownloaded": str(done), "BytesToDownload": str(total),
                                            "SizeOnDisk": str(size)}}))


@pytest.mark.parametrize("flags,done,total,expected", [
    (4, 0, 0, "installed"),
    (1026, 0, 0, "queued"),
    (1026, 50, 100, "downloading"),
    (6, 0, 0, "queued"),                      # installed, update waiting
    (4 | 2 | (1 << 20), 10, 100, "downloading"),
    (1026 | 512, 10, 100, "paused"),
    (0, 0, 0, "other"),
])
def test_classify(flags, done, total, expected):
    assert classify(flags, done, total) == expected


def test_downloads_across_libraries(steam_root, tmp_path):
    drive = tmp_path / "crypt" / "SteamLibrary"
    manifest(drive, 1, "Queued Game", 1026)
    manifest(steam_root, 2, "Running Game", 1026 | (1 << 20), 300, 1000)
    manifest(drive, 3, "Paused Game", 1026 | 512, 10, 100)
    manifest(steam_root, 4, "Done Game", 4, 100, 100)
    manifest(steam_root, 5, "Proton 9.0", 1026)  # tools are not listed
    items = installer.downloads(steam_root)
    # fixture: Hades (flags 6) has an update waiting
    assert [(d.name, d.state) for d in items] == [
        ("Running Game", "downloading"), ("Paused Game", "paused"),
        ("Hades", "queued"), ("Queued Game", "queued")]
    hades = next(d for d in items if d.name == "Hades")
    assert hades.is_update and not items[-1].is_update
    assert items[0].percent == 30.0
    assert installer.downloads(None) == []


def test_describe():
    assert describe(Download(1, "G", "downloading", 512 * 1024**2, 2 * 1024**3, False)) == \
        "Install · Downloading · 512.0 MB of 2.0 GB"
    assert describe(Download(1, "G", "queued", 0, 0, True)) == "Update · Queued"


class DownloadService(FakeService):
    def __init__(self, steps):
        super().__init__()
        self.steps = steps

    def downloads(self):
        return self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]


def test_tab_updates_rows_and_badge(qtbot):
    running = Download(2, "Running", "downloading", 250, 1000, False)
    queued = Download(1, "Queued", "queued", 0, 0, False)
    service = DownloadService([[queued, running], [Download(2, "Running", "downloading", 750, 1000, False)], []])
    tab = DownloadsTab(service)
    tab.timer.stop()  # step through the scripted states one refresh at a time
    shell = Shell({"Downloads": tab})
    qtbot.addWidget(shell)
    qtbot.waitUntil(lambda: shell.tab_buttons["Downloads"].text() == "Downloads (2)")
    assert set(tab.rows) == {1, 2} and tab.empty.isHidden()
    tab.refresh()
    qtbot.waitUntil(lambda: set(tab.rows) == {2} and tab.rows[2].percent.text() == "75.0%")
    tab.refresh()
    qtbot.waitUntil(lambda: tab.rows == {})
    assert not tab.empty.isHidden()
    assert shell.tab_buttons["Downloads"].text() == "Downloads"


def test_shell_has_downloads_tab(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    assert list(shell.tab_buttons)[:2] == ["Games", "Downloads"]


# --- speeds, disk usage and smooth progress ---------------------------------------

from pathlib import Path  # noqa: E402

from gamingcrypt.system import io_stats  # noqa: E402
from gamingcrypt.system.io_stats import IoSample  # noqa: E402


def test_net_and_disk_counters(tmp_path):
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / "net/dev").write_text(
        "Inter-|   Receive\n face |bytes    packets\n"
        "    lo:  999999    3185    0    0    0     0          0         0   268400\n"
        " wlan0: 1000    269815    0   11    0     0          0         0 260625650\n"
        "  eth0: 500    1 0 0 0 0 0 0 0\n")
    (proc / "diskstats").write_text(" 253 1 dm-1 73270 0 7262354 70445 60072 0 2048 80198 0 43790\n")
    assert io_stats.net_rx_bytes(proc) == 1500  # loopback ignored
    assert io_stats.disk_written_bytes("dm-1", proc) == 2048 * 512
    assert io_stats.disk_written_bytes("sda", proc) is None


def test_real_counters():
    project = str(Path(__file__).resolve().parent)  # on a real disk (the test HOME is on tmpfs)
    sample = io_stats.sample(project)
    assert sample.net_rx >= 0 and sample.free > 0
    assert io_stats.block_device(project) is not None
    assert io_stats.block_device("/does/not/exist") is None


def test_rate():
    a, b = IoSample(10.0, 1000, 0, 5), IoSample(12.0, 5000, 2048, 5)
    assert io_stats.rate(a, b, "net_rx") == 2000 and io_stats.rate(a, b, "disk_written") == 1024
    assert io_stats.rate(None, b, "net_rx") is None
    assert io_stats.rate(b, a, "net_rx") is None  # time went backwards / counter reset


def test_formatting():
    assert downloads_tab.format_rate(None) == "-"
    assert downloads_tab.format_rate(500) == "500 B/s"
    assert downloads_tab.format_rate(12.5 * 1024**2) == "12.5 MB/s"
    assert downloads_tab.format_eta(30) == "<1 min left"
    assert downloads_tab.format_eta(600) == "10 min left"
    assert downloads_tab.format_eta(5400) == "1.5 h left"


class StatsService(FakeService):
    def __init__(self, items, samples):
        super().__init__()
        self.items, self.samples = items, samples

    def downloads(self):
        return self.items[0] if len(self.items) == 1 else self.items.pop(0)

    def io_sample(self, library):
        self.library = library
        return self.samples.pop(0) if len(self.samples) > 1 else self.samples[0]


MB = 1024**2


def test_stats_line_and_smooth_progress(qtbot):
    d = lambda done: Download(7, "Big Game", "downloading", done, 1000 * MB, False, "/mnt/games")  # noqa: E731
    service = StatsService(items=[[d(100 * MB)]], samples=[
        IoSample(0.0, 0, 0, 50 * 1024**3), IoSample(1.0, 10 * MB, 20 * MB, 50 * 1024**3)])
    tab = DownloadsTab(service)
    tab.timer.stop()
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: 7 in tab.rows)
    tab.show_downloads([d(100 * MB)], IoSample(0.0, 0, 0, 50 * 1024**3))
    assert service.library == "/mnt/games"  # disk usage of the drive the game goes to
    tab.show_downloads([d(100 * MB)], IoSample(1.0, 10 * MB, 20 * MB, 50 * 1024**3))
    row = tab.rows[7]
    assert tab.stats.text() == "↓ 10.0 MB/s   ·   Disk 20.0 MB/s   ·   50.0 GB free"
    # Steam still says 100 MB, but 10 MB more arrived -> 11 % instead of a frozen 10 %
    assert row.percent.text() == "11.0%"
    assert "10.0 MB/s" in row.state.text() and "min left" in row.state.text()
    # Steam's counter catches up -> re-synced, never jumps backwards
    tab.show_downloads([d(105 * MB)], IoSample(2.0, 20 * MB, 30 * MB, 50 * 1024**3))
    assert row.percent.text() == "11.0%"
    tab.show_downloads([d(105 * MB)], IoSample(3.0, 40 * MB, 30 * MB, 50 * 1024**3))
    assert row.percent.text() == "12.5%"


def test_stats_hidden_without_active_download(qtbot):
    queued = Download(1, "Q", "queued", 0, 0, False, "/x")
    service = StatsService(items=[[queued]], samples=[IoSample(0.0, 0, 0, 1)])
    tab = DownloadsTab(service)
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: 1 in tab.rows)
    assert tab.stats.isHidden() and service.library is None

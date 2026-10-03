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


def test_tab_updates_rows_and_badge(qtbot, monkeypatch):
    monkeypatch.setattr(downloads_tab, "REFRESH_MS", 20)
    running = Download(2, "Running", "downloading", 250, 1000, False)
    queued = Download(1, "Queued", "queued", 0, 0, False)
    service = DownloadService([[queued, running], [Download(2, "Running", "downloading", 750, 1000, False)], []])
    tab = DownloadsTab(service)
    shell = Shell({"Downloads": tab})
    qtbot.addWidget(shell)
    qtbot.waitUntil(lambda: shell.tab_buttons["Downloads"].text() == "Downloads (2)")
    assert set(tab.rows) == {1, 2} and tab.empty.isHidden()
    qtbot.waitUntil(lambda: set(tab.rows) == {2} and tab.rows[2].percent.text() == "75%", timeout=3000)
    qtbot.waitUntil(lambda: tab.rows == {}, timeout=3000)
    assert not tab.empty.isHidden()
    assert shell.tab_buttons["Downloads"].text() == "Downloads"


def test_shell_has_downloads_tab(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    assert list(shell.tab_buttons)[:2] == ["Games", "Downloads"]

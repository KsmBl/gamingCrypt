from gamingcrypt.steam import installer, vdf
from gamingcrypt.steam.installer import Download, InstallProgress
from gamingcrypt.system.io_stats import IoSample
from gamingcrypt.ui.downloads_tab import DownloadsTab
from gamingcrypt.ui.progress_estimate import ProgressEstimator
from tests.fakes import FakeService

MB, GB = 1024**2, 1024**3


def test_estimator():
    est = ProgressEstimator()
    assert est.estimate(1, 0, 1000, None) == 0  # no counters -> Steam's value
    assert est.estimate(1, 0, 0, 50) == 0  # unknown size
    assert est.estimate(1, 0, 1000, 100) == 0  # first sample = baseline
    assert est.estimate(1, 0, 1000, 400) == 300  # Steam still says 0, 300 bytes arrived
    assert est.estimate(1, 200, 1000, 450) == 300  # Steam catches up (200) -> re-sync, never backwards
    assert est.estimate(1, 200, 1000, 700) == 450
    assert est.estimate(1, 200, 1000, 99999) == 1000  # capped at the total
    est.forget(1)
    assert est.estimate(1, 0, 1000, 5) == 0
    assert ProgressEstimator().estimate(2, 0, 1000, 300, since=100) == 200  # first interval counts


def test_estimator_ignores_traffic_while_another_game_downloads():
    est = ProgressEstimator()
    est.estimate(1, 0, 1000, 0)
    assert est.estimate(1, 0, 1000, 100) == 100
    est.reset(1, 600)  # 500 bytes went to another game
    assert est.estimate(1, 0, 1000, 650) == 150


def write(folder, appid, flags, done, total, staged=0, to_stage=0):
    path = folder / "steamapps" / f"appmanifest_{appid}.acf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(vdf.dumps({"AppState": {"appid": str(appid), "name": f"G{appid}", "StateFlags": str(flags),
                                            "BytesDownloaded": str(done), "BytesToDownload": str(total),
                                            "BytesStaged": str(staged), "BytesToStage": str(to_stage)}}))


def test_staging_counters_are_used(steam_root):
    write(steam_root, 7, 1026, 0, 1000, staged=500, to_stage=2000)  # download counter stuck, staging moved
    write(steam_root, 8, 1026, 0, 0, staged=30, to_stage=120)  # only staging numbers known
    items = {d.appid: d for d in installer.downloads(steam_root)}
    assert (items[7].downloaded, items[7].total) == (250, 1000)
    assert (items[8].downloaded, items[8].total) == (30, 120)
    assert installer.progress(steam_root, 7).downloaded == 250


class Service(FakeService):
    def __init__(self, items):
        super().__init__()
        self.items = items

    def downloads(self):
        return self.items


def tab_for(qtbot, items):
    tab = DownloadsTab(Service(items))
    tab.timer.stop()
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: not tab.loading)
    return tab


def test_queued_but_receiving_shows_moving_percentage(qtbot):
    """The reported bug: Steam keeps BytesDownloaded at 0 -> stayed at 0.0 % forever."""
    stuck = Download(7, "ROUNDS", "queued", 0, 4 * GB, False, "/mnt")
    tab = tab_for(qtbot, [stuck])
    tab.show_downloads([stuck], IoSample(0.0, 0, None, 100 * GB))
    tab.show_downloads([stuck], IoSample(1.0, 40 * MB, None, 100 * GB))
    tab.show_downloads([stuck], IoSample(2.0, 410 * MB, None, 100 * GB))
    row = tab.rows[7]
    assert row.percent.text() == "10.0%"  # 410 MB of 4 GB
    assert "Downloading" in row.state.text() and "MB/s" in row.state.text()


def test_queued_and_idle_stays_queued(qtbot):
    waiting = Download(7, "ROUNDS", "queued", 0, 4 * GB, False, "/mnt")
    tab = tab_for(qtbot, [waiting])
    tab.show_downloads([waiting], IoSample(0.0, 0, None, 1))
    tab.show_downloads([waiting], IoSample(1.0, 10 * 1024, None, 1))  # a few KB: not a download
    assert tab.rows[7].percent.text() == "0.0%" and "Queued" in tab.rows[7].state.text()


def test_only_one_download_gets_the_network_bytes(qtbot):
    a = Download(1, "A Game", "queued", 0, 1 * GB, False, "/mnt")
    b = Download(2, "B Game", "queued", 0, 1 * GB, False, "/mnt")
    tab = tab_for(qtbot, [a, b])
    tab.show_downloads([a, b], IoSample(0.0, 0, None, 1))
    tab.show_downloads([a, b], IoSample(1.0, 100 * MB, None, 1))
    assert tab.rows[1].percent.text() != "0.0%"
    assert tab.rows[2].percent.text() == "0.0%"


def test_game_page_percentage_moves_too(qtbot):
    from tests.fakes import SilentInstallService
    from gamingcrypt.ui import game_detail
    from gamingcrypt.ui.games_tab import GamesTab

    service = SilentInstallService(progress_steps=[InstallProgress("downloading", 0, 4 * GB)])
    # the page measures once when it opens, then on every poll
    samples = iter([IoSample(0.0, 0, None, None), IoSample(1.0, 0, None, None), IoSample(2.0, 820 * MB, None, None)])
    service.io_sample = lambda library: next(samples)
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.games.update({g.appid: g for g in service.games})
    service.installs.append(292030)
    tab.open_game(292030)
    page = tab.currentWidget()
    page._progress_timer.stop()
    page.poll_progress()
    page.poll_progress()
    assert page.status.text().startswith("Downloading 20% · 820.0 MB of 4.0 GB")

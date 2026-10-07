"""Settings -> Storage: space per game, shader caches, leftovers of cancelled downloads."""

import types

import pytest

from gamingcrypt.steam import storage


def fill(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


@pytest.fixture
def steam(steam_root):
    extra = steam_root.parent / "crypt" / "SteamLibrary" / "steamapps"
    fill(steam_root / "steamapps/shadercache/620/fozpipelines/a.foz", 3000)
    fill(extra / "shadercache/1145360/b.foz", 1000)
    fill(extra / "downloading/999/part.bin", 5000)  # cancelled: no longer queued
    fill(extra / "temp/998/x", 200)
    fill(steam_root / "steamapps/compatdata/620/pfx/drive_c/save.dat", 100)  # a save game!
    return steam_root, extra


def test_scan(steam):
    root, extra = steam
    report = storage.scan(root)
    names = [g.name for g in report.games]
    assert names[0] == "Portal 2" and "Hades" in names  # biggest first
    portal = report.games[0]
    assert portal.game_bytes == 12_000_000_000 and portal.shader_bytes == 3000
    assert report.shader_bytes == 4000
    assert sorted(p.name for p in report.leftovers) == ["998", "999"] and report.leftover_bytes == 5200
    assert {lib.path for lib in report.libraries} >= {root, extra.parent}  # the unmounted one is skipped
    assert all(lib.total >= lib.free > 0 for lib in report.libraries)


def test_queued_download_is_not_a_leftover(steam):
    root, extra = steam
    from tests.conftest import write_manifest

    write_manifest(extra.parent, 999, "Queued Game", flags=1026)  # update queued
    report = storage.scan(root)
    assert [p.name for p in report.leftovers] == ["998"]


def test_freeing_space_keeps_saves(steam):
    root, extra = steam
    report = storage.scan(root)
    portal = next(g for g in report.games if g.appid == 620)
    assert storage.clear_shader_cache(portal) == 3000
    assert not (root / "steamapps/shadercache/620").exists()
    assert storage.clear_leftovers(report) == 5200
    assert not (extra / "downloading/999").exists() and not (extra / "temp/998").exists()
    assert (root / "steamapps/compatdata/620/pfx/drive_c/save.dat").exists()  # never touched
    assert storage.scan(None).games == []


# --- UI ---------------------------------------------------------------------------------

def page_for(qtbot, root, running=frozenset()):
    from gamingcrypt.ui.storage_page import StoragePage

    uninstalled = []
    service = types.SimpleNamespace(root=root, uninstall_game=lambda appid: uninstalled.append(appid) or
                                    types.SimpleNamespace(ok=True, message=""))
    page = StoragePage(lambda: service, games_running=lambda: set(running))
    qtbot.addWidget(page)
    page.show()
    page.refresh()
    qtbot.waitUntil(lambda: page.report is not None and not page.busy)
    return page, uninstalled


def test_storage_page(qtbot, steam):
    root, extra = steam
    page, uninstalled = page_for(qtbot, root)
    from gamingcrypt.ui.game_widgets import format_size

    assert page.shaders_button.isVisible() and f"({format_size(4000)})" in page.shaders_button.text()
    assert page.leftovers_button.isVisible()
    page.leftovers_button.click()
    qtbot.waitUntil(lambda: "Freed" in page.status.text())
    assert not page.leftovers_button.isVisible() and not (extra / "downloading/999").exists()
    text, shaders, remove = page.rows[620]
    assert "Portal 2" in text.text() and shaders.isVisible()
    from gamingcrypt.ui.modal import open_modal

    remove.click()
    question = open_modal(page.window(), on_screen=False)
    assert uninstalled == [] and "Uninstall Portal 2?" in question.content.question.text()
    question.content.action_button.click()
    qtbot.waitUntil(lambda: uninstalled == [620])
    qtbot.waitUntil(lambda: "Portal 2 uninstalled" in page.status.text())


def test_nothing_deleted_while_a_game_runs(qtbot, steam):
    root, _ = steam
    page, _ = page_for(qtbot, root, running={620})
    page.clear_all_shaders()
    assert "Close your game first" in page.status.text()
    assert (root / "steamapps/shadercache/620").exists()


def test_settings_has_storage(qtbot, steam):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    root, _ = steam
    service = types.SimpleNamespace(root=root)
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, steam_service=service)
    qtbot.addWidget(tab)
    tab.sub_buttons["Storage"].click()
    qtbot.waitUntil(lambda: tab.storage_page.report is not None)
    assert 620 in tab.storage_page.rows

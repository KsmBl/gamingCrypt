import os

# Always offscreen: a desktop session's own QT_QPA_PLATFORM (e.g. "wayland;xcb") would open real
# windows that steal focus while the tests run - and make focus-dependent tests flaky.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402


def write_manifest(library: Path, appid: int, name: str, last_updated: int = 1700000000,
                   size: int = 1000, flags: int = 4) -> None:
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{appid}.acf").write_text(f'''"AppState"
{{
\t"appid"\t\t"{appid}"
\t"name"\t\t"{name}"
\t"StateFlags"\t\t"{flags}"
\t"installdir"\t\t"{name.replace(' ', '')}"
\t"LastUpdated"\t\t"{last_updated}"
\t"SizeOnDisk"\t\t"{size}"
}}
''')


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Never look at the real ~/GamingCrypt.vc or config while testing."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # never touch the real runtime / state / config / cache folders (e.g. a "next-mode" request)
    for var, sub in (("XDG_RUNTIME_DIR", "run"), ("XDG_STATE_HOME", "state"),
                     ("XDG_CONFIG_HOME", "config"), ("XDG_CACHE_HOME", "cache")):
        monkeypatch.setenv(var, str(tmp_path / "isolated-xdg" / sub))
    monkeypatch.delenv("GAMINGCRYPT_SESSION", raising=False)
    return home


@pytest.fixture(autouse=True)
def no_real_controllers(monkeypatch):
    """UI tests must not pick up (or grab!) a controller plugged into the dev machine."""
    from gamingcrypt.input import evdev

    monkeypatch.setattr(evdev, "find_gamepads", lambda *a, **k: [])


@pytest.fixture
def steam_root(tmp_path) -> Path:
    """A fake Steam install with a second library folder (the 'encrypted drive')."""
    root = tmp_path / "Steam"
    extra = tmp_path / "crypt" / "SteamLibrary"
    write_manifest(root, 620, "Portal 2", last_updated=1600000000, size=12_000_000_000)
    write_manifest(root, 228980, "Steamworks Common Redistributables")
    write_manifest(root, 1493710, "Proton Experimental")
    write_manifest(extra, 1145360, "Hades", last_updated=1700000000, flags=6)
    (root / "steamapps" / "libraryfolders.vdf").write_text(f'''"libraryfolders"
{{
\t"0"
\t{{
\t\t"path"\t\t"{root}"
\t\t"apps" {{ "620" "1" }}
\t}}
\t"1"
\t{{
\t\t"path"\t\t"{extra}"
\t}}
\t"2"
\t{{
\t\t"path"\t\t"{tmp_path / 'unmounted'}"
\t}}
}}
''')
    cfg = root / "userdata" / "12345" / "config"
    cfg.mkdir(parents=True)
    (cfg / "localconfig.vdf").write_text('''"UserLocalConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"apps"
\t\t\t\t{
\t\t\t\t\t"620" { "LastPlayed" "1650000000" "Playtime" "1234" }
\t\t\t\t\t"1145360" { "LastPlayed" "1710000000" "Playtime" "60" }
\t\t\t\t}
\t\t\t}
\t\t}
\t}
}
''')
    return root


@pytest.fixture(autouse=True)
def no_real_battery(monkeypatch):
    """The dev machine's battery must not pop up warnings in UI tests."""
    from gamingcrypt.app import MainWindow

    monkeypatch.setattr(MainWindow, "battery_reader", staticmethod(lambda: None))


@pytest.fixture(autouse=True)
def no_welcome_screens(monkeypatch):
    """The first-start tour would cover every other UI test."""
    from gamingcrypt.app import MainWindow

    monkeypatch.setattr(MainWindow, "welcome_enabled", False)


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """No GitHub access from UI tests."""
    from gamingcrypt.app import MainWindow

    monkeypatch.setattr(MainWindow, "update_check_enabled", False)


@pytest.fixture(autouse=True)
def controller_not_scrolling():
    """A test that ends while the navigator glides must not leave "the controller scrolls" set."""
    yield
    from gamingcrypt.ui.widgets import FoldingHeader

    FoldingHeader.programmatic = False


@pytest.fixture(autouse=True)
def no_store_lookups(request, monkeypatch):
    """The Games tab asks the store for genres in the background: never in tests (it would go
    online and keep redrawing the list) - except where a test is about it (@pytest.mark.store_facts)."""
    if request.node.get_closest_marker("store_facts") is None:
        from gamingcrypt.ui.games_tab import GamesTab

        monkeypatch.setattr(GamesTab, "fill_facts", lambda self: None)

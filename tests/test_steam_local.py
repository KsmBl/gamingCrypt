import subprocess

import pytest

from gamingcrypt.steam import library, vdf
from gamingcrypt.steam.client import SteamClient, detect_command


# --- vdf ---------------------------------------------------------------------

def test_vdf_nested_and_comments():
    data = vdf.loads('''
    // comment
    "a" { "b" "1"  "c" { "d" "x y" } }
    unquoted value
    "esc" "say \\"hi\\"\\n"
    ''')
    assert data == {"a": {"b": "1", "c": {"d": "x y"}}, "unquoted": "value", "esc": 'say "hi"\n'}


@pytest.mark.parametrize("text", ['"a" {', '"a" }', '{', '"a" "b" "c"', '"unterminated'])
def test_vdf_errors(text):
    with pytest.raises(vdf.VDFError):
        vdf.loads(text)


def test_iget_case_insensitive():
    data = {"AppState": {"LastUpdated": "5"}}
    assert vdf.iget(data, "appstate", "lastupdated") == "5"
    assert vdf.iget(data, "AppState", "missing", default=0) == 0
    assert vdf.iget(data, "AppState", "LastUpdated", "deeper") is None


# --- library -----------------------------------------------------------------

def test_find_steam_root(steam_root, tmp_path):
    assert library.find_steam_root(str(steam_root)) == steam_root.resolve()
    assert library.find_steam_root(str(tmp_path / "nope")) is None
    home = tmp_path / "home"
    (home / ".local/share/Steam/steamapps").mkdir(parents=True)
    assert library.find_steam_root(home=home) == (home / ".local/share/Steam").resolve()


def test_library_folders(steam_root, tmp_path):
    folders = library.library_folders(steam_root)
    assert folders[0] == steam_root
    assert tmp_path / "crypt" / "SteamLibrary" in folders
    assert len(folders) == 3


def test_installed_games_filters_tools_and_reads_all_libraries(steam_root):
    games = {g.appid: g for g in library.installed_games(steam_root)}
    assert set(games) == {620, 1145360}
    portal = games[620]
    assert portal.name == "Portal 2" and portal.installed
    assert portal.size_on_disk == 12_000_000_000
    assert portal.last_updated == 1600000000
    assert portal.install_dir.endswith("steamapps/common/Portal2")
    assert not portal.update_pending
    assert games[1145360].update_pending
    assert "crypt" in games[1145360].library_path


def test_broken_manifest_is_skipped(steam_root):
    (steam_root / "steamapps" / "appmanifest_1.acf").write_text('"AppState" {')
    assert {g.appid for g in library.installed_games(steam_root)} == {620, 1145360}


def test_local_playtime(steam_root):
    playtime = library.local_playtime(steam_root)
    assert playtime[620] == {"playtime": 1234, "last_played": 1650000000}
    assert playtime[1145360]["playtime"] == 60


def test_is_game():
    assert library.is_game(620, "Portal 2")
    assert not library.is_game(1, "Proton 9.0")
    assert not library.is_game(1, "Steam Linux Runtime 3.0 (sniper)")


# --- client ------------------------------------------------------------------

class Recorder:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, cmd, **kw):
        if self.fail:
            raise FileNotFoundError
        self.calls.append(cmd)


def test_client_uris():
    rec = Recorder()
    client = SteamClient(["steam"], launcher=rec)
    assert client.play(620)
    client.install(620)
    client.uninstall(620)
    client.open_store(620)
    assert [c[1] for c in rec.calls] == [
        "steam://rungameid/620", "steam://install/620", "steam://uninstall/620", "steam://store/620",
    ]


def test_client_string_command_and_failure():
    client = SteamClient("flatpak run com.valvesoftware.Steam", launcher=Recorder(fail=True))
    assert client.command == ["flatpak", "run", "com.valvesoftware.Steam"]
    assert client.play(1) is False


def test_detect_command(monkeypatch):
    assert detect_command(lambda name: "/usr/bin/steam" if name == "steam" else None) == ["steam"]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "com.valvesoftware.Steam\n", ""))
    assert detect_command(lambda name: "/usr/bin/flatpak" if name == "flatpak" else None)[:2] == ["flatpak", "run"]
    assert detect_command(lambda name: None) == ["xdg-open"]

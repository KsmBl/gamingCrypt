"""The movie player: mpv through the game wrapper, asked over its IPC socket where it is."""

import json
import socket
import threading

import pytest

from gamingcrypt.movies import library, player


@pytest.fixture
def movie(tmp_path):
    (tmp_path / "Movies").mkdir()
    (tmp_path / "Movies" / "The Matrix (1999).mkv").write_bytes(b"v")
    return library.scan(tmp_path / "Movies")[0]


def test_command(movie, tmp_path):
    args = player.command(movie, tmp_path / "reaper", tmp_path / "mpv.sock", tmp_path / "input.conf", 0,
                          ("de", "en"))
    assert args[:4] == [str(tmp_path / "reaper"), "SteamLaunch", f"AppId={movie.appid}", "--"]
    assert args[4] == "mpv" and "--fs" in args and "--input-gamepad=no" in args  # GamingCrypt reads the pad
    assert "--volume=100" in args and "--volume-max=100" in args  # no volume of its own
    assert "--osc=no" in args and f"--script={player.TOUCH_SCRIPT}" in args  # big touch controls instead
    assert "--force-media-title=The Matrix" in args
    assert "--alang=de,en" in args and "--title=The Matrix" in args
    assert not any(a.startswith("--start") for a in args)
    assert args[-2:] == ["--", str(movie.path)]  # a name starting with "-" stays a file
    resumed = player.command(movie, tmp_path / "r", tmp_path / "s", tmp_path / "c", 3723.44)
    assert "--start=3723.4" in resumed


def test_launch(movie, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    started = []
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / player.SOCKET_NAME).write_text("old")  # left by a crashed player
    ok, message = player.launch(movie, tmp_path / "data", tmp_path / "logs", 60,
                                popen=lambda args, **kw: started.append((args, kw)), which=lambda n: "/usr/bin/mpv")
    assert ok and message == "Playing The Matrix"
    args, kw = started[0]
    assert "--start=60.0" in args and kw["start_new_session"] and (tmp_path / "logs" / "mpv.log").exists()
    assert (tmp_path / "data" / "reaper").exists()
    assert (tmp_path / "data" / "mpv-input.conf").read_text() == player.INPUT_CONF
    assert not (tmp_path / "run" / player.SOCKET_NAME).exists()


def test_launch_problems(movie, tmp_path):
    ok, message = player.launch(movie, tmp_path, tmp_path, which=lambda n: None)
    assert not ok and "mpv" in message
    movie.path.unlink()
    ok, message = player.launch(movie, tmp_path, tmp_path, which=lambda n: "/usr/bin/mpv")
    assert not ok and message == "The movie file is gone"

    def fails(*a, **k):
        raise OSError("no reaper")

    movie.path.write_bytes(b"v")
    ok, message = player.launch(movie, tmp_path, tmp_path, popen=fails, which=lambda n: "/usr/bin/mpv")
    assert not ok and "no reaper" in message


def test_no_volume_keys():
    conf = player.INPUT_CONF
    for key in ("VOLUME_UP", "VOLUME_DOWN", "MUTE", "WHEEL_UP", "WHEEL_DOWN", "9", "0", "m"):
        assert f"\n{key} ignore\n" in "\n" + conf
    assert "GAMEPAD" not in conf


def test_controller_buttons_become_player_commands():
    from gamingcrypt.input import evdev as e

    key = lambda code, value=1: player.remote_command(e.EV_KEY, code, value)  # noqa: E731
    assert key(e.BTN_SOUTH) == key(e.BTN_START) == "osd-msg cycle pause"
    assert key(e.BTN_EAST) == "quit"
    assert key(e.BTN_NORTH) == "osd-msg cycle sub" and key(e.BTN_WEST) == "osd-msg cycle audio"
    assert key(e.BTN_TL) == "osd-msg-bar add chapter -1" and key(e.BTN_TR) == "osd-msg-bar add chapter 1"
    assert key(e.BTN_SELECT) == "show-progress"
    assert key(e.BTN_SOUTH, 0) is None and key(e.BTN_SOUTH, 2) is None  # release, auto repeat
    hat = lambda code, value: player.remote_command(e.EV_ABS, code, value)  # noqa: E731
    assert hat(e.ABS_HAT0X, -1) == "osd-msg-bar seek -10" and hat(e.ABS_HAT0X, 1) == "osd-msg-bar seek 30"
    assert hat(e.ABS_HAT0Y, -1) == "osd-msg-bar seek 300" and hat(e.ABS_HAT0Y, 1) == "osd-msg-bar seek -300"
    assert hat(e.ABS_HAT0X, 0) is None and hat(e.ABS_X, 30000) is None


def test_send_a_command(tmp_path):
    sock = tmp_path / "mpv.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock))
    server.listen()
    got = []

    def serve():
        conn, _ = server.accept()
        with conn:
            got.append(conn.makefile().readline())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert player.send(sock, "osd-msg-bar seek 30")
    thread.join(2)
    server.close()
    assert got == ["osd-msg-bar seek 30\n"]
    assert not player.send(tmp_path / "nothing.sock", "quit")


class FakeMpv:
    """mpv's JSON IPC: events in between, replies carry the request id."""

    def __init__(self, path, values):
        self.values = values
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                request = json.loads(conn.makefile().readline())
                prop = request["command"][1]
                conn.sendall(b'{"event":"playback-restart"}\n')
                if prop in self.values:
                    reply = {"data": self.values[prop], "error": "success", "request_id": request["request_id"]}
                else:
                    reply = {"error": "property unavailable", "request_id": request["request_id"]}
                conn.sendall(json.dumps(reply).encode() + b"\n")

    def close(self):
        self.server.close()


def test_asks_mpv_where_it_is(tmp_path):
    sock = tmp_path / "mpv.sock"
    mpv = FakeMpv(sock, {"time-pos": 3723.5, "duration": 8160.0})
    try:
        assert player.query(sock, "time-pos") == 3723.5
        assert player.position(sock) == (3723.5, 8160.0)
    finally:
        mpv.close()


def test_unknown_length_and_no_player(tmp_path):
    sock = tmp_path / "mpv.sock"
    mpv = FakeMpv(sock, {"time-pos": 12})
    try:
        assert player.position(sock) == (12.0, 0.0)
    finally:
        mpv.close()
    assert player.position(tmp_path / "nothing.sock") is None
    still_loading = FakeMpv(tmp_path / "loading.sock", {})
    try:
        assert player.position(tmp_path / "loading.sock") is None
    finally:
        still_loading.close()


def test_socket_lives_in_the_runtime_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert player.socket_path() == tmp_path / player.SOCKET_NAME


def test_touch_script_is_there_and_shipped():
    import shutil
    import subprocess
    from pathlib import Path

    script = player.TOUCH_SCRIPT.read_text()
    assert 'add_forced_key_binding("MBTN_LEFT"' in script and '"absolute-percent"' in script
    for label in ("« 10", "10 »", "✕", "Subtitles", "Audio", "2x  ▶▶"):
        assert label in script
    assert "//" not in "".join(line.split("--")[0] for line in script.splitlines())  # LuaJIT: no //
    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert '"gamingcrypt.movies" = ["*.lua"]' in pyproject
    luajit = shutil.which("luajit")
    if luajit:
        assert subprocess.run([luajit, "-b", str(player.TOUCH_SCRIPT), "/dev/null"]).returncode == 0


def test_touch_mode_switch():
    import subprocess

    from gamingcrypt.system import gamescope_ctl

    calls = []

    def runner(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    assert gamescope_ctl.set_touch_mode(gamescope_ctl.TOUCH_LEFT_CLICK, runner)
    assert calls == [["xprop", "-root", "-f", "STEAM_TOUCH_CLICK_MODE", "32c", "-set", "STEAM_TOUCH_CLICK_MODE", "1"]]
    assert gamescope_ctl.TOUCH_PASSTHROUGH == 4  # the session's --default-touch-mode
    from gamingcrypt.session.mode import DEFAULT_ARGS

    assert f"--default-touch-mode {gamescope_ctl.TOUCH_PASSTHROUGH}" in DEFAULT_ARGS
    assert not gamescope_ctl.set_touch_mode(1, lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))


def test_touch_script_gestures_are_there():
    script = player.TOUCH_SCRIPT.read_text()
    assert '{complex = true}' in script  # finger down / up: holds and drags
    assert 'set_property_number("speed", 2)' in script  # hold: 2x like YouTube
    assert "SEEK_STREAK_S" in script and "DOUBLE_TAP_S" in script  # double tap, further taps add 10 s
    assert "DRAG_REST_S" in script  # gamescope's click mode lets go when the finger moves


def test_touch_script_has_a_speed_menu():
    script = player.TOUCH_SCRIPT.read_text()
    assert "SPEEDS = {0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2}" in script and "Playback speed" in script
    assert 'mp.set_property_number("speed", state.speed_before)' in script  # holding 2x goes back to it

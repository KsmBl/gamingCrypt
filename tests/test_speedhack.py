"""Game speed for Windows, Linux and Steam games: their clock (a preloaded library, as Cheat Engine's
speedhack), set from the quick menu while the game runs."""

import copy
import os
import shutil
import subprocess

import pytest

from gamingcrypt import speedhack

MEASURE = r"""
#include <stdio.h>
#include <time.h>
static double clock_of(int id){struct timespec t;clock_gettime(id,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(void){
  double m0=clock_of(CLOCK_MONOTONIC), w0=clock_of(CLOCK_REALTIME), last=m0; int back=0;
  for(int i=0;i<6;i++){struct timespec s={0,50000000};nanosleep(&s,0);double m=clock_of(CLOCK_MONOTONIC);back|=m<last;last=m;}
  struct timespec until; clock_gettime(CLOCK_MONOTONIC,&until); until.tv_nsec+=300000000;
  if(until.tv_nsec>=1000000000){until.tv_sec++;until.tv_nsec-=1000000000;}
  double s0=clock_of(CLOCK_REALTIME); clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&until,0);
  printf("%.2f %.2f %d %.2f\n",clock_of(CLOCK_MONOTONIC)-m0,clock_of(CLOCK_REALTIME)-w0,back,clock_of(CLOCK_REALTIME)-s0);
  return 0;}
"""


def test_env_for_games_and_steam(monkeypatch):
    monkeypatch.setattr(speedhack, "available", lambda machine=None: True)
    env = speedhack.game_env(620, {"LD_PRELOAD": "/usr/lib/mangohud.so"})
    libs = env["LD_PRELOAD"].split(":")
    assert libs[0] == "/usr/lib/mangohud.so" and libs[1:] == [str(p) for p in speedhack.LIBRARIES]  # both widths
    assert env["GAMINGCRYPT_SPEED_APPID"] == "620"
    again = speedhack.preload(env["LD_PRELOAD"])
    assert again == env["LD_PRELOAD"]  # not twice
    steam = speedhack.steam_env({"HOME": "/h"})
    assert steam["HOME"] == "/h" and "GAMINGCRYPT_SPEED_APPID" not in steam  # (Steam's games know their id)
    monkeypatch.setattr(speedhack, "available", lambda machine=None: False)
    assert speedhack.game_env(620) == {}
    assert speedhack.available("aarch64") is False


def test_speed_file(tmp_path):
    path = tmp_path / "speed"
    speedhack.set_speed(620, 2.5, path)
    assert path.read_text() == "2.5 620\n"
    speedhack.set_speed(620, 1.0, path)
    assert not path.exists()  # as it is: no file
    speedhack.clear(path)


def test_loaded(tmp_path):
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "maps").write_text("7f00 r-xp /x/libgamingcrypt-speed64.so\n")
    (tmp_path / "8").mkdir()
    (tmp_path / "8" / "maps").write_text("7f00 r-xp /usr/lib/libc.so.6\n")
    assert speedhack.loaded([8, 7], proc=tmp_path) and not speedhack.loaded([8, 9], proc=tmp_path)


@pytest.mark.skipif(not speedhack.available() or shutil.which("gcc") is None, reason="needs x86_64 and gcc")
def test_the_library_changes_the_games_clock(tmp_path):
    """The real thing: a program's monotonic clock at 2x (the wall clock not), and only for the game
    the speed is meant for; a sleep until a time on its clock lasts the real time that is."""
    source = tmp_path / "measure.c"
    source.write_text(MEASURE)
    program = tmp_path / "measure"
    subprocess.run(["gcc", "-O2", "-o", str(program), str(source)], check=True)
    shm = speedhack.speed_file()  # (the library reads it there)
    if shm.exists():
        pytest.skip("a game's speed is set right now")
    try:
        speedhack.set_speed(620, 2.0, shm)

        def run(appid):
            env = {**os.environ, **speedhack.game_env(appid)}
            done = subprocess.run([str(program)], env=env, capture_output=True, text=True, check=True)
            return [float(v) for v in done.stdout.split()]

        clock, wall, backwards, sleep = run(620)
        assert 1.1 < clock / wall < 2.6 and not backwards  # (6 x 50 ms real: twice that on its clock)
        assert sleep < 0.25  # 0.3 s on its clock: 0.15 s real
        clock, wall, _b, sleep = run(999)
        assert 0.8 < clock / wall < 1.2 and sleep > 0.25  # another game: as it is
    finally:
        speedhack.clear(shm)


# --- the quick menu ---------------------------------------------------------------------------

@pytest.fixture
def window(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    monkeypatch.setattr(speedhack, "available", lambda machine=None: True)
    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    return w


def test_quick_menu_speed_for_a_steam_game(qtbot, window, monkeypatch):
    from gamingcrypt.emulation.retroarch import SPEEDS
    from gamingcrypt.steam import running

    set_to = []
    monkeypatch.setattr(speedhack, "set_speed", lambda appid, speed, p=None: set_to.append((appid, speed)))
    monkeypatch.setattr(speedhack, "clear", lambda p=None: set_to.append("clear"))
    monkeypatch.setattr(running, "game_processes", lambda appid, proc=None: set())
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.live and menu.speed_row.isVisibleTo(menu) and not menu.state_row.isVisibleTo(menu)
    menu.speed.setValue(SPEEDS.index(2.0))
    assert "clock" in menu.status.text()  # no restart: its clock
    menu.close_menu()
    assert set_to == [(620, 2.0)] and window.live_speeds == {620: 2.0}
    window.toggle_quick_menu()
    assert menu.speed_value.text() == "2x"  # (as it runs)
    menu.close_menu()
    window.game_over(620)
    assert set_to[-1] == "clear" and window.live_speeds == {}  # the next game starts as it is


def test_no_speed_without_a_game_or_for_a_movie(qtbot, window):
    window.toggle_quick_menu()
    assert not window.quick_menu.live and not window.quick_menu.speed_row.isVisibleTo(window.quick_menu)
    assert window.live_speed_of(None) is None


def test_steam_gets_it_from_here(monkeypatch):
    from gamingcrypt.steam.client import SteamClient

    monkeypatch.setattr(speedhack, "available", lambda machine=None: True)
    calls = []
    SteamClient(["steam"], launcher=lambda cmd, **kw: calls.append(kw.get("env"))).play(620)
    assert str(speedhack.LIBRARIES[0]) in calls[0]["LD_PRELOAD"]
    SteamClient("flatpak run com.valvesoftware.Steam", launcher=lambda cmd, **kw: calls.append(kw.get("env"))).play(620)
    assert calls[-1] is None  # (Flatpak's sandbox: its games can't reach the libraries)

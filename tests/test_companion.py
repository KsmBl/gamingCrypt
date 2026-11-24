"""A game's companion (gamingcrypt-companion.sh in its folder): runs only while the game does."""

import time

from gamingcrypt.companion import SCRIPT, Companions


def wait_for(check, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_no_script_nothing_runs(tmp_path):
    companions = Companions()
    assert not companions.start(7, tmp_path, tmp_path / "logs")
    assert not companions.running(7)
    companions.stop(7)  # (nothing to end)


def test_runs_with_the_game_and_ends_with_it(tmp_path):
    game = tmp_path / "GTA4"
    game.mkdir()
    # it learns about its game, and may still tidy up when it's ended (the triggers off)
    (game / SCRIPT).write_text(
        'echo "app $GAMINGCRYPT_APPID in $GAMINGCRYPT_GAME_DIR from $PWD"\n'
        'trap \'echo tidied > "$GAMINGCRYPT_GAME_DIR/tidied"; exit 0\' TERM\n'
        'while :; do sleep 0.05; done\n')
    logs = tmp_path / "logs"
    companions = Companions()
    assert companions.start(42, game, logs)
    assert companions.running(42)
    assert wait_for(lambda: "app 42" in (logs / "companion-42.log").read_text())
    assert f"in {game} from {game}" in (logs / "companion-42.log").read_text()
    companions.stop(42)
    assert not companions.running(42)
    assert (game / "tidied").read_text() == "tidied\n"  # ended with TERM, not killed outright


def test_one_that_wont_end_is_killed(tmp_path, monkeypatch):
    from gamingcrypt import companion

    monkeypatch.setattr(companion, "STOP_WAIT_S", 0.2)
    (tmp_path / SCRIPT).write_text("trap '' TERM\nwhile :; do sleep 0.05; done\n")
    companions = Companions()
    companions.start(1, tmp_path, tmp_path / "logs")
    started = time.monotonic()
    companions.stop()  # every one (GamingCrypt closing)
    assert not companions.running(1) and time.monotonic() - started < 3


def test_a_new_start_replaces_the_old_one(tmp_path):
    (tmp_path / SCRIPT).write_text("while :; do sleep 0.05; done\n")
    companions = Companions()
    companions.start(5, tmp_path, tmp_path / "logs")
    first = companions._running[5]
    companions.start(5, tmp_path, tmp_path / "logs")
    assert first.poll() is not None and companions.running(5)
    companions.stop()

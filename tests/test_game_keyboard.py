"""The on-screen keyboard over a game: typed through a virtual keyboard, steered with the
controller (which the game doesn't get meanwhile)."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.input import evdev as e
from gamingcrypt.input import virtual_keyboard as vk
from gamingcrypt.input.profile import default_profile
from gamingcrypt.input.remapper import Remapper
from tests.test_input import AXES, BUILT_IN, KEYS, FakeVirtual, PipePad, wait_until


def keys_of(events):
    return [(code, value) for kind, code, value in events if kind == e.EV_KEY]


def typed(text):
    virtual = FakeVirtual()
    board = vk.VirtualKeyboard(make_uinput=lambda: virtual, pause=lambda s: None)
    board.insert(text)
    return keys_of(virtual.got), board


def test_characters_become_key_presses_with_shift_where_needed():
    got, _board = typed("aZ!")
    assert got == [(30, 1), (30, 0),  # a
                   (vk.KEY_LEFTSHIFT, 1), (44, 1), (44, 0), (vk.KEY_LEFTSHIFT, 0),  # Z
                   (vk.KEY_LEFTSHIFT, 1), (2, 1), (2, 0), (vk.KEY_LEFTSHIFT, 0)]  # !
    assert typed("é")[0] == []  # not on a US keyboard: nothing


def test_ctrl_and_alt_hold_for_one_key():
    virtual = FakeVirtual()
    board = vk.VirtualKeyboard(make_uinput=lambda: virtual, pause=lambda s: None)
    board.held = {"Ctrl"}
    board.insert("c")
    board.key("F5")
    assert keys_of(virtual.got) == [(vk.KEY_LEFTCTRL, 1), (46, 1), (46, 0), (vk.KEY_LEFTCTRL, 0), (63, 1), (63, 0)]
    assert board.held == set()


def test_no_uinput_no_crash():
    def fail():
        raise PermissionError(13, "Permission denied")

    board = vk.VirtualKeyboard(make_uinput=fail, pause=lambda s: None)
    board.insert("a")
    assert "Permission denied" in board.error


def test_remapper_hands_the_controller_to_the_keyboard_and_back():
    pad = PipePad()
    virtual = FakeVirtual()
    r = Remapper(BUILT_IN, default_profile(KEYS, AXES), open_device=lambda path: pad, make_uinput=lambda: virtual)
    assert r.start(), r.error
    diverted = []
    try:
        pad.press((e.EV_KEY, e.BTN_SOUTH, 1), (e.EV_SYN, 0, 0))
        assert wait_until(lambda: (e.EV_KEY, e.BTN_SOUTH, 1) in virtual.got)
        r.divert = diverted.extend
        assert wait_until(lambda: virtual.got[-1] == (e.EV_SYN, e.SYN_REPORT, 0)
                          and (e.EV_KEY, e.BTN_SOUTH, 0) in virtual.got)  # let go for the game
        virtual.got.clear()
        pad.press((e.EV_KEY, e.BTN_EAST, 1), (e.EV_SYN, 0, 0))
        assert wait_until(lambda: (e.EV_KEY, e.BTN_EAST, 1) in diverted)
        assert (e.EV_KEY, e.BTN_EAST, 1) not in virtual.got  # the game didn't get it
        r.divert = None
        pad.press((e.EV_KEY, e.BTN_NORTH, 1), (e.EV_SYN, 0, 0))
        assert wait_until(lambda: (e.EV_KEY, e.BTN_NORTH, 1) in virtual.got)
    finally:
        r.stop()


@pytest.fixture
def board(qtbot):
    from gamingcrypt.ui.game_keyboard import GameKeyboard

    virtual = FakeVirtual()
    sink = vk.VirtualKeyboard(make_uinput=lambda: virtual, pause=lambda s: None)
    diverts = []
    kb = GameKeyboard(sink=sink, divert=diverts.append, mark_overlay=lambda w: True)
    qtbot.addWidget(kb)
    kb.open_over_game()
    kb.virtual, kb.diverts = virtual, diverts
    yield kb
    kb.close_keyboard()


def press(kb, code):
    kb.pad_event(e.EV_KEY, code, 1)
    kb.pad_event(e.EV_KEY, code, 0)


def hat(kb, x=0, y=0):
    kb.pad_event(e.EV_ABS, e.ABS_HAT0X if x else e.ABS_HAT0Y, x or y)
    kb.pad_event(e.EV_ABS, e.ABS_HAT0X if x else e.ABS_HAT0Y, 0)


def test_controller_types_into_the_game(board):
    from gamingcrypt.ui import navigator

    assert board.is_open() and callable(board.diverts[-1]) and board.pad_event in navigator.LISTENERS
    assert board.key().text() == "1"  # the number row, first key
    hat(board, y=1)  # down: q
    hat(board, x=1)  # right: w
    press(board, e.BTN_SOUTH)  # A types it
    press(board, e.BTN_WEST)  # Y: space
    press(board, e.BTN_NORTH)  # X: Shift
    press(board, e.BTN_SOUTH)  # W
    press(board, e.BTN_EAST)  # B: delete
    press(board, e.BTN_START)  # Menu: Enter
    assert keys_of(board.virtual.got) == [
        (17, 1), (17, 0), (vk.KEY_SPACE, 1), (vk.KEY_SPACE, 0),
        (vk.KEY_LEFTSHIFT, 1), (17, 1), (17, 0), (vk.KEY_LEFTSHIFT, 0),
        (vk.KEY_BACKSPACE, 1), (vk.KEY_BACKSPACE, 0), (vk.KEY_ENTER, 1), (vk.KEY_ENTER, 0)]
    press(board, e.BTN_SELECT)  # View: closed, the controller is the game's again
    assert not board.is_open() and board.diverts[-1] is None and board.pad_event not in navigator.LISTENERS


def test_esc_and_function_keys(board):
    hat(board, y=-1)  # up from the number row: wraps to … the bottom row
    hat(board, y=-1)  # … the row above it
    board.select(0, 0)
    press(board, e.BTN_SOUTH)  # Esc
    board.select(0, len(board.rows[0]) - 1)
    press(board, e.BTN_SOUTH)  # Fn
    assert [b.text() for b in board.rows[1]][:2] == ["F1", "F2"]
    board.select(1, 4)
    press(board, e.BTN_SOUTH)
    assert keys_of(board.virtual.got) == [(vk.KEY_ESC, 1), (vk.KEY_ESC, 0), (63, 1), (63, 0)]


# --- in the window ---------------------------------------------------------------------------

@pytest.fixture
def window(qtbot):
    from gamingcrypt.app import MainWindow

    cfg = copy.deepcopy(DEFAULTS)
    w = MainWindow(cfg, lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    return w


def test_combination_during_a_game_opens_it_over_the_game(qtbot, window, monkeypatch):
    from gamingcrypt.input import hotkeys
    from gamingcrypt.ui import game_keyboard

    monkeypatch.setattr(game_keyboard.GameKeyboard, "open_over_game",
                        lambda self: setattr(self, "opened", True))
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    window.hide()
    window.hardware_key(hotkeys.ACTION_CODES["keyboard"])
    keyboard = window.game_keyboard
    assert keyboard.is_open() and not window.isVisible()  # the game stays in front
    window.hardware_key(hotkeys.ACTION_CODES["keyboard"])  # again: closed
    assert not keyboard.is_open()
    window.hardware_key(hotkeys.ACTION_CODES["keyboard"])
    window.game_over()
    assert not keyboard.is_open()

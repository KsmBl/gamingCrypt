import pytest
from PySide6.QtCore import QPointF, Qt

from gamingcrypt.ui.lock_screen import LockScreen, PatternWidget, PinPad, between_node
from gamingcrypt.ui.widgets import OnScreenKeyboard
from gamingcrypt.unlock.veracrypt import UnlockResult


class FakeUnlocker:
    def __init__(self, correct="1234", configured=True):
        self.correct = correct
        self.configured = configured
        self.attempts = []

    def unlock(self, secret):
        self.attempts.append(secret)
        if secret == self.correct:
            return UnlockResult(True, "Unlocked")
        return UnlockResult(False, "Wrong code - please try again")


def test_pinpad_typing_and_submit(qtbot):
    pad = PinPad()
    qtbot.addWidget(pad)
    for key in "12⌫34":
        pad.press(key)
    with qtbot.waitSignal(pad.submitted) as blocker:
        pad.press("✓")
    assert blocker.args == ["134"]


@pytest.mark.parametrize("a,b,mid", [(0, 2, 1), (0, 8, 4), (2, 6, 4), (0, 6, 3), (0, 1, None), (0, 5, None)])
def test_between_node(a, b, mid):
    assert between_node(a, b) == mid


def test_pattern_add_node_fills_skipped_dots():
    w = PatternWidget()
    w.add_node(0)
    w.add_node(2)
    w.add_node(2)
    assert w.nodes == [0, 1, 2]


def test_pattern_drag_emits_nodes(qtbot):
    w = PatternWidget()
    qtbot.addWidget(w)
    w.resize(300, 300)
    w.show()
    points = [w.node_center(i).toPoint() for i in (0, 3, 6, 7)]
    with qtbot.waitSignal(w.pattern_entered) as blocker:
        qtbot.mousePress(w, Qt.MouseButton.LeftButton, pos=points[0])
        for p in points[1:]:
            qtbot.mouseMove(w, p)
            # offscreen mouseMove doesn't carry button state; feed the widget directly
            w._track(QPointF(p))
        qtbot.mouseRelease(w, Qt.MouseButton.LeftButton, pos=points[-1])
    assert blocker.args == [[0, 3, 6, 7]]


def test_keyboard_types_into_target(qtbot):
    from PySide6.QtWidgets import QLineEdit

    edit = QLineEdit()
    kb = OnScreenKeyboard(edit)
    qtbot.addWidget(kb)
    kb.toggle_shift()
    assert "Q" in kb.key_labels()
    kb.type_text("Q")  # shift resets after one letter
    assert "q" in kb.key_labels()
    kb.type_text("w")
    kb.toggle_symbols()
    kb.type_text("!")
    kb.backspace()
    kb.type_text("?")
    assert edit.text() == "Qw?"
    with qtbot.waitSignal(kb.submitted):
        kb.submitted.emit()


def test_lock_screen_correct_pin_unlocks(qtbot):
    unlocker = FakeUnlocker("4711")
    screen = LockScreen(unlocker)
    qtbot.addWidget(screen)
    with qtbot.waitSignal(screen.unlocked, timeout=3000):
        for key in "4711✓":
            screen.pin_pad.press(key)
    assert unlocker.attempts == ["4711"]


def test_lock_screen_wrong_pin_shows_error(qtbot):
    unlocker = FakeUnlocker("4711")
    screen = LockScreen(unlocker)
    qtbot.addWidget(screen)
    for key in "0000✓":
        screen.pin_pad.press(key)
    qtbot.waitUntil(lambda: not screen.busy)
    assert "Wrong code" in screen.status.text()
    assert screen.pin_pad.display.text() == ""


def test_lock_screen_short_pin_is_rejected_without_calling_veracrypt(qtbot):
    unlocker = FakeUnlocker()
    screen = LockScreen(unlocker)
    qtbot.addWidget(screen)
    for key in "12✓":
        screen.pin_pad.press(key)
    assert unlocker.attempts == []
    assert "at least" in screen.status.text()


def test_lock_screen_password_and_pattern(qtbot):
    unlocker = FakeUnlocker("14789")
    screen = LockScreen(unlocker)
    qtbot.addWidget(screen)
    screen.select_method("password")
    assert screen.stack.currentWidget() is screen.password
    screen.password.edit.setText("nope")
    screen.password.keyboard.submitted.emit()
    qtbot.waitUntil(lambda: not screen.busy)
    assert unlocker.attempts == ["nope"]
    screen.select_method("pattern")
    with qtbot.waitSignal(screen.unlocked, timeout=3000):
        screen.pattern.pattern_entered.emit([0, 3, 6, 7, 8])


def test_lock_screen_only_configured_methods(qtbot):
    screen = LockScreen(FakeUnlocker(), methods=["pattern", "bogus"])
    qtbot.addWidget(screen)
    assert screen.methods == ["pattern"]
    assert screen.stack.currentWidget() is screen.pattern


def test_lock_screen_unconfigured_allows_skip(qtbot):
    screen = LockScreen(FakeUnlocker(configured=False))
    qtbot.addWidget(screen)
    assert not screen.skip_button.isHidden()
    with qtbot.waitSignal(screen.unlocked):
        screen.skip_button.click()

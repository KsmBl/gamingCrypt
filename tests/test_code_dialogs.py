"""The code asked for in a box over the screen (encrypting a stick, opening one): it fits any screen,
sits in the middle, nothing overlaps or is cut off - and every dot stays where it is when one's tapped.

At 1280x800 the 5x5 dots used to be pushed off-centre and their ⌫ / ✓ lay over dots."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget

from gamingcrypt.system.removable import Removable
from gamingcrypt.ui import theme
from gamingcrypt.ui.modal import show_modal

SCREENS = [(1280, 800), (1280, 720), (1366, 768), (1920, 1080), (1920, 1200), (2560, 1600), (1024, 600), (800, 600)]
METHODS = ["grid5", "pattern", "pin", "password"]
STICK = Removable(Path("/x"), "usb", "STICK", "/dev/sdb1", "exfat", "/dev/sdb", 32 * 1024 ** 3,
                  container="/x/GamingCrypt.vc", host=Path("/x"))


def screen(qtbot, w, h) -> QWidget:
    host = QWidget()
    host.setObjectName("screen")
    host.setStyleSheet(f"QWidget#screen {{ background: {theme.BG}; }}")
    qtbot.addWidget(host)
    host.resize(w, h)
    host.show()
    return host


def settle(qtbot) -> None:
    qtbot.wait(30)


def format_dialog(qtbot, host, method):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(STICK, formats=["exfat", "ext4"], encrypt=lambda *a, **k: None,
                        check_code=lambda _s: None, method=method)
    show_modal(host, box, lambda: None)
    box.choose("exfat")
    settle(qtbot)
    return box, box.code.input.widget


def unlock_dialog(qtbot, host, method, monkeypatch):
    from gamingcrypt.ui import unlock_stick

    monkeypatch.setattr(unlock_stick, "methods_of", lambda _v: [method])
    box = unlock_stick.UnlockStick(STICK)
    show_modal(host, box, lambda: None)
    settle(qtbot)
    return box, box.input.widget


def code_prompt(qtbot, host, method):
    from gamingcrypt.ui.code_prompt import CodePrompt

    box = CodePrompt("🔓 Unlock STICK", "It's encrypted with your code.", method, lambda _s: None)
    show_modal(host, box, lambda: None)
    settle(qtbot)
    return box, box.entry.input.widget


DIALOGS = {"format": format_dialog, "unlock": unlock_dialog, "prompt": code_prompt}


def open_dialog(qtbot, host, kind, method, monkeypatch):
    if kind == "unlock":
        return unlock_dialog(qtbot, host, method, monkeypatch)
    return DIALOGS[kind](qtbot, host, method)


def rect_in(widget: QWidget, ancestor: QWidget) -> QRect:
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def shown_parts(box: QWidget) -> list[QWidget]:
    """What one sees and taps in the box: its buttons, fields, labels, the dots."""
    from gamingcrypt.ui.secret_input import DotCanvas, PatternWidget

    kinds = (QAbstractButton, QLineEdit, QLabel, DotCanvas, PatternWidget)
    return [w for w in box.findChildren(QWidget) if isinstance(w, kinds) and w.isVisibleTo(box)
            and not (isinstance(w, QLabel) and not w.text())]


@pytest.mark.parametrize("w,h", SCREENS)
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_it_fits_and_sits_in_the_middle(qtbot, monkeypatch, kind, method, w, h):
    host = screen(qtbot, w, h)
    box, pad = open_dialog(qtbot, host, kind, method, monkeypatch)
    where = rect_in(box, host)
    assert host.rect().contains(where), f"the box {where} is off the {w}x{h} screen"
    assert abs(where.left() - (w - where.right() - 1)) <= 2  # in the middle
    assert abs(where.top() - (h - where.bottom() - 1)) <= 2 or where.height() >= h - 2 * 12 - 2
    for part in shown_parts(box):
        inside = rect_in(part, box)
        assert box.rect().contains(inside), f"{type(part).__name__} {part.objectName()} is cut off: {inside}"
        if not isinstance(part, QLabel):
            assert part.height() >= part.minimumSizeHint().height() - 1, f"{type(part).__name__} squeezed"
    # the input in the middle of the box
    centre = rect_in(pad, box).center().x()
    assert abs(centre - box.width() / 2) <= 3, f"the {method} input is off-centre by {centre - box.width() / 2}"


@pytest.mark.parametrize("w,h", SCREENS)
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_the_dots_and_their_buttons_dont_overlap(qtbot, monkeypatch, kind, w, h):
    host = screen(qtbot, w, h)
    box, pad = open_dialog(qtbot, host, kind, "grid5", monkeypatch)
    canvas = rect_in(pad.canvas, box)
    side = min(pad.canvas.width(), pad.canvas.height())
    assert side >= 200  # big enough for a finger: 40 px a dot at least
    assert abs(canvas.center().x() - box.width() / 2) <= 3  # the dots in the middle
    for button in (pad.back_button, pad.ok_button):
        where = rect_in(button, box)
        assert not where.intersects(canvas), f"{button.text()} lies over the dots"
        assert where.top() - canvas.bottom() >= 10  # a gap: a tap on the last row doesn't hit it
        for i in range(25):
            dot = pad.canvas.node_center(i).toPoint() + canvas.topLeft()
            assert not where.contains(dot)


def dot_pixels(host, canvas, count: int) -> tuple[list, object]:
    """The colour at each dot's middle, and between two of them (the background)."""
    image = host.grab().toImage()
    origin = canvas.mapTo(host, QPoint(0, 0))
    centres = [canvas.node_center(i).toPoint() + origin for i in range(count)]
    between = (canvas.node_center(0) + canvas.node_center(1)).toPoint() / 2 + origin
    return [image.pixelColor(p) for p in centres], image.pixelColor(between)


@pytest.mark.parametrize("w,h", [(1280, 800), (1024, 600), (1920, 1080)])
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_every_dot_stays_when_the_first_is_tapped(qtbot, monkeypatch, kind, w, h):
    host = screen(qtbot, w, h)
    box, pad = open_dialog(qtbot, host, kind, "grid5", monkeypatch)
    canvas = pad.canvas
    before, background = dot_pixels(host, canvas, 25)
    assert all(c != background for c in before), "not every dot is drawn"
    geometry = (canvas.geometry(), box.geometry())
    first = canvas.node_center(0).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=first)
    settle(qtbot)
    after, background_after = dot_pixels(host, canvas, 25)
    assert pad.nodes == [0] and pad.display.text() == "●"
    assert (canvas.geometry(), box.geometry()) == geometry  # nothing moved
    assert background_after == background
    assert all(c != background for c in after), "dots went away when the first was tapped"
    assert after[0] == theme_color("ACCENT")  # the tapped one lights up
    assert after[1:] == before[1:]  # the others as they were
    qtbot.waitUntil(lambda: dot_pixels(host, canvas, 1)[0][0] == before[0], timeout=1000)  # (and goes out again)


@pytest.mark.parametrize("w,h", [(1280, 800), (1024, 600)])
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_the_swipe_pattern_keeps_its_dots(qtbot, monkeypatch, kind, w, h):
    host = screen(qtbot, w, h)
    box, pad = open_dialog(qtbot, host, kind, "pattern", monkeypatch)
    before, background = dot_pixels(host, pad, 9)
    assert all(c != background for c in before)
    QTest.mousePress(pad, Qt.MouseButton.LeftButton, pos=pad.node_center(0).toPoint())
    settle(qtbot)
    after, _ = dot_pixels(host, pad, 9)
    assert pad.nodes == [0] and all(c != background for c in after)


def test_a_pin_shows_its_digits_and_keys_fit(qtbot, monkeypatch):
    host = screen(qtbot, 1024, 600)
    box, pad = format_dialog(qtbot, host, "pin")
    for key in "1234":
        pad.buttons[key].click()
    assert pad.display.text() == "1234"
    keys = [rect_in(b, box) for b in pad.buttons.values()]
    assert all(not a.intersects(b) for i, a in enumerate(keys) for b in keys[i + 1:])  # no key over another


def test_the_lock_screen_keeps_its_big_pad(qtbot):
    from gamingcrypt.ui.secret_input import DotGridPad, PinPad, SecretInput

    dots, digits = SecretInput("grid5"), SecretInput("pin")
    for widget in (dots, digits):
        qtbot.addWidget(widget)
    big, pin = dots.widget, digits.widget
    assert isinstance(big, DotGridPad) and big.canvas.minimumWidth() == 400  # (compact only in a box)
    assert big.back_button.size().width() == 120
    assert isinstance(pin, PinPad) and pin.buttons["1"].objectName() == "pinKey"


def test_the_box_follows_the_screen(qtbot):
    """Gaming mode's resolution changed while it's open: still on the screen, in the middle."""
    host = screen(qtbot, 1920, 1080)
    box, _pad = format_dialog(qtbot, host, "grid5")
    host.resize(1024, 600)
    settle(qtbot)
    where = rect_in(box, host)
    assert host.rect().contains(where) and abs(where.left() - (1024 - where.right() - 1)) <= 2


def theme_color(name: str):
    from PySide6.QtGui import QColor

    return QColor(getattr(theme, name))

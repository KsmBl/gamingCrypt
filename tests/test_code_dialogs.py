"""The code asked for again (encrypting a stick, opening one): the whole screen, as the lock screen -
its title, "Enter your PIN", the same pads - nothing cut off or squeezed, in the middle, and every
dot stays where it is when one's tapped (with a mouse and with a finger)."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget

from gamingcrypt.system.removable import Removable
from gamingcrypt.ui import theme
from gamingcrypt.ui.modal import open_modal, show_modal

# the lock screen's sizes: 720 px high and more (its 5x5 and pattern shrink to fit down to 600)
SCREENS = [(1280, 800), (1280, 720), (1366, 768), (1920, 1080), (1920, 1200), (2560, 1600)]
SMALL = [(1024, 600)]
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


def format_code(qtbot, host, method, monkeypatch):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(STICK, formats=["exfat", "ext4"], encrypt=lambda *a, **k: None,
                        check_code=lambda _s: None, method=method)
    show_modal(host, box, lambda: None)
    box.choose("exfat")
    box.next_button.click()  # (its name, how much is encrypted: as they are) - then the code
    settle(qtbot)
    page = box.code.parentWidget()
    return page, box.code.input.widget


def unlock_code(qtbot, host, method, monkeypatch):
    from gamingcrypt.ui import unlock_stick
    from gamingcrypt.ui.code_prompt import FullScreen

    monkeypatch.setattr(unlock_stick, "methods_of", lambda _v: [method])
    page = unlock_stick.UnlockStick(STICK)
    FullScreen(host, page)
    settle(qtbot)
    return page, page.input.widget


def your_code(qtbot, host, method, monkeypatch):
    from gamingcrypt.ui.code_prompt import ask_code

    page = ask_code(host, "🔓 Unlock STICK", "It's encrypted with your code.", method, lambda _s: None,
                    lambda _p: None)
    settle(qtbot)
    return page, page.entry.input.widget


DIALOGS = {"format": format_code, "unlock": unlock_code, "prompt": your_code}


def open_dialog(qtbot, host, kind, method, monkeypatch):
    return DIALOGS[kind](qtbot, host, method, monkeypatch)


def rect_in(widget: QWidget, ancestor: QWidget) -> QRect:
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def shown_parts(box: QWidget) -> list[QWidget]:
    """What one sees and taps: its buttons, fields, labels, the dots."""
    from gamingcrypt.ui.secret_input import DotCanvas, PatternWidget

    kinds = (QAbstractButton, QLineEdit, QLabel, DotCanvas, PatternWidget)
    return [w for w in box.findChildren(QWidget) if isinstance(w, kinds) and w.isVisibleTo(box)
            and not (isinstance(w, QLabel) and not w.text())]


def check_fits(page, pad, host, w, h, squeeze: bool = True) -> None:
    assert rect_in(page, host) == host.rect(), "not the whole screen"
    for part in shown_parts(page):
        where = rect_in(part, page)
        assert page.rect().contains(where), f"{type(part).__name__} {getattr(part, 'text', lambda: '')()!r} " \
                                            f"cut off at {w}x{h}: {where}"
        if squeeze and not isinstance(part, QLabel):
            assert part.height() >= part.minimumSizeHint().height() - 1, f"{type(part).__name__} squeezed"
    centre = rect_in(pad, page).center().x()
    assert abs(centre - page.width() / 2) <= 3, f"the input is off-centre by {centre - page.width() / 2}"


@pytest.mark.parametrize("w,h", SCREENS)
@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_the_whole_screen_as_the_lock_screen(qtbot, monkeypatch, kind, method, w, h):
    host = screen(qtbot, w, h)
    page, pad = open_dialog(qtbot, host, kind, method, monkeypatch)
    check_fits(page, pad, host, w, h)
    assert page.findChild(QLabel, "title").text().startswith(("🔓", "🔒"))
    assert open_modal(host) is not None and open_modal(host).content is page  # (the controller stays in it)


@pytest.mark.parametrize("w,h", SMALL)
@pytest.mark.parametrize("method", ["grid5", "pattern"])
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_the_dots_shrink_on_a_small_screen(qtbot, monkeypatch, kind, method, w, h):
    host = screen(qtbot, w, h)
    page, pad = open_dialog(qtbot, host, kind, method, monkeypatch)
    check_fits(page, pad, host, w, h)
    target = getattr(pad, "canvas", pad)
    side = min(target.width(), target.height())  # (both draw a square in what they have)
    assert side >= 220  # (and it fits: check_fits)


def test_the_lock_screens_own_pads(qtbot, monkeypatch):
    from gamingcrypt.ui.secret_input import DotGridPad, PinPad, SIDE_BUTTON

    host = screen(qtbot, 1920, 1080)
    _page, dots = your_code(qtbot, host, "grid5", monkeypatch)
    assert isinstance(dots, DotGridPad) and dots.canvas.minimumWidth() == 400  # (room: its own size)
    assert dots.back_button.size() == SIDE_BUTTON and dots.hint.isVisible()  # ⌫ ✓ beside it, the buttons' hint
    _page, pin = your_code(qtbot, screen(qtbot, 1920, 1080), "pin", monkeypatch)
    assert isinstance(pin, PinPad) and pin.buttons["1"].objectName() == "pinKey"


def test_cancel_and_b_close_it(qtbot, monkeypatch):
    from gamingcrypt.ui.code_prompt import ask_code

    host = screen(qtbot, 1280, 800)
    cancelled = []
    page = ask_code(host, "T", "x", "pin", lambda _s: None, lambda _p: None, lambda: cancelled.append(1))
    page.cancel_button.click()
    settle(qtbot)
    assert cancelled == [1] and open_modal(host) is None
    page = ask_code(host, "T", "x", "pin", lambda _s: None, lambda _p: None, lambda: cancelled.append(2))
    assert page.gamepad_back() and cancelled == [1, 2]


def test_the_right_code_hands_on_the_password(qtbot):
    from gamingcrypt.ui.code_prompt import ask_code

    host = screen(qtbot, 1280, 800)
    got = []
    page = ask_code(host, "T", "x", "pin", lambda s: "the password" if s == "1234" else None, got.append)
    page.entry.try_code("0000")
    qtbot.waitUntil(lambda: not page.entry.working)
    assert page.entry.status.text() == "Wrong code - try again" and got == []
    page.entry.try_code("1234")
    qtbot.waitUntil(lambda: got == ["the password"])
    assert open_modal(host) is None


def test_the_code_over_formatting_has_the_controller(qtbot, monkeypatch):
    host = screen(qtbot, 1280, 800)
    page, _pad = format_code(qtbot, host, "pin", monkeypatch)
    assert open_modal(host).content is page  # (the top one: not the format box under it)


def dot_pixels(host, canvas, count: int) -> tuple[list, object]:
    """The colour at each dot's middle, and between two of them (the background)."""
    image = host.grab().toImage()
    origin = canvas.mapTo(host, QPoint(0, 0))
    centres = [canvas.node_center(i).toPoint() + origin for i in range(count)]
    between = (canvas.node_center(0) + canvas.node_center(1)).toPoint() / 2 + origin
    return [image.pixelColor(p) for p in centres], image.pixelColor(between)


@pytest.mark.parametrize("w,h", [(1280, 800), (1280, 720), (1920, 1080)])
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_every_dot_stays_when_the_first_is_tapped(qtbot, monkeypatch, kind, w, h):
    host = screen(qtbot, w, h)
    _page, pad = open_dialog(qtbot, host, kind, "grid5", monkeypatch)
    canvas = pad.canvas
    before, background = dot_pixels(host, canvas, 25)
    assert all(c != background for c in before), "not every dot is drawn"
    first = canvas.node_center(0).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=first)
    settle(qtbot)
    after, background_after = dot_pixels(host, canvas, 25)
    assert pad.nodes == [0] and pad.display.text() == "●"
    assert background_after == background and all(c != background for c in after)
    assert after[1:] == before[1:]


def touch(host, widget, pos, release: bool = True) -> None:
    device = touch.device = getattr(touch, "device", None) or QTest.createTouchDevice()
    where = widget.mapTo(host, pos)
    QTest.touchEvent(host, device).press(0, where, host)
    if release:
        QTest.touchEvent(host, device).release(0, where, host)


@pytest.mark.parametrize("look", ["dark", "light"])
@pytest.mark.parametrize("w,h", [(1280, 800), (1280, 720), (1920, 1080)])
@pytest.mark.parametrize("kind", list(DIALOGS))
def test_a_finger_on_the_dots(qtbot, monkeypatch, kind, w, h, look):
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    before_look, before_sheet = theme.current, app.styleSheet()
    theme.apply(look, app)
    try:
        host = screen(qtbot, w, h)
        _page, pad = open_dialog(qtbot, host, kind, "grid5", monkeypatch)
        dots, background = dot_pixels(host, pad.canvas, 25)
        touch(host, pad.canvas, pad.canvas.node_center(0).toPoint(), release=False)
        settle(qtbot)
        held, held_background = dot_pixels(host, pad.canvas, 25)
        assert held_background == background and all(c != held_background for c in held[1:])
        QTest.touchEvent(host, touch.device).release(0, pad.canvas.mapTo(host, pad.canvas.node_center(0).toPoint()),
                                                   host)
        for _ in range(3):
            touch(host, pad.canvas, pad.canvas.node_center(12).toPoint())
            qtbot.wait(20)
        assert pad.nodes == [0, 12, 12, 12] and all(c != background for c in dot_pixels(host, pad.canvas, 25)[0])
    finally:
        theme.apply(before_look)
        app.setStyleSheet(before_sheet)


@pytest.mark.parametrize("kind", list(DIALOGS))
def test_a_finger_on_the_pin_keys(qtbot, monkeypatch, kind):
    host = screen(qtbot, 1280, 800)
    _page, pad = open_dialog(qtbot, host, kind, "pin", monkeypatch)
    for key in "1234":
        touch(host, pad.buttons[key], pad.buttons[key].rect().center())
        qtbot.wait(20)
    assert pad.display.text() == "1234"


def test_every_box_over_the_screen_stays_as_it_is_under_a_finger(qtbot):
    """Remove, Move, Format - any card shown as a box: a finger doesn't light it up."""
    from PySide6.QtWidgets import QFrame, QVBoxLayout

    host = screen(qtbot, 1280, 800)
    content = QFrame()
    content.setObjectName("card")
    QVBoxLayout(content).addWidget(QLabel("Really?"))
    show_modal(host, content, lambda: None)
    settle(qtbot)
    assert content.objectName() == "dialog"
    spot = QPoint(content.width() - 30, content.height() // 2)
    colour = host.grab().toImage().pixelColor(content.mapTo(host, spot))
    touch(host, content, spot, release=False)
    settle(qtbot)
    assert host.grab().toImage().pixelColor(content.mapTo(host, spot)) == colour


def test_the_box_follows_the_screen(qtbot):
    """Gaming mode's resolution changed while one is open: still on the screen, in the middle."""
    from gamingcrypt.ui.format_drive import FormatConfirm

    host = screen(qtbot, 1920, 1080)
    box = FormatConfirm(STICK, formats=["exfat"])
    show_modal(host, box, lambda: None)
    host.resize(1280, 720)
    settle(qtbot)
    where = rect_in(box, host)
    assert host.rect().contains(where) and abs(where.left() - (1280 - where.right() - 1)) <= 2

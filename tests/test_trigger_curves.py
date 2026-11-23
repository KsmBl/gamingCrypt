"""Settings → Controller → Triggers: a curve for triggers that aren't linear."""

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import (CURVE_POINTS, Profile, Translator, apply_curve, measured_curve,
                                       trigger_curve)
from gamingcrypt.ui import trigger_curves
from tests.test_controller_settings import make, opened, push


def test_curve_from_sliders():
    assert trigger_curve(0, 1, 1) == [i / (CURVE_POINTS - 1) for i in range(CURVE_POINTS)]
    curve = trigger_curve(0.25, 0.75, 1)
    assert apply_curve(curve, 0.2) == 0 and apply_curve(curve, 0.5) == 0.5 and apply_curve(curve, 0.8) == 1
    early = trigger_curve(0, 1, 0.5)  # a trigger that does little at first: more there
    assert apply_curve(early, 0.25) > 0.45


def test_measured_slow_pull_linearises_an_exponential_trigger():
    # the sensor rises like x² over a 3 s even pull, and is at 100% for the last 20 % of it
    samples = [(t / 100, min(1.0, (t / 240) ** 2)) for t in range(0, 301)]
    curve = measured_curve(samples)
    assert curve is not None and curve[0] == 0 and curve[-1] == 1
    assert all(b >= a for a, b in zip(curve, curve[1:]))
    # the sensor moves at 0.25 s (1 %), reaches a quarter at 1.2 s and 100 % at 2.4 s: games get
    # how far along the pull that is - (1.2 - 0.25) / (2.4 - 0.25)
    assert abs(apply_curve(curve, 0.25) - 0.95 / 2.15) < 0.02
    assert measured_curve([(0, 0), (0.05, 0.5), (0.1, 1.0)] * 3) is None  # in one go
    assert measured_curve([(t / 10, t / 100) for t in range(30)]) is None  # never all the way


def test_translator_uses_the_curve():
    from tests.test_input import ABSINFO

    profile = Profile(axes={"lt": e.ABS_Z, "rt": e.ABS_RZ}, trigger_curves={"rt": trigger_curve(0.5, 1, 1)})
    from gamingcrypt.input.profile import Source

    profile.buttons = {"lt": Source("abs", e.ABS_Z, 1), "rt": Source("abs", e.ABS_RZ, 1)}
    t = Translator(profile, ABSINFO)
    top = ABSINFO[e.ABS_RZ].maximum
    t.feed(e.EV_ABS, e.ABS_RZ, top * 3 // 4)
    t.feed(e.EV_ABS, e.ABS_Z, top * 3 // 4)
    out = dict(((c, v) for _t, c, v in t.feed(e.EV_SYN, e.SYN_REPORT, 0)))
    assert abs(out[e.ABS_RZ] - 128) <= 2 and out[e.ABS_Z] > 180  # rt: half; lt: straight
    again = Profile.from_dict(profile.to_dict())
    assert again.trigger_curves == profile.trigger_curves


def test_page_sliders_measure_and_straight(qtbot, monkeypatch):
    page, service, cfg, saved, _ = make(qtbot)
    opened(page, "triggers")
    section = page.triggers
    assert section.isVisible() and section.editing == "rt"
    section.start_slider.setValue(20)
    assert page.profile.trigger_shapes["rt"][0] == 0.2 and len(page.profile.trigger_curves["rt"]) == CURVE_POINTS
    assert saved  # kept
    section.select("lt")
    assert section.start_slider.value() == 0  # LT has none
    clock = iter(i / 100 for i in range(10_000))
    monkeypatch.setattr(trigger_curves.time, "monotonic", lambda: next(clock))
    section.start_measuring()
    top = page.absinfo[page.profile.axes["lt"]].maximum
    for step in range(0, 301):
        push(page, (e.EV_ABS, page.profile.axes["lt"], round(top * min(1.0, (step / 240) ** 2))))
    push(page, (e.EV_ABS, page.profile.axes["lt"], 0))
    assert section.measuring is None and "measured" in section.status.text()
    assert "lt" in page.profile.trigger_curves and "lt" not in page.profile.trigger_shapes
    section.straight()
    assert "lt" not in page.profile.trigger_curves and "rt" in page.profile.trigger_curves


def test_shape_slider_both_ways():
    assert trigger_curves.shape_of(0) == 1 and trigger_curves.shape_of(100) == 0.25
    assert trigger_curves.slider_of(trigger_curves.shape_of(-40)) == -40

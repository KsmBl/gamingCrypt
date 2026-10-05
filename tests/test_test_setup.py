"""The tests never open real windows on the desktop they run on."""

import os


def test_tests_run_offscreen(qapp):
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen" and qapp.platformName() == "offscreen"

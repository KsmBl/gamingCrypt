import re
from pathlib import Path

import gamingcrypt


def test_version_is_consistent():
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == gamingcrypt.__version__

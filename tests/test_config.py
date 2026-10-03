import json

from gamingcrypt import config


def test_missing_file_returns_defaults(tmp_path):
    cfg = config.load_config(tmp_path / "nope.json")
    assert cfg == config.DEFAULTS
    assert cfg is not config.DEFAULTS


def test_partial_file_is_merged_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"unlock": {"volume": "/dev/sdb1"}, "fullscreen": False}))
    cfg = config.load_config(path)
    assert cfg["unlock"]["volume"] == "/dev/sdb1"
    assert cfg["unlock"]["method"] == ""
    assert cfg["fullscreen"] is False
    assert cfg["steam"]["country"] == "de"


def test_broken_file_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json")
    assert config.load_config(path) == config.DEFAULTS


def test_save_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    cfg = config.load_config(path)
    cfg["steam"]["api_key"] = "abc"
    config.save_config(cfg, path)
    assert config.load_config(path)["steam"]["api_key"] == "abc"


def test_xdg_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "k"))
    assert config.config_path() == tmp_path / "c" / "gamingcrypt" / "config.json"
    assert config.cache_dir() == tmp_path / "k" / "gamingcrypt"

from __future__ import annotations

import re
from pathlib import Path

import pytest

from csvftps import config as settings
from csvftps.config import Config, ConfigError, Range


def test_round_trip(tmp_path: Path) -> None:
    config = Config(input="data/in.csv", extra_files=["a.csv"], interval=300)
    config.rules.column = "Size"
    config.rules.ranges = [Range("small", max=2.5), Range("big", min=2.5)]
    config.server.host = "ftp.example.com"
    config.server.verify_certificate = False
    path = settings.save(config, tmp_path / "nested" / "csvftps.toml")

    loaded = settings.load(path)
    assert loaded == config
    assert loaded.base_dir == path.parent
    assert "password" not in settings.to_dict(config)["server"]


def test_empty_file_gives_defaults(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("", encoding="utf-8")
    assert settings.load(path) == Config()


def test_relative_paths_follow_the_settings_file(tmp_path: Path) -> None:
    path = tmp_path / "proj" / "csvftps.toml"
    path.parent.mkdir()
    path.write_text('[files]\ninput = "in/data.csv"\nextra = ["x.csv"]\n', encoding="utf-8")
    config = settings.load(path)
    assert config.input_path == (path.parent / "in" / "data.csv").resolve()
    assert config.upload_paths == [(path.parent / "x.csv").resolve(), (path.parent / "output.csv").resolve()]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("interval = 0", "interval must be at least 1"),
        ('interval = "10"', "interval must be int"),
        ("[server]\nport = true", "server.port must be int"),
        ("[server]\nhots = 'x'", "unknown setting(s): server.hots"),
        ("[csv]\ndelimiter = ';;'", "exactly one character"),
        ("[[convert.ranges]]\nmin = 1", "needs a label"),
        ("[[convert.ranges]]\nmin = 5\nmax = 1\nlabel = 'x'", "min must be less than max"),
        ("[files]\nextra = [1]", "files.extra must be a list of strings"),
        ("not toml", "csvftps.toml"),
    ],
)
def test_invalid_settings(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "csvftps.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match=re.escape(message)):
        settings.load(path)


def test_default_path_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(settings.CONFIG_ENV, str(tmp_path / "x.toml"))
    assert settings.default_config_path() == tmp_path / "x.toml"
    monkeypatch.delenv(settings.CONFIG_ENV)
    assert settings.default_config_path().parts[-2:] == ("csvftps", "config.toml")

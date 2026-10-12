from __future__ import annotations

import threading
from pathlib import Path

import pytest

from csvftps import config as settings
from csvftps import runner
from csvftps.cli import main
from csvftps.config import Config
from csvftps.credentials import get_password


def cli(project: Config, *args: str) -> int:
    return main([*args, "-c", str(project.base_dir / "csvftps.toml")])


def test_init_creates_settings(tmp_path: Path, capsys) -> None:
    path = tmp_path / "new" / "csvftps.toml"
    assert main(["init", "-c", str(path)]) == 0
    assert settings.load(path) == Config()
    assert "Created" in capsys.readouterr().out
    assert main(["init", "-c", str(path)]) == 2  # will not overwrite
    assert main(["init", "-c", str(path), "--force"]) == 0


def test_init_uses_default_location(tmp_path: Path) -> None:
    assert main(["init"]) == 0
    assert (tmp_path / "home" / "config.toml").is_file()


def test_missing_settings_file(tmp_path: Path, caplog) -> None:
    assert main(["run", "--once", "-c", str(tmp_path / "nope.toml")]) == 2


def test_convert(project: Config) -> None:
    assert cli(project, "convert") == 0
    lines = project.output_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Id;Dealer;City;Group;Size;Price"
    assert [line.split(";")[4] for line in lines[1:]] == [
        "None",
        "2-5 inch",
        "2-5 inch",
        "6-10 inch",
        "6-10 inch",
        "> 10 inch",
        "None",
        "Size",  # second header row, kept
        "> 10 inch",
    ]


def test_convert_with_overrides(project: Config, tmp_path: Path) -> None:
    out = tmp_path / "elsewhere.csv"
    assert cli(project, "convert", "-o", str(out)) == 0
    assert out.is_file()
    assert not project.output_path.exists()


def test_run_once_uploads(project: Config, fake_ftps, monkeypatch) -> None:
    monkeypatch.setenv("CSVFTPS_PASSWORD", "secret")
    assert cli(project, "run", "--once") == 0
    assert set(fake_ftps.all_stored()) == {"prices.csv", "stock.csv", "output.csv"}


def test_run_once_partial_upload_fails(project: Config, fake_ftps, monkeypatch) -> None:
    monkeypatch.setenv("CSVFTPS_PASSWORD", "secret")
    (project.base_dir / "stock.csv").unlink()
    assert cli(project, "run", "--once") == 1


def test_run_no_upload_needs_no_password(project: Config, fake_ftps) -> None:
    assert cli(project, "run", "--once", "--no-upload") == 0
    assert fake_ftps.instances == []


def test_run_without_password_fails(project: Config, fake_ftps) -> None:
    assert cli(project, "run", "--once") == 1


def test_invalid_interval(project: Config) -> None:
    assert cli(project, "run", "--interval", "0") == 2


def test_set_and_delete_password(project: Config, monkeypatch, capsys) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "secret")
    assert cli(project, "set-password") == 0
    assert get_password(project.server) == "secret"
    assert cli(project, "set-password", "--delete") == 0
    assert get_password(project.server) is None
    assert cli(project, "set-password", "--delete") == 0
    assert "No saved password" in capsys.readouterr().out


def test_env_password_wins_over_keyring(project: Config, monkeypatch) -> None:
    monkeypatch.setattr("getpass.getpass", lambda prompt: "from-keyring")
    cli(project, "set-password")
    monkeypatch.setenv("CSVFTPS_PASSWORD", "from-env")
    assert get_password(project.server) == "from-env"


def test_test_command(project: Config, fake_ftps, monkeypatch, capsys) -> None:
    monkeypatch.setenv("CSVFTPS_PASSWORD", "secret")
    assert cli(project, "test") == 0
    assert "OK: logged in to ftp.example.com" in capsys.readouterr().out
    monkeypatch.setenv("CSVFTPS_PASSWORD", "wrong")
    assert cli(project, "test") == 1


def test_loop_survives_failures_and_stops(project: Config, monkeypatch) -> None:
    """A failed run is reported and the loop keeps going until it is stopped."""
    calls: list[str] = []
    stop = threading.Event()

    def fake_run_once(config, password=None, **kwargs):
        calls.append("run")
        if len(calls) == 1:
            raise runner.RunError("network down")
        stop.set()
        return runner.RunResult(runner.Stats(), None)

    monkeypatch.setattr(runner, "run_once", fake_run_once)
    project.interval = 1
    errors: list[str | None] = []
    runner.run_forever(project, do_upload=False, stop=stop, on_run=lambda r, e: errors.append(e))
    assert calls == ["run", "run"]
    assert errors == ["network down", None]


@pytest.mark.parametrize("args", [["--version"], ["--help"]])
def test_info_flags(args: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 0

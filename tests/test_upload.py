from __future__ import annotations

import ssl
from pathlib import Path

import pytest

from csvftps.config import Config
from csvftps.runner import RunError, run_once
from csvftps.upload import UploadError, describe, upload
from csvftps.upload import test_connection as check_connection  # not a test itself


def test_upload_uses_tls_for_data_and_remote_dir(project: Config, fake_ftps) -> None:
    project.server.remote_dir = "/in"
    project.output_path.write_text("x", encoding="utf-8")
    result = upload(project.server, "secret", project.upload_paths)

    [ftps] = fake_ftps.instances
    assert ftps.calls[:4] == [
        ("connect", "ftp.example.com", 21),
        ("login", "dealer"),
        ("prot_p",),
        ("cwd", "/in"),
    ]
    assert ftps.calls[-1] == ("quit",)
    assert ftps.context.verify_mode == ssl.CERT_REQUIRED
    assert list(ftps.stored) == ["prices.csv", "stock.csv", "output.csv"]
    assert [p.name for p in result.uploaded] == ["prices.csv", "stock.csv", "output.csv"]


def test_certificate_check_can_be_turned_off(project: Config, fake_ftps) -> None:
    project.server.verify_certificate = False
    check_connection(project.server, "secret")
    assert fake_ftps.instances[0].context.verify_mode == ssl.CERT_NONE


def test_missing_files_are_skipped(project: Config, fake_ftps) -> None:
    project.output_path.write_text("x", encoding="utf-8")
    (project.base_dir / "stock.csv").unlink()
    result = upload(project.server, "secret", project.upload_paths)
    assert [p.name for p in result.missing] == ["stock.csv"]
    assert set(fake_ftps.all_stored()) == {"prices.csv", "output.csv"}


def test_nothing_to_upload(project: Config, fake_ftps) -> None:
    with pytest.raises(UploadError, match="none of the files exist"):
        upload(project.server, "secret", [project.base_dir / "nope.csv"])
    assert fake_ftps.instances == []


def test_retry_resumes_where_it_stopped(project: Config, fake_ftps) -> None:
    project.output_path.write_text("x", encoding="utf-8")
    fake_ftps.failures = [ConnectionResetError("reset")]
    upload(project.server, "secret", project.upload_paths)
    first, second = fake_ftps.instances
    assert first.stored == {}
    assert list(second.stored) == ["prices.csv", "stock.csv", "output.csv"]


def test_gives_up_after_retries(project: Config, fake_ftps) -> None:
    project.server.retries = 2
    fake_ftps.failures = [TimeoutError()] * 5
    with pytest.raises(UploadError, match="did not answer in time.*after 3 attempt"):
        upload(project.server, "secret", project.upload_paths)
    assert len(fake_ftps.instances) == 3


def test_wrong_password_is_not_retried(project: Config, fake_ftps) -> None:
    with pytest.raises(UploadError, match="530"):
        upload(project.server, "wrong", project.upload_paths)
    assert len(fake_ftps.instances) == 1


def test_describe_certificate_error() -> None:
    exc = ssl.SSLCertVerificationError()
    exc.verify_message = "self-signed certificate"
    assert "verify_certificate = false" in describe(exc)


def test_run_once_converts_then_uploads(project: Config, fake_ftps, monkeypatch) -> None:
    monkeypatch.setenv("CSVFTPS_PASSWORD", "secret")
    result = run_once(project)
    assert result.complete
    assert result.stats.converted == 7
    stored = fake_ftps.all_stored()
    assert list(stored) == ["prices.csv", "stock.csv", "output.csv"]
    assert stored["output.csv"] == project.output_path.read_bytes()
    assert b"1;North;Kyiv;Phones;None;100" in stored["output.csv"]


def test_run_once_without_password(project: Config, fake_ftps) -> None:
    with pytest.raises(RunError, match="no password for dealer@ftp.example.com"):
        run_once(project)
    assert not project.output_path.exists()


def test_run_once_missing_input(project: Config, tmp_path: Path) -> None:
    project.input = str(tmp_path / "gone.csv")
    with pytest.raises(RunError, match="input file not found"):
        run_once(project, do_upload=False)

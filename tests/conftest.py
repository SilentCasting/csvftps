"""Shared fixtures: a project folder with settings and a sample CSV, and a fake FTPS server."""

from __future__ import annotations

import ftplib
from pathlib import Path

import pytest

from csvftps import config as settings
from csvftps.config import Config

SAMPLE = """\
Id;Dealer;City;Group;Size;Price
1;North;Kyiv;Phones;1.5;100
2;North;Kyiv;Phones;2;120
3;South;Odesa;Phones;5.9;130
4;South;Odesa;Tablets;6;200
5;West;Lviv;Tablets;10.7;210
6;West;Lviv;Monitors;11;300
7;East;Kharkiv;Monitors;NULL;310
Id;Dealer;City;Name Exchange;Size;Price
8;East;Kharkiv;TV;55;900
"""


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never touch the real settings file, password or keyring from a test."""
    monkeypatch.setenv(settings.CONFIG_ENV, str(tmp_path / "home" / "config.toml"))
    monkeypatch.delenv("CSVFTPS_PASSWORD", raising=False)
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr("keyring.get_password", lambda service, user: store.get((service, user)))
    monkeypatch.setattr(
        "keyring.set_password", lambda service, user, password: store.__setitem__((service, user), password)
    )

    def delete(service: str, user: str) -> None:
        from keyring.errors import PasswordDeleteError

        if store.pop((service, user), None) is None:
            raise PasswordDeleteError("not found")

    monkeypatch.setattr("keyring.delete_password", delete)


@pytest.fixture
def project(tmp_path: Path) -> Config:
    """A folder with input.csv, two extra files and a saved csvftps.toml."""
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "input.csv").write_text(SAMPLE, encoding="utf-8")
    (folder / "prices.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    (folder / "stock.csv").write_text("c;d\n3;4\n", encoding="utf-8")
    config = Config(extra_files=["prices.csv", "stock.csv"], base_dir=folder)
    config.server.host = "ftp.example.com"
    config.server.user = "dealer"
    config.server.retry_delay = 0
    settings.save(config, folder / "csvftps.toml")
    return config


class FakeFTPS:
    """Stands in for ftplib.FTP_TLS and records what the code asked it to do."""

    instances: list[FakeFTPS] = []
    # Exceptions to raise from storbinary(), one per call, before it starts succeeding.
    failures: list[BaseException] = []
    password = "secret"

    def __init__(self, context=None, timeout=None) -> None:
        self.context, self.timeout = context, timeout
        self.calls: list[tuple] = []
        self.stored: dict[str, bytes] = {}
        FakeFTPS.instances.append(self)

    def connect(self, host, port):
        self.calls.append(("connect", host, port))

    def login(self, user, password):
        self.calls.append(("login", user))
        if password != FakeFTPS.password:
            raise ftplib.error_perm("530 Login incorrect.")

    def prot_p(self):
        self.calls.append(("prot_p",))

    def cwd(self, path):
        self.calls.append(("cwd", path))

    def pwd(self):
        return "/upload"

    def storbinary(self, command, fh):
        if FakeFTPS.failures:
            raise FakeFTPS.failures.pop(0)
        self.stored[command.removeprefix("STOR ")] = fh.read()

    def quit(self):
        self.calls.append(("quit",))

    def close(self):
        self.calls.append(("close",))

    @classmethod
    def all_stored(cls) -> dict[str, bytes]:
        merged: dict[str, bytes] = {}
        for instance in cls.instances:
            merged.update(instance.stored)
        return merged


@pytest.fixture
def fake_ftps(monkeypatch: pytest.MonkeyPatch) -> type[FakeFTPS]:
    FakeFTPS.instances = []
    FakeFTPS.failures = []
    monkeypatch.setattr(ftplib, "FTP_TLS", FakeFTPS)
    return FakeFTPS

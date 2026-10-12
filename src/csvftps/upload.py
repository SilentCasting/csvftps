"""Upload files to an FTP server over explicit TLS (FTPS), with retries."""

from __future__ import annotations

import ftplib
import logging
import socket
import ssl
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from csvftps.config import Server

log = logging.getLogger(__name__)


class UploadError(RuntimeError):
    pass


@dataclass
class UploadResult:
    uploaded: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)


def connect(server: Server, password: str) -> ftplib.FTP_TLS:
    """Log in and switch the data connection to TLS as well (``PROT P``)."""
    if not server.host:
        raise UploadError("no server host set")
    context = ssl.create_default_context()
    if not server.verify_certificate:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    ftps = ftplib.FTP_TLS(context=context, timeout=server.timeout)
    try:
        ftps.connect(server.host, server.port)
        ftps.login(server.user, password)
        # Without this only the login is encrypted and the files go in plain text.
        ftps.prot_p()
        if server.remote_dir:
            ftps.cwd(server.remote_dir)
    except BaseException:
        ftps.close()
        raise
    return ftps


def test_connection(server: Server, password: str) -> str:
    """Log in and return the remote folder, or raise :class:`UploadError`."""
    try:
        ftps = connect(server, password)
    except (OSError, EOFError, ftplib.Error) as exc:
        raise UploadError(describe(exc)) from exc
    try:
        return ftps.pwd()
    finally:
        _quit(ftps)


def upload(
    server: Server,
    password: str,
    files: Sequence[Path],
    stop: threading.Event | None = None,
) -> UploadResult:
    """Upload ``files`` under their own names; retry on network errors.

    Missing files are skipped and reported in the result. Files that went up
    before a connection dropped are not sent again on the next attempt.
    ``stop`` cuts the waits between attempts short.
    """
    result = UploadResult()
    pending = []
    for path in files:
        (pending if path.is_file() else result.missing).append(path)
    for path in result.missing:
        log.warning("Not found, skipped: %s", path)
    if not pending:
        raise UploadError("nothing to upload: none of the files exist")

    attempts = server.retries + 1
    for attempt in range(1, attempts + 1):
        try:
            _upload_once(server, password, pending, result)
            return result
        except ftplib.error_perm as exc:
            # 5xx replies (wrong password, no such folder, no permission) will not fix themselves.
            raise UploadError(describe(exc)) from exc
        except (OSError, EOFError, ftplib.Error) as exc:
            if attempt == attempts:
                raise UploadError(f"{describe(exc)} (gave up after {attempts} attempt(s))") from exc
            log.warning(
                "Upload failed: %s. Retrying in %g s (%d/%d)…",
                describe(exc),
                server.retry_delay,
                attempt,
                attempts - 1,
            )
            # A fresh Event is never set, so wait() is then just a sleep.
            if (stop or threading.Event()).wait(server.retry_delay):
                raise UploadError("stopped") from exc
    raise AssertionError("unreachable")


def _upload_once(server: Server, password: str, pending: list[Path], result: UploadResult) -> None:
    ftps = connect(server, password)
    try:
        while pending:
            path = pending[0]
            with path.open("rb") as fh:
                ftps.storbinary(f"STOR {path.name}", fh)
            log.info("Uploaded %s (%s)", path.name, _size(path))
            result.uploaded.append(pending.pop(0))
    finally:
        _quit(ftps)


def _quit(ftps: ftplib.FTP_TLS) -> None:
    try:
        ftps.quit()
    except (OSError, EOFError, ftplib.Error):
        ftps.close()


def describe(exc: BaseException) -> str:
    """A short, readable reason for a failed connection or transfer."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        return (
            f"the server certificate could not be verified ({exc.verify_message}). "
            "If the server uses a self-signed certificate you trust, "
            "set verify_certificate = false in [server]"
        )
    if isinstance(exc, TimeoutError):
        return "the server did not answer in time"
    if isinstance(exc, socket.gaierror):
        return "server not found: check the host name"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused: check the host and port"
    if isinstance(exc, EOFError):
        return "the server closed the connection"
    text = str(exc).strip()
    return text or type(exc).__name__


def _size(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024**2:.1f} MB"

"""One run = convert the CSV, then upload it with the extra files. Repeat on a schedule."""

from __future__ import annotations

import csv
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from csvftps.config import Config
from csvftps.credentials import PASSWORD_ENV, get_password
from csvftps.excel import ExcelError
from csvftps.transform import Stats, convert_file
from csvftps.upload import UploadError, UploadResult, upload

log = logging.getLogger(__name__)


class RunError(RuntimeError):
    pass


@dataclass
class RunResult:
    stats: Stats
    upload: UploadResult | None  # None when uploading was turned off

    @property
    def complete(self) -> bool:
        """False if some files to upload were missing."""
        return self.upload is None or not self.upload.missing


def resolve_password(config: Config, password: str | None = None) -> str:
    if password is None:
        password = get_password(config.server)
    if password is None:
        raise RunError(
            f"no password for {config.server.user}@{config.server.host}: "
            f"run `csvftps set-password` or set {PASSWORD_ENV}"
        )
    return password


def convert(config: Config) -> Stats:
    source, target = config.input_path, config.output_path
    if source == target:
        raise RunError("the input and output must be different files")
    try:
        stats = convert_file(source, target, config.rules)
    except FileNotFoundError as exc:
        raise RunError(f"input file not found: {exc.filename}") from exc
    except PermissionError as exc:
        # Anything but the input is the output or its temp file, which is not worth naming.
        locked = source if exc.filename and Path(exc.filename) == source else target
        raise RunError(f"cannot access {locked.name}: it may be open in Excel or another program") from exc
    except ExcelError as exc:
        raise RunError(str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise RunError(
            f"{source.name} is not valid {config.rules.input_encoding} text "
            f"(byte {exc.start}); change csv.input_encoding"
        ) from exc
    except (OSError, csv.Error, LookupError) as exc:
        raise RunError(f"could not convert {source.name}: {exc}") from exc
    log.info(
        "Converted %s -> %s: %d row(s), %d converted, %d empty, %d kept as is",
        source.name,
        target.name,
        stats.rows - stats.headers,
        stats.converted,
        stats.empty,
        stats.skipped,
    )
    return stats


def run_once(
    config: Config,
    password: str | None = None,
    *,
    do_upload: bool = True,
    stop: threading.Event | None = None,
) -> RunResult:
    """Convert, then upload. Raises :class:`RunError` with a readable reason on failure."""
    if do_upload:
        password = resolve_password(config, password)
    stats = convert(config)
    if not do_upload:
        return RunResult(stats, None)
    try:
        uploaded = upload(config.server, password, config.upload_paths, stop=stop)
    except UploadError as exc:
        raise RunError(f"upload failed: {exc}") from exc
    log.info("Uploaded %d file(s) to %s", len(uploaded.uploaded), config.server.host)
    return RunResult(stats, uploaded)


def run_forever(
    config: Config,
    password: str | None = None,
    *,
    do_upload: bool = True,
    stop: threading.Event | None = None,
    on_run: Callable[[RunResult | None, str | None], None] | None = None,
    on_wait: Callable[[datetime], None] | None = None,
) -> None:
    """Run every ``config.interval`` seconds until ``stop`` is set.

    A failed run is logged and the next one happens on time: a network outage
    or a locked input file must not end the loop. ``on_run`` gets the result
    or the error text; ``on_wait`` gets the time of the next run.
    """
    stop = stop or threading.Event()
    if do_upload:
        password = resolve_password(config, password)
    while not stop.is_set():
        started = time.monotonic()
        try:
            result = run_once(config, password, do_upload=do_upload, stop=stop)
        except RunError as exc:
            if stop.is_set():
                break
            log.error("%s", exc)
            if on_run:
                on_run(None, str(exc))
        else:
            if on_run:
                on_run(result, None)

        if stop.is_set():
            break
        delay = max(0.0, config.interval - (time.monotonic() - started))
        next_run = datetime.now() + timedelta(seconds=delay)
        log.info("Next run at %s", next_run.strftime("%H:%M:%S"))
        if on_wait:
            on_wait(next_run)
        _wait(stop, delay)


def _wait(stop: threading.Event, seconds: float) -> None:
    """Like ``stop.wait(seconds)``, but in short steps so Ctrl+C works on Windows too."""
    deadline = time.monotonic() + seconds
    while not stop.is_set():
        left = deadline - time.monotonic()
        if left <= 0:
            return
        stop.wait(min(left, 0.5))

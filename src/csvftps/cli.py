"""Command line interface: ``csvftps run``, ``csvftps convert``, ``csvftps set-password`` …"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from csvftps import __version__
from csvftps import config as settings
from csvftps.config import Config, ConfigError
from csvftps.credentials import CredentialsError, delete_password, get_password, set_password
from csvftps.runner import RunError, convert, resolve_password, run_forever, run_once
from csvftps.upload import UploadError, test_connection

log = logging.getLogger("csvftps")

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c",
        "--config",
        metavar="FILE",
        type=Path,
        help=f"settings file (default: {settings.default_config_path()})",
    )
    common.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors")
    common.add_argument("--log-file", metavar="FILE", type=Path, help="also append the log to FILE")

    parser = argparse.ArgumentParser(
        prog="csvftps",
        description="Convert a CSV or Excel file with your rules and upload it to an FTPS server.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    init = commands.add_parser("init", parents=[common], help="create a settings file with the defaults")
    init.add_argument("--force", action="store_true", help="overwrite an existing settings file")

    run = commands.add_parser("run", parents=[common], help="convert and upload, then repeat on schedule")
    run.add_argument("--once", action="store_true", help="run once and exit")
    run.add_argument("--no-upload", action="store_true", help="only convert, do not upload")
    run.add_argument("--interval", type=int, metavar="SECONDS", help="override the time between runs")

    conv = commands.add_parser("convert", parents=[common], help="only convert the input file, once")
    conv.add_argument("-i", "--input", metavar="FILE", help="override the input file")
    conv.add_argument("-o", "--output", metavar="FILE", help="override the output file")

    password = commands.add_parser(
        "set-password", parents=[common], help="save the FTPS password in the system keyring"
    )
    password.add_argument("--delete", action="store_true", help="forget the saved password")

    commands.add_parser("test", parents=[common], help="check that the FTPS login works")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(quiet=args.quiet, log_file=args.log_file)
    path = args.config or settings.default_config_path()

    if args.command == "init":
        return cmd_init(path, force=args.force)
    try:
        config = load_config(path)
        if args.command == "run":
            if args.interval is not None:
                config.interval = args.interval
                settings.validate(config)
            return cmd_run(config, once=args.once, do_upload=not args.no_upload)
        if args.command == "convert":
            if args.input:
                config.input = str(Path(args.input).resolve())
            if args.output:
                config.output = str(Path(args.output).resolve())
            convert(config)
            return EXIT_OK
        if args.command == "set-password":
            return cmd_password(config, delete=args.delete)
        if args.command == "test":
            folder = test_connection(config.server, resolve_password(config))
            print(f"OK: logged in to {config.server.host}, remote folder {folder}")
            return EXIT_OK
    except ConfigError as exc:
        log.error("%s", exc)
        return EXIT_USAGE
    except (RunError, UploadError, CredentialsError) as exc:
        log.error("%s", exc)
        return EXIT_FAILED
    raise AssertionError(args.command)


def setup_logging(*, quiet: bool = False, log_file: Path | None = None) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
    log.handlers[:] = handlers
    log.setLevel(logging.WARNING if quiet else logging.INFO)
    log.propagate = False


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"no settings file at {path}: create one with `csvftps init`")
    return settings.load(path)


def cmd_init(path: Path, *, force: bool) -> int:
    if path.exists() and not force:
        log.error("%s already exists; use --force to overwrite it", path)
        return EXIT_USAGE
    config = Config(base_dir=path.parent)
    settings.save(config, path)
    print(f"Created {path}")
    print("Next: fill in the [files] and [server] sections, then run `csvftps set-password`.")
    return EXIT_OK


def cmd_run(config: Config, *, once: bool, do_upload: bool) -> int:
    if once:
        result = run_once(config, do_upload=do_upload)
        return EXIT_OK if result.complete else EXIT_FAILED

    stop = threading.Event()
    log.info("Running every %d s. Press Ctrl+C to stop.", config.interval)
    try:
        run_forever(config, do_upload=do_upload, stop=stop)
    except KeyboardInterrupt:
        stop.set()
        log.info("Stopped.")
    return EXIT_OK


def cmd_password(config: Config, *, delete: bool) -> int:
    server = config.server
    if delete:
        found = delete_password(server)
        print("Password removed." if found else "No saved password.")
        return EXIT_OK
    if not server.host or not server.user:
        raise ConfigError("set [server] host and user in the settings file first")
    if get_password(server) is not None:
        print(f"A password for {server.user}@{server.host} is already saved; it will be replaced.")
    password = getpass.getpass(f"FTPS password for {server.user}@{server.host}: ")
    if not password:
        print("Empty password, nothing saved.", file=sys.stderr)
        return EXIT_USAGE
    set_password(server, password)
    print("Password saved in the system keyring.")
    return EXIT_OK

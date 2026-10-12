"""Settings: which files to convert and upload, the conversion rules and the FTPS server.

Settings live in a TOML file. Relative paths in it are resolved against the
folder that holds the file, so a project folder with its own ``csvftps.toml``
can be moved around freely. The FTPS password is never stored here; see
:mod:`csvftps.credentials`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

CONFIG_ENV = "CSVFTPS_CONFIG"
CONFIG_NAME = "config.toml"


class ConfigError(ValueError):
    """The settings file is missing values or has values of the wrong type."""


@dataclass
class Range:
    """Numbers from ``min`` (inclusive) up to ``max`` (exclusive) become ``label``.

    Leave ``min`` or ``max`` as ``None`` for an open end.
    """

    label: str
    min: float | None = None
    max: float | None = None

    def contains(self, number: float) -> bool:
        return (self.min is None or number >= self.min) and (self.max is None or number < self.max)


def default_ranges() -> list[Range]:
    """The size groups of the original script: None, 2-5, 6-10 and over 10 inches.

    The original cut the decimals off before comparing (``int(float(x))``), so
    5.9 counted as 5 and 10.7 as 10. Half-open ranges give the same result.
    """
    return [
        Range("None", max=2),
        Range("2-5 inch", min=2, max=6),
        Range("6-10 inch", min=6, max=11),
        Range("> 10 inch", min=11),
    ]


@dataclass
class Rules:
    """How the input CSV is read and which column is converted."""

    delimiter: str = ";"
    input_encoding: str = "utf-8-sig"  # also reads plain UTF-8, and drops a BOM if there is one
    output_encoding: str = "utf-8"
    # The first row is always a header. Rows whose ``header_column`` holds one
    # of ``header_markers`` are headers too and are copied unchanged.
    header_column: int = 3
    header_markers: list[str] = field(default_factory=lambda: ["Name Exchange"])
    # Column to convert: a 0-based index, or a name looked up in the header row.
    column: int | str = 4
    empty_values: list[str] = field(default_factory=lambda: ["", "NULL"])
    empty_label: str = "None"
    ranges: list[Range] = field(default_factory=default_ranges)


@dataclass
class Server:
    """An FTP server with explicit TLS (FTPS). The password is kept separately."""

    host: str = ""
    port: int = 21
    user: str = ""
    remote_dir: str = ""
    timeout: float = 30
    retries: int = 3
    retry_delay: float = 10
    # Turn off only for a server with a self-signed certificate you trust.
    verify_certificate: bool = True


@dataclass
class Config:
    input: str = "input.csv"
    output: str = "output.csv"
    extra_files: list[str] = field(default_factory=list)
    interval: int = 600  # seconds between runs
    rules: Rules = field(default_factory=Rules)
    server: Server = field(default_factory=Server)
    # Folder that relative paths are resolved against; not saved to the file.
    base_dir: Path = field(default_factory=Path.cwd, compare=False)

    def resolve(self, path: str) -> Path:
        return (self.base_dir / Path(path).expanduser()).resolve()

    @property
    def input_path(self) -> Path:
        return self.resolve(self.input)

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output)

    @property
    def upload_paths(self) -> list[Path]:
        """Everything that is uploaded on each run: the extra files, then the converted CSV."""
        return [self.resolve(p) for p in self.extra_files] + [self.output_path]


def default_config_path() -> Path:
    """``$CSVFTPS_CONFIG``, or ``%APPDATA%\\csvftps\\config.toml`` (``~/.config/csvftps`` elsewhere)."""
    if os.environ.get(CONFIG_ENV):
        return Path(os.environ[CONFIG_ENV]).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "csvftps" / CONFIG_NAME


# ------------------------------------------------------------------- loading


def load(path: str | os.PathLike[str]) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    try:
        config = from_dict(data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    config.base_dir = path.resolve().parent
    return config


def from_dict(data: dict[str, Any]) -> Config:
    data = dict(data)
    files = _table(data, "files")
    csv = _table(data, "csv")
    convert = _table(data, "convert")
    server = _table(data, "server")
    config = Config(
        input=_get(files, "input", str, "files", Config.input),
        output=_get(files, "output", str, "files", Config.output),
        extra_files=_get_str_list(files, "extra", "files", []),
        interval=_get(data, "interval", int, "", Config.interval),
        rules=Rules(
            delimiter=_get(csv, "delimiter", str, "csv", Rules.delimiter),
            input_encoding=_get(csv, "input_encoding", str, "csv", Rules.input_encoding),
            output_encoding=_get(csv, "output_encoding", str, "csv", Rules.output_encoding),
            header_column=_get(csv, "header_column", int, "csv", Rules.header_column),
            header_markers=_get_str_list(csv, "header_markers", "csv", ["Name Exchange"]),
            column=_get(convert, "column", (int, str), "convert", Rules.column),
            empty_values=_get_str_list(convert, "empty_values", "convert", ["", "NULL"]),
            empty_label=_get(convert, "empty_label", str, "convert", Rules.empty_label),
            ranges=_get_ranges(convert),
        ),
        server=Server(
            host=_get(server, "host", str, "server", Server.host),
            port=_get(server, "port", int, "server", Server.port),
            user=_get(server, "user", str, "server", Server.user),
            remote_dir=_get(server, "remote_dir", str, "server", Server.remote_dir),
            timeout=_get(server, "timeout", (int, float), "server", Server.timeout),
            retries=_get(server, "retries", int, "server", Server.retries),
            retry_delay=_get(server, "retry_delay", (int, float), "server", Server.retry_delay),
            verify_certificate=_get(server, "verify_certificate", bool, "server", Server.verify_certificate),
        ),
    )
    for section, table in (("", data), ("files", files), ("csv", csv), ("convert", convert)):
        _reject_unknown(table, section)
    _reject_unknown(server, "server")
    validate(config)
    return config


def validate(config: Config) -> None:
    """Raise :class:`ConfigError` for values that can never work."""
    rules = config.rules
    if len(rules.delimiter) != 1:
        raise ConfigError("csv.delimiter must be exactly one character")
    if rules.header_column < 0:
        raise ConfigError("csv.header_column must be 0 or more")
    if isinstance(rules.column, int) and rules.column < 0:
        raise ConfigError("convert.column must be 0 or more")
    if isinstance(rules.column, str) and not rules.column:
        raise ConfigError("convert.column must not be empty")
    for number, item in enumerate(rules.ranges, 1):
        if item.min is not None and item.max is not None and item.min >= item.max:
            raise ConfigError(f"convert.ranges #{number} ({item.label!r}): min must be less than max")
    if config.interval < 1:
        raise ConfigError("interval must be at least 1 second")
    if not 0 < config.server.port < 65536:
        raise ConfigError("server.port must be between 1 and 65535")
    if config.server.retries < 0:
        raise ConfigError("server.retries must be 0 or more")


def _where(section: str, key: str) -> str:
    return f"{section}.{key}" if section else key


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    table = data.pop(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"[{name}] must be a table")
    return dict(table)


def _get(table: dict[str, Any], key: str, kind: type | tuple[type, ...], section: str, default: Any) -> Any:
    if key not in table:
        return default
    value = table.pop(key)
    kinds = kind if isinstance(kind, tuple) else (kind,)
    # bool is a subclass of int, but `port = true` is surely a mistake.
    if (isinstance(value, bool) and bool not in kinds) or not isinstance(value, kinds):
        names = " or ".join(t.__name__ for t in kinds)
        raise ConfigError(f"{_where(section, key)} must be {names}, got {value!r}")
    return value


def _get_str_list(table: dict[str, Any], key: str, section: str, default: list[str]) -> list[str]:
    value = _get(table, key, list, section, default)
    if not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{_where(section, key)} must be a list of strings")
    return list(value)


def _get_ranges(table: dict[str, Any]) -> list[Range]:
    if "ranges" not in table:
        return default_ranges()
    ranges = []
    for number, item in enumerate(_get(table, "ranges", list, "convert", []), 1):
        if not isinstance(item, dict):
            raise ConfigError(f"convert.ranges #{number} must be a table")
        where = f"convert.ranges #{number}"
        item = dict(item)
        if "label" not in item:
            raise ConfigError(f"{where} needs a label")
        ranges.append(
            Range(
                label=_get(item, "label", str, where, ""),
                min=_get(item, "min", (int, float), where, None),
                max=_get(item, "max", (int, float), where, None),
            )
        )
        _reject_unknown(item, where)
    return ranges


def _reject_unknown(table: dict[str, Any], section: str) -> None:
    """Typos in key names would otherwise be silently ignored."""
    if table:
        names = ", ".join(sorted(_where(section, key) for key in table))
        raise ConfigError(f"unknown setting(s): {names}")


# -------------------------------------------------------------------- saving


def to_dict(config: Config) -> dict[str, Any]:
    rules, server = config.rules, config.server

    def number(value: float) -> int | float:
        return int(value) if float(value).is_integer() else value

    ranges = []
    for item in rules.ranges:
        entry: dict[str, Any] = {}
        if item.min is not None:
            entry["min"] = number(item.min)
        if item.max is not None:
            entry["max"] = number(item.max)
        entry["label"] = item.label
        ranges.append(entry)

    return {
        "interval": config.interval,
        "files": {"input": config.input, "output": config.output, "extra": list(config.extra_files)},
        "csv": {
            "delimiter": rules.delimiter,
            "input_encoding": rules.input_encoding,
            "output_encoding": rules.output_encoding,
            "header_column": rules.header_column,
            "header_markers": list(rules.header_markers),
        },
        "convert": {
            "column": rules.column,
            "empty_values": list(rules.empty_values),
            "empty_label": rules.empty_label,
            "ranges": ranges,
        },
        "server": {
            "host": server.host,
            "port": server.port,
            "user": server.user,
            "remote_dir": server.remote_dir,
            "timeout": number(server.timeout),
            "retries": server.retries,
            "retry_delay": number(server.retry_delay),
            "verify_certificate": server.verify_certificate,
        },
    }


def save(config: Config, path: str | os.PathLike[str]) -> Path:
    """Write the settings as TOML, replacing the file in one step."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(HEADER + tomli_w.dumps(to_dict(config)), encoding="utf-8")
    os.replace(temp, path)
    return path


HEADER = """\
# csvftps settings. See https://github.com/SilentCasting/csvftps#settings
# The FTPS password is not stored here: run `csvftps set-password`
# or set the CSVFTPS_PASSWORD environment variable.

"""

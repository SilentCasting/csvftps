"""Convert one column of a CSV file into named ranges, e.g. ``7.5`` -> ``6-10 inch``."""

from __future__ import annotations

import csv
import logging
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from csvftps.config import Rules

log = logging.getLogger(__name__)

# Problems reported per run before the rest are only counted.
MAX_LOGGED_PROBLEMS = 10


@dataclass
class Stats:
    rows: int = 0  # all rows written, headers included
    headers: int = 0
    converted: int = 0
    empty: int = 0  # empty or NULL values that got ``empty_label``
    skipped: int = 0  # rows left unchanged: too short, not a number or outside every range
    problems: list[str] = field(default_factory=list)


def parse_number(text: str) -> float | None:
    """Read ``12``, ``12.5`` or ``12,5`` (decimal comma); return None for anything else."""
    try:
        number = float(text.strip().replace(",", "."))
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None  # no NaN / inf


def convert_value(value: str, rules: Rules) -> str | None:
    """Return the new text for ``value``, or None if it should stay as it is."""
    if value.strip() in rules.empty_values:
        return rules.empty_label
    number = parse_number(value)
    if number is None:
        return None
    for item in rules.ranges:
        if item.contains(number):
            return item.label
    return None


def is_header(row: list[str], index: int, rules: Rules) -> bool:
    if index == 0:
        return True
    column = rules.header_column
    return column < len(row) and row[column] in rules.header_markers


def find_column(header: list[str], rules: Rules) -> int | None:
    """Index of the column to convert, or None if it is named and not in this header."""
    if isinstance(rules.column, int):
        return rules.column
    names = [name.strip().casefold() for name in header]
    target = rules.column.strip().casefold()
    return names.index(target) if target in names else None


def convert_rows(rows: Iterable[list[str]], rules: Rules, stats: Stats) -> Iterator[list[str]]:
    """Yield the rows with the target column converted; header rows pass through unchanged.

    A file may contain several header rows (one per section). A column given by
    name is looked up again in each of them.
    """
    column: int | None = None
    for index, row in enumerate(rows):
        line = index + 1
        stats.rows += 1
        if is_header(row, index, rules):
            stats.headers += 1
            column = find_column(row, rules)
            if column is None:
                _problem(stats, f"line {line}: header has no column named {rules.column!r}")
            yield row
            continue

        if column is None or column >= len(row):
            stats.skipped += 1
            if column is not None:
                _problem(stats, f"line {line}: only {len(row)} column(s), kept as is")
            yield row
            continue

        new = convert_value(row[column], rules)
        if new is None:
            stats.skipped += 1
            _problem(stats, f"line {line}: {row[column]!r} is not a number in any range, kept as is")
        else:
            if row[column].strip() in rules.empty_values:
                stats.empty += 1
            else:
                stats.converted += 1
            row = row[:column] + [new] + row[column + 1 :]
        yield row


def convert_file(source: str | os.PathLike[str], target: str | os.PathLike[str], rules: Rules) -> Stats:
    """Convert ``source`` into ``target``.

    The result is written to a temporary file first and then moved into place,
    so ``target`` is never half-written, even if the input turns out broken.
    """
    source, target = Path(source), Path(target)
    stats = Stats()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.tmp")
    try:
        with (
            source.open(newline="", encoding=rules.input_encoding) as infile,
            temp.open("w", newline="", encoding=rules.output_encoding) as outfile,
        ):
            reader = csv.reader(infile, delimiter=rules.delimiter)
            writer = csv.writer(outfile, delimiter=rules.delimiter)
            writer.writerows(convert_rows(reader, rules, stats))
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)

    hidden = len(stats.problems) - MAX_LOGGED_PROBLEMS
    for problem in stats.problems[:MAX_LOGGED_PROBLEMS]:
        log.warning("%s: %s", source.name, problem)
    if hidden > 0:
        log.warning("%s: %d more row(s) kept as is", source.name, hidden)
    return stats


def _problem(stats: Stats, text: str) -> None:
    stats.problems.append(text)

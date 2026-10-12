from __future__ import annotations

import random
from pathlib import Path

import pytest

from csvftps.config import Range, Rules
from csvftps.transform import Stats, convert_file, convert_rows, convert_value, parse_number


def legacy_size(value: str) -> str:
    """The conversion exactly as the original 2022 script did it."""
    if value == "NULL" or 2 > int(float(value)):
        return "None"
    elif 5 >= int(float(value)) >= 2:
        return "2-5 inch"
    elif 10 >= int(float(value)) >= 6:
        return "6-10 inch"
    elif int(float(value)) >= 10:
        return "> 10 inch"
    raise AssertionError(value)


def test_default_rules_match_the_original_script() -> None:
    rules = Rules()
    rng = random.Random(42)
    values = ["NULL", "0", "1.99", "2", "5", "5.99", "6", "10", "10.99", "11", "65", "-3", "-0.5"]
    values += [f"{rng.uniform(-5, 100):.3f}" for _ in range(2000)]
    for value in values:
        assert convert_value(value, rules) == legacy_size(value), value


@pytest.mark.parametrize(
    ("text", "number"),
    [("12", 12.0), (" 7.5 ", 7.5), ("7,5", 7.5), ("-1", -1.0), ("abc", None), ("", None), ("nan", None)],
)
def test_parse_number(text: str, number: float | None) -> None:
    assert parse_number(text) == number


def test_empty_values_and_unknown_text() -> None:
    rules = Rules(empty_values=["", "NULL", "n/a"], empty_label="-")
    assert convert_value("", rules) == "-"
    assert convert_value("n/a", rules) == "-"
    assert convert_value("big", rules) is None


def test_custom_ranges_first_match_wins() -> None:
    rules = Rules(ranges=[Range("small", max=10), Range("any")])
    assert convert_value("3", rules) == "small"
    assert convert_value("30", rules) == "any"


def test_value_outside_every_range_is_kept() -> None:
    rules = Rules(column=1, ranges=[Range("small", min=0, max=10)])
    stats = Stats()
    rows = list(convert_rows([["h1", "h2"], ["a", "50"]], rules, stats))
    assert rows[1] == ["a", "50"]
    assert stats.skipped == 1
    assert "not a number in any range" in stats.problems[0]


def test_header_rows_are_copied_unchanged() -> None:
    rules = Rules(header_column=0, header_markers=["Section"], column=1)
    rows = [["Name", "Size"], ["a", "3"], ["Section", "Size"], ["b", "12"]]
    stats = Stats()
    assert list(convert_rows(rows, rules, stats)) == [
        ["Name", "Size"],
        ["a", "2-5 inch"],
        ["Section", "Size"],
        ["b", "> 10 inch"],
    ]
    assert (stats.rows, stats.headers, stats.converted) == (4, 2, 2)


def test_column_by_name_is_looked_up_in_each_header() -> None:
    rules = Rules(header_column=0, header_markers=["Section"], column="size")
    rows = [["Size", "Name"], ["3", "a"], ["Section", "Size"], ["b", "7"]]
    out = list(convert_rows(rows, rules, Stats()))
    assert out[1] == ["2-5 inch", "a"]
    assert out[3] == ["b", "6-10 inch"]


def test_missing_named_column_keeps_rows() -> None:
    stats = Stats()
    out = list(convert_rows([["a", "b"], ["1", "2"]], Rules(column="Size"), stats))
    assert out == [["a", "b"], ["1", "2"]]
    assert stats.skipped == 1
    assert "no column named 'Size'" in stats.problems[0]


def test_short_rows_are_kept() -> None:
    stats = Stats()
    out = list(convert_rows([["a", "b", "c", "d", "e"], ["only", "three", "cols"]], Rules(), stats))
    assert out[1] == ["only", "three", "cols"]
    assert stats.skipped == 1


def test_convert_file(tmp_path: Path) -> None:
    source = tmp_path / "in.csv"
    source.write_bytes(
        '﻿Id;Name;City;Group;Size\r\n1;"Smith; John";Kyiv;A;7,2\r\n2;Ann;Lviv;B;NULL\r\n'.encode()
    )
    target = tmp_path / "sub" / "out.csv"
    stats = convert_file(source, target, Rules())
    assert target.read_text(encoding="utf-8").splitlines() == [
        "Id;Name;City;Group;Size",  # BOM removed
        '1;"Smith; John";Kyiv;A;6-10 inch',  # quoted delimiter kept intact
        "2;Ann;Lviv;B;None",
    ]
    assert (stats.converted, stats.empty) == (1, 1)
    assert not list(tmp_path.glob("sub/.*.tmp"))


def test_failed_conversion_leaves_old_output(tmp_path: Path) -> None:
    source = tmp_path / "in.csv"
    source.write_bytes(b"a;b\n\xff\xfe;1\n")
    target = tmp_path / "out.csv"
    target.write_text("previous", encoding="utf-8")
    with pytest.raises(UnicodeDecodeError):
        convert_file(source, target, Rules())
    assert target.read_text(encoding="utf-8") == "previous"
    assert [p.name for p in tmp_path.iterdir()] == ["in.csv", "out.csv"]

"""Read and write Excel workbooks (.xlsx, .xlsm) as rows of text, like a CSV file.

Cells are turned into the text a CSV export would hold: ``12``, ``7.5``,
``2026-10-25``, ``TRUE``. Formulas give the value Excel last calculated.
When writing, text that is plainly a number is stored as a number again, so
the sheet does not fill up with "number stored as text" warnings.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

READ_SUFFIXES = {".xlsx", ".xlsm"}
WRITE_SUFFIXES = {".xlsx"}
SHEET_TITLE = "Sheet1"
MAX_COLUMN_WIDTH = 60

# Only plain numbers that come back unchanged; "007", "1e5" and "7,5" stay text.
_INT = re.compile(r"-?(0|[1-9]\d{0,14})")
_FLOAT = re.compile(r"-?(0|[1-9]\d{0,14})\.\d{0,14}[1-9]")


class ExcelError(ValueError):
    """The workbook cannot be read: not an Excel file, damaged, or no such sheet."""


def is_excel(path: str | Path) -> bool:
    return Path(path).suffix.lower() in READ_SUFFIXES


def cell_text(value: object) -> str:
    """The text a CSV export would show for a cell value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time() else value.isoformat(sep=" ")
    if isinstance(value, date | time):
        return value.isoformat()
    return str(value)


def cell_value(text: str) -> str | int | float | None:
    """The value to store for ``text``: a number if it plainly is one, otherwise the text."""
    if text == "":
        return None
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    return text


@contextmanager
def read_rows(path: Path, sheet: int | str = "") -> Iterator[Iterator[list[str]]]:
    """Open a sheet and yield its rows as lists of text.

    ``sheet`` is a name, a number starting at 1, or ``""`` for the first sheet.
    Empty cells at the end of a row and empty rows at the end of the sheet
    are dropped, the same as in a CSV export.
    """
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException, KeyError) as exc:
        raise ExcelError(f"{path.name} is not a valid Excel workbook ({exc})") from exc
    try:
        worksheet = _pick_sheet(workbook, sheet, path.name)
        # Some programs write wrong size info into the file; read to the real end instead.
        worksheet.reset_dimensions()
        yield _rows(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()


def write_rows(path: Path, rows: Iterable[list[str]], header_rows: Iterable[int] = ()) -> None:
    """Write rows to a new workbook; rows whose index is in ``header_rows`` are bold."""
    rows = list(rows)
    headers = set(header_rows)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = SHEET_TITLE
    bold = Font(bold=True)
    widths: dict[int, int] = {}
    for row_index, row in enumerate(rows, 1):
        for column_index, text in enumerate(row, 1):
            cell = worksheet.cell(row=row_index, column=column_index, value=cell_value(text))
            if isinstance(cell.value, str) and cell.value.startswith("="):
                cell.data_type = "s"  # data, not a formula to run
            if row_index - 1 in headers:
                cell.font = bold
            widths[column_index] = max(widths.get(column_index, 0), len(text))
    for column_index, width in widths.items():
        letter = get_column_letter(column_index)
        worksheet.column_dimensions[letter].width = min(max(width + 2, 8), MAX_COLUMN_WIDTH)
    if 0 in headers:
        worksheet.freeze_panes = "A2"
    workbook.save(path)


def _pick_sheet(workbook, sheet: int | str, name: str):
    names = workbook.sheetnames
    if sheet == "":
        return workbook.worksheets[0]
    if isinstance(sheet, int):
        if not 1 <= sheet <= len(names):
            raise ExcelError(f"{name} has {len(names)} sheet(s), there is no sheet {sheet}")
        return workbook.worksheets[sheet - 1]
    if sheet not in names:
        raise ExcelError(f"{name} has no sheet named {sheet!r}; it has: {', '.join(names)}")
    return workbook[sheet]


def _rows(values: Iterable[tuple]) -> Iterator[list[str]]:
    blank = 0  # empty rows held back until we know more data follows
    for raw in values:
        row = [cell_text(value) for value in raw]
        while row and row[-1] == "":
            row.pop()
        if not row:
            blank += 1
            continue
        yield from ([] for _ in range(blank))
        blank = 0
        yield row

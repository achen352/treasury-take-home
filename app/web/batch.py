"""Batch checking: reading the spreadsheet of labels, and exporting the results.

The browser reads the spreadsheet through here, then sends each label to /batch/check one at a
time, so the server holds nothing between requests. The spreadsheet may come from Excel or any
other tool, so headers are matched loosely and the usual CSV quirks are handled.
"""

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from app.web.forms import FIELDS, read_application
from app.web.paste import header_field

MAX_ROWS = 300
MAX_SHEET_BYTES = 1024 * 1024
IMAGE_HEADERS = ("images", "image", "label images", "label image", "files", "file names", "file")
VERDICT_ORDER = ("Does not match", "Couldn't check", "Needs review", "Matches")
_BINARY_STARTS = (b"\x89PNG", b"%PDF", b"PK\x03\x04", b"\xff\xd8\xff", b"GIF8")
_IMAGE_SEPARATORS = re.compile(r"[;,|\n]+")


class SheetProblem(ValueError):
    """A spreadsheet that can't be used. The message is plain and safe to show."""


@dataclass(frozen=True)
class BatchRow:
    number: int  # the row's number in the spreadsheet, counting the header as row 1
    images: list[str]
    values: dict[str, str]  # as written; checking tidies them
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Sheet:
    rows: list[BatchRow]
    unknown_columns: list[str]


class BatchResult(BaseModel):
    """One label's outcome, as the browser reports it for export."""

    model_config = ConfigDict(extra="ignore")

    number: int = Field(ge=0, le=100_000)
    images: list[str] = Field(default_factory=list, max_length=20)
    brand: str = Field(default="", max_length=300)
    verdict: str = Field(max_length=40)
    issues: str = Field(default="", max_length=5000)


def read_sheet(data: bytes) -> Sheet:
    if len(data) > MAX_SHEET_BYTES:
        raise SheetProblem("The spreadsheet is larger than 1 MB. Split it into smaller batches.")
    if data.startswith(b"PK\x03\x04"):
        raise SheetProblem("This looks like an Excel workbook. In Excel, choose Save As, then CSV.")
    if data.startswith(_BINARY_STARTS) or b"\x00" in data[:4096]:
        raise SheetProblem("This isn't a CSV file. Save the spreadsheet as CSV and try again.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")  # Excel on Windows saves "CSV" this way
    if not text.strip():
        raise SheetProblem("The spreadsheet is empty.")

    records = list(csv.reader(io.StringIO(text, newline=""), dialect=_dialect(text)))
    numbered = [
        (index + 1, record)
        for index, record in enumerate(records)
        if any(c.strip() for c in record)
    ]
    if not numbered:
        raise SheetProblem("The spreadsheet is empty.")
    (_, header), *body = numbered

    columns: dict[int, str] = {}
    unknown: list[str] = []
    for position, title in enumerate(header):
        name = "images" if _key(title) in IMAGE_HEADERS else header_field(title)
        if name is None:
            if title.strip():
                unknown.append(title.strip())
        elif name not in columns.values():
            columns[position] = name
    if not any(name in FIELDS for name in columns.values()):
        raise SheetProblem(
            "None of the columns were recognised. Download the template to see the headers to use."
        )
    if not body:
        raise SheetProblem("The spreadsheet has no labels below its header row.")
    if len(body) > MAX_ROWS:
        raise SheetProblem(
            f"The spreadsheet has more than {MAX_ROWS} labels. Split it into batches of up to "
            f"{MAX_ROWS}."
        )

    rows = []
    for number, record in body:
        cells = {
            name: record[position] if position < len(record) else ""
            for position, name in columns.items()
        }
        images = [_file_name(part) for part in _IMAGE_SEPARATORS.split(cells.pop("images", ""))]
        images = [name for name in images if name]
        values = {name: value for name, value in cells.items() if name in FIELDS}
        _, errors = read_application(values)
        if not images:
            errors = {**errors, "images": "No images are listed for this label."}
        rows.append(BatchRow(number=number, images=images, values=values, errors=errors))
    return Sheet(rows=rows, unknown_columns=unknown)


def export_csv(results: Sequence[BatchResult]) -> str:
    """The results as a spreadsheet, failures first, with spreadsheet formulas neutralised."""
    rank = {verdict: index for index, verdict in enumerate(VERDICT_ORDER)}
    ordered = sorted(
        results, key=lambda result: (rank.get(result.verdict, len(rank)), result.number)
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["Row", "Images", "Brand", "Result", "Issues"])
    for result in ordered:
        writer.writerow(
            [
                _safe(cell)
                for cell in (
                    str(result.number),
                    "; ".join(result.images),
                    result.brand,
                    result.verdict,
                    result.issues,
                )
            ]
        )
    return buffer.getvalue()


def template_csv() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["images", *[name for name in FIELDS]])
    writer.writerow(
        [
            "old-tom-front.png; old-tom-back.png",
            "spirits",
            "no",
            "OLD TOM DISTILLERY",
            "",
            "Kentucky Straight Bourbon Whiskey",
            "45% Alc./Vol. (90 Proof)",
            "750 mL",
            "Old Tom Distillery, Louisville, Kentucky",
            "",
        ]
    )
    return buffer.getvalue()


def _safe(cell: str) -> str:
    """A cell a spreadsheet won't run as a formula (OWASP's CSV injection advice)."""
    return "'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell


def _dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _key(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.casefold()).split())


def _file_name(path: str) -> str:
    """Just the file name, without any folders, as the browser knows the chosen files."""
    return re.split(r"[\\/]", path.strip())[-1].strip()

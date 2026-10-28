"""Reading the batch spreadsheet and exporting results, however the spreadsheet was saved."""

import csv
import io

import pytest

from app.web.batch import (
    MAX_ROWS,
    MAX_SHEET_BYTES,
    BatchResult,
    SheetProblem,
    export_csv,
    read_sheet,
)

HEADER = "images,beverage_type,brand_name,class_type,alcohol_content,net_contents,bottler"
ROW = 'label.png,spirits,OLD TOM DISTILLERY,Bourbon,45%,750 mL,"Old Tom Distillery, Louisville, KY"'


def sheet(*lines: str, encoding: str = "utf-8") -> bytes:
    return ("\n".join(lines) + "\n").encode(encoding)


def test_a_simple_sheet_gives_one_row_per_label() -> None:
    read = read_sheet(sheet(HEADER, ROW, ROW.replace("label.png", "front.png;back.png")))

    assert [row.number for row in read.rows] == [2, 3]
    assert read.rows[0].images == ["label.png"]
    assert read.rows[1].images == ["front.png", "back.png"]
    assert read.rows[0].values["bottler"] == "Old Tom Distillery, Louisville, KY"
    assert read.rows[0].errors == {}


def test_friendly_headers_in_any_case_or_order_are_recognised() -> None:
    read = read_sheet(
        sheet(
            "Brand Name, NET CONTENTS ,Label Images,Class/Type,Bottler,Type of Product,ABV",
            "OLD TOM,750 mL,label.png,Bourbon,Old Tom Distillery,Distilled Spirits,45%",
        )
    )

    row = read.rows[0]
    assert row.errors == {}
    assert row.images == ["label.png"]
    assert row.values["brand_name"] == "OLD TOM"
    assert row.values["beverage_type"] == "Distilled Spirits"


def test_unknown_columns_are_ignored_and_listed() -> None:
    read = read_sheet(sheet(HEADER + ",Serial Number", ROW + ",26-001"))

    assert read.unknown_columns == ["Serial Number"]
    assert read.rows[0].errors == {}


def test_rows_with_missing_or_misformatted_fields_say_what_is_wrong() -> None:
    read = read_sheet(sheet(HEADER, "label.png,spirits,,Bourbon,forty,750,Old Tom"))

    errors = read.rows[0].errors
    assert set(errors) == {"brand_name", "alcohol_content", "net_contents"}


def test_a_row_with_no_images_listed_is_explained() -> None:
    read = read_sheet(sheet(HEADER, ROW.replace("label.png", "")))

    assert "images" in read.rows[0].errors


@pytest.mark.parametrize("separator", [";", ",", "|"])
def test_image_lists_can_use_semicolons_commas_or_bars(separator: str) -> None:
    images = f'"folder/Front.PNG{separator} back.png"'
    read = read_sheet(sheet(HEADER, ROW.replace("label.png", images)))

    assert read.rows[0].images == ["Front.PNG", "back.png"]  # folders dropped, case kept


def test_excel_quirks_are_handled() -> None:
    semicolons = sheet(
        HEADER.replace(",", ";"),
        ROW.replace(",", ";").replace('"Old Tom Distillery; Louisville; KY"', "Old Tom"),
    )
    bom = b"\xef\xbb\xbf" + sheet(HEADER, ROW)
    windows = sheet(
        HEADER, ROW.replace("OLD TOM DISTILLERY", "Château Ste. Michelle"), encoding="cp1252"
    )
    tabs = sheet(
        HEADER.replace(",", "\t"), "label.png\tspirits\tOLD TOM\tBourbon\t45%\t750 mL\tOld Tom"
    )

    assert read_sheet(semicolons).rows[0].errors == {}
    assert read_sheet(bom).rows[0].values["brand_name"] == "OLD TOM DISTILLERY"
    assert read_sheet(windows).rows[0].values["brand_name"] == "Château Ste. Michelle"
    assert read_sheet(tabs).rows[0].errors == {}


def test_blank_rows_extra_and_missing_cells_are_handled() -> None:
    read = read_sheet(sheet(HEADER, "", ROW + ",extra,cells", ",,,", "label.png,spirits,OLD TOM"))

    assert [row.number for row in read.rows] == [3, 5]
    assert read.rows[0].errors == {}
    assert "class_type" in read.rows[1].errors  # the short row is missing its later cells


def test_a_cell_with_a_line_break_inside_quotes_stays_one_cell() -> None:
    read = read_sheet(
        sheet(
            HEADER,
            ROW.replace(
                '"Old Tom Distillery, Louisville, KY"', '"Old Tom Distillery\nLouisville, KY"'
            ),
        )
    )

    assert read.rows[0].values["bottler"] == "Old Tom Distillery\nLouisville, KY"
    assert read.rows[0].errors == {}


def test_formula_looking_cells_are_read_as_plain_text() -> None:
    read = read_sheet(sheet(HEADER, ROW.replace("OLD TOM DISTILLERY", '=HYPERLINK("x")')))

    assert read.rows[0].values["brand_name"] == '=HYPERLINK("x")'


@pytest.mark.parametrize(
    "data",
    [b"", b"   \n  \n", sheet("just one line without a header"), b"\x89PNG\r\n\x1a\n" + bytes(100)],
    ids=["empty", "blank", "no-rows", "not-a-csv"],
)
def test_sheets_that_cannot_be_used_get_a_plain_message(data: bytes) -> None:
    with pytest.raises(SheetProblem):
        read_sheet(data)


def test_more_than_three_hundred_rows_or_too_big_a_file_is_refused() -> None:
    with pytest.raises(SheetProblem, match=str(MAX_ROWS)):
        read_sheet(sheet(HEADER, *[ROW] * (MAX_ROWS + 1)))
    with pytest.raises(SheetProblem, match="1 MB"):
        read_sheet(b"x" * (MAX_SHEET_BYTES + 1))


# ---- export ----


def result(number: int, verdict: str, brand: str = "OLD TOM", issues: str = "") -> BatchResult:
    return BatchResult(
        number=number, images=["label.png"], brand=brand, verdict=verdict, issues=issues
    )


def test_the_export_lists_failures_first() -> None:
    rows = list(
        csv.reader(
            io.StringIO(
                export_csv(
                    [
                        result(2, "Matches"),
                        result(3, "Needs review"),
                        result(4, "Does not match"),
                        result(5, "Couldn't check"),
                    ]
                )
            )
        )
    )

    assert rows[0] == ["Row", "Images", "Brand", "Result", "Issues"]
    assert [row[3] for row in rows[1:]] == [
        "Does not match",
        "Couldn't check",
        "Needs review",
        "Matches",
    ]


@pytest.mark.parametrize("hostile", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tTAB", "\rCR"])
def test_spreadsheet_formulas_in_the_export_are_neutralised(hostile: str) -> None:
    rows = list(
        csv.reader(io.StringIO(export_csv([result(2, "Matches", brand=hostile, issues=hostile)])))
    )

    assert rows[1][2] == "'" + hostile
    assert rows[1][4] == "'" + hostile

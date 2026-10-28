"""The batch page and its endpoints: read a spreadsheet, check one label, export results."""

import csv
import io
import json
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.constants import HEALTH_WARNING
from app.main import create_app
from app.readers.extractor import ImageReading
from app.web.batch import read_sheet
from scripts.fixtures import FIXTURES_ROOT
from tests.fakes import FakeExtractor, FakeOcr
from tests.samples import OLD_TOM_LABEL_LINES, OLD_TOM_READING

OLD_TOM_PNG = (FIXTURES_ROOT / "synthetic" / "old-tom" / "label.png").read_bytes()
FORM = {
    "beverage_type": "spirits",
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "bottler": "Old Tom Distillery, Louisville, Kentucky",
}


def make_client(**overrides: object) -> TestClient:
    settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    app = create_app(
        settings,
        extractor=FakeExtractor(ImageReading(OLD_TOM_READING)),
        ocr_reader=FakeOcr([(*OLD_TOM_LABEL_LINES, HEALTH_WARNING)] * 6),
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client() as test_client:
        yield test_client


def test_the_main_page_links_to_the_batch_page(client: TestClient) -> None:
    assert '<a href="/batch">Check many labels at once</a>' in client.get("/").text


def test_the_batch_page_walks_through_three_steps_with_no_inline_script(client: TestClient) -> None:
    page = client.get("/batch").text

    steps = re.findall(r'<h2 class="step"><span class="step-number">(\d)</span>', page)
    assert steps == ["1", "2", "3"]
    assert re.search(r'<input[^>]+type="file"[^>]+name="sheet"[^>]+accept="[^"]*\.csv', page)
    assert re.search(r'<input[^>]+type="file"[^>]+name="images"[^>]+multiple', page)
    assert '<a href="/batch/template.csv"' in page
    assert re.search(r'<button type="button" class="run-example"', page)
    assert '<script src="/static/batch.js" defer></script>' in page
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", page)
    assert page.count("<h1") == 1


def test_the_template_is_a_spreadsheet_the_reader_accepts(client: TestClient) -> None:
    response = client.get("/batch/template.csv")

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    sheet = read_sheet(response.content)
    assert len(sheet.rows) == 1 and sheet.rows[0].errors == {}


def test_a_spreadsheet_is_read_into_rows_with_their_problems(client: TestClient) -> None:
    data = (
        b"images,beverage_type,brand_name,class_type,alcohol_content,net_contents,bottler\n"
        b"label.png,spirits,OLD TOM,Bourbon,45%,750 mL,Old Tom\n"
        b"x.png,spirits,,Bourbon,45%,750,Old Tom\n"
    )

    response = client.post("/batch/read", files={"sheet": ("labels.csv", data, "text/csv")})

    body = response.json()
    assert response.status_code == 200
    assert [row["number"] for row in body["rows"]] == [2, 3]
    assert body["rows"][0]["errors"] == {}
    assert set(body["rows"][1]["errors"]) == {"brand_name", "net_contents"}


def test_a_spreadsheet_that_cannot_be_used_gets_a_plain_message(client: TestClient) -> None:
    response = client.post("/batch/read", files={"sheet": ("x.csv", b"", "text/csv")})

    assert response.status_code == 422
    assert response.json()["error"]


def test_the_example_batch_is_the_eleven_samples(client: TestClient) -> None:
    rows = client.get("/batch/samples").json()["rows"]

    assert len(rows) == 11
    assert all(row["sample"] and row["values"]["brand_name"] for row in rows)


def test_one_label_is_checked_and_answered_briefly(client: TestClient) -> None:
    response = client.post("/batch/check", data=FORM, files=[("images", ("l.png", OLD_TOM_PNG))])

    body = response.json()
    assert response.status_code == 200
    assert body["verdict"] == "Matches"
    assert body["summary"].startswith("6 of 6 items match")
    item = body["items"][0]
    assert {"name", "status", "status_word", "expected", "found", "notes"} <= set(item)
    assert "data:image" not in response.text  # no images come back


def test_a_sample_can_be_checked_by_name(client: TestClient) -> None:
    response = client.post("/batch/check", data={**FORM, "sample": "old-tom"})

    assert response.json()["verdict"] == "Matches"


def test_a_label_that_cannot_be_checked_says_why(client: TestClient) -> None:
    bad_form = client.post(
        "/batch/check",
        data={**FORM, "net_contents": "750"},
        files=[("images", ("l.png", OLD_TOM_PNG))],
    )
    bad_image = client.post(
        "/batch/check", data=FORM, files=[("images", ("l.png", b"<html></html>"))]
    )

    assert bad_form.status_code == 422 and "unit" in bad_form.json()["error"]
    assert bad_image.status_code == 422 and bad_image.json()["error"]


def test_batch_checks_keep_the_same_guards() -> None:
    with make_client(rate_limit_per_minute=1) as client:
        first = client.post("/batch/check", data={**FORM, "sample": "old-tom"})
        second = client.post("/batch/check", data={**FORM, "sample": "old-tom"})
        cross = client.post(
            "/batch/check",
            data={**FORM, "sample": "old-tom"},
            headers={"sec-fetch-site": "cross-site"},
        )

    assert first.status_code == 200
    assert second.status_code == 429 and second.headers["retry-after"]
    assert cross.status_code == 403


def test_the_results_export_as_a_spreadsheet_with_failures_first_and_formulas_neutralised(
    client: TestClient,
) -> None:
    results = [
        {"number": 2, "images": ["a.png"], "brand": "OLD TOM", "verdict": "Matches", "issues": ""},
        {
            "number": 3,
            "images": ["b.png"],
            "brand": "=1+1",
            "verdict": "Does not match",
            "issues": "Alcohol content: does not match",
        },
    ]

    response = client.post("/batch/export", data={"results": json.dumps(results)})

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[1][3] == "Does not match"
    assert rows[1][2] == "'=1+1"


def test_an_export_that_is_not_results_is_refused(client: TestClient) -> None:
    assert client.post("/batch/export", data={"results": "not json"}).status_code == 422
    too_many = [
        {"number": n, "images": [], "brand": "", "verdict": "Matches", "issues": ""}
        for n in range(301)
    ]
    assert client.post("/batch/export", data={"results": json.dumps(too_many)}).status_code == 422

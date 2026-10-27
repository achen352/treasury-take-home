"""The OCR reader: Tesseract run directly, its words and boxes, and finding fields in them.

Tests marked `ocr` run the real Tesseract binary; the rest use canned output.
"""

import io
import subprocess

import pytest
from PIL import Image, ImageDraw

from app.domain.constants import HEALTH_WARNING
from app.domain.crosscheck import cross_check
from app.domain.models import (
    Box,
    DiffOp,
    LabelField,
    Location,
    Reader,
    Status,
    Verdict,
)
from app.domain.verifier import verify
from app.readers import ocr
from app.readers.ocr import (
    OcrUnavailable,
    attach_locations,
    has_warning_header,
    locate,
    parse_tsv,
    read_page,
    reading_from_ocr,
    rotate_box_back,
    run_tesseract,
)
from app.readers.uploads import LabelImage, prepare_upload
from scripts.fixtures import FIXTURES_ROOT, load_fixtures
from tests.fakes import words_page
from tests.samples import OLD_TOM_APPLICATION, OLD_TOM_READING

SYNTHETIC = FIXTURES_ROOT / "synthetic"
TSV_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
)


def label(name: str, image: str = "label.png") -> LabelImage:
    return prepare_upload((SYNTHETIC / name / image).read_bytes())[0]


def tsv(*rows: tuple[int, int, int, int, int, int, int, float, str]) -> str:
    """Tesseract's TSV for word rows given as (block, par, line, word, left, top, width, conf,
    text); every word is 40 pixels tall."""
    lines = [TSV_HEADER, "1\t1\t0\t0\t0\t0\t0\t0\t1600\t2000\t-1\t"]
    for block, par, line, word, left, top, width, conf, text in rows:
        lines.append(
            f"5\t1\t{block}\t{par}\t{line}\t{word}\t{left}\t{top}\t{width}\t40\t{conf}\t{text}"
        )
    return "\n".join(lines) + "\n"


# ---- running Tesseract ----


def test_tesseract_runs_by_absolute_path_with_the_image_on_stdin_and_no_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(args: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        calls.append({"args": args, **options})
        return subprocess.CompletedProcess(args, 0, stdout=tsv().encode(), stderr=b"")

    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/opt/bin/tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    monkeypatch.setenv("LLM_API_KEY", "sk-test-not-a-real-key-123456")

    run_tesseract(Image.new("RGB", (50, 50), "white"))

    call = calls[0]
    args = call["args"]
    assert isinstance(args, list)
    assert args[0] == "/opt/bin/tesseract"
    assert args[1:3] == ["stdin", "stdout"]
    assert args[-1] == "tsv"
    assert "-l" in args and args[args.index("-l") + 1] == "eng"
    assert call.get("shell", False) is False
    assert isinstance(call["input"], bytes) and call["input"].startswith(b"\x89PNG")
    assert call["timeout"] is not None
    env = call["env"]
    assert isinstance(env, dict)
    assert env["OMP_THREAD_LIMIT"] == "1"
    assert "LLM_API_KEY" not in env  # secrets never reach the subprocess


def test_tsv_words_become_words_with_boxes_and_confidence() -> None:
    words = parse_tsv(
        tsv(
            (1, 1, 1, 1, 10, 20, 100, 96.5, "OLD"),
            (1, 1, 1, 2, 120, 20, 90, 91.0, "TOM"),
            (1, 1, 1, 3, 220, 20, 50, -1, ""),
        )
    )

    assert [word.text for word in words] == ["OLD", "TOM"]
    assert words[0].box == Box(left=10, top=20, width=100, height=40)
    assert words[0].confidence == 96.5


@pytest.mark.parametrize("output", ["", "garbage\nwith no tabs\n", TSV_HEADER + "\n5\t1\tx\n"])
def test_unreadable_tsv_gives_no_words(output: str) -> None:
    assert parse_tsv(output) == []


def test_tesseract_missing_crashing_or_hanging_makes_ocr_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = Image.new("RGB", (50, 50), "white")

    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    with pytest.raises(OcrUnavailable, match="missing"):
        run_tesseract(image)

    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/opt/bin/tesseract")

    def crashes(args: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"Error")

    monkeypatch.setattr(ocr.subprocess, "run", crashes)
    with pytest.raises(OcrUnavailable, match="failed"):
        run_tesseract(image)

    def hangs(args: list[str], **options: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(args, 1.0)

    monkeypatch.setattr(ocr.subprocess, "run", hangs)
    with pytest.raises(OcrUnavailable, match="timeout"):
        run_tesseract(image)


# ---- sideways passes map back to the upright image ----


@pytest.mark.parametrize("angle", [90, 270])
def test_boxes_from_a_sideways_pass_map_back_to_the_upright_image(angle: int) -> None:
    upright = Image.new("L", (400, 300), 0)
    ImageDraw.Draw(upright).rectangle((50, 200, 129, 239), fill=255)  # 80 x 40 at (50, 200)
    turned = upright.rotate(angle, expand=True)
    left, top, right, bottom = turned.getbbox() or (0, 0, 0, 0)

    mapped = rotate_box_back(
        Box(left=left, top=top, width=right - left, height=bottom - top), angle, upright.size
    )

    assert mapped == Box(left=50, top=200, width=80, height=40)


def test_the_warning_header_is_recognised_despite_small_misreads() -> None:
    assert has_warning_header([words_page("GOVERNMENT WARNING: (1) According")])
    assert has_warning_header([words_page("GOVERNMENTWARNING. (I) According")])
    assert not has_warning_header([words_page("OLD TOM DISTILLERY")])


# ---- finding fields in OCR text ----


def test_offline_reading_finds_each_application_value_in_the_ocr_text() -> None:
    page = words_page(
        "OLD TOM DISTILLERY",
        "Kentucky Straight Bourbon Whiskey",
        "45% Alc./Vol. (90 Proof) 750 mL",
        "Distilled and bottled by Old Tom Distillery, Louisville, Kentucky",
        HEALTH_WARNING,
    )

    reading = reading_from_ocr([page], OLD_TOM_APPLICATION)

    assert reading.brand_name == "OLD TOM DISTILLERY"
    assert reading.class_type == "Kentucky Straight Bourbon Whiskey"
    assert reading.alcohol_content == "45% Alc./Vol. (90 Proof)"
    assert reading.net_contents == "750 mL"
    assert (
        reading.bottler is not None
        and "Old Tom Distillery, Louisville, Kentucky" in reading.bottler
    )
    assert reading.health_warning == HEALTH_WARNING
    assert reading.warning_header_bold is None  # OCR can't judge bold
    assert reading.warning_body_bold is None


def test_offline_reading_leaves_a_value_that_is_not_on_the_label_missing() -> None:
    page = words_page("BLUE RIDGE SPIRITS", "Vodka 40% Alc./Vol.")

    reading = reading_from_ocr([page], OLD_TOM_APPLICATION)

    assert reading.brand_name is None
    assert reading.health_warning is None


def test_locating_text_gives_the_box_around_its_words() -> None:
    page = words_page("OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey", image=1)

    location = locate("Kentucky Straight Bourbon Whiskey", [page])

    assert location == Location(image=1, box=Box(left=0, top=100, width=780, height=40))


def test_text_that_cannot_be_found_gets_no_box_rather_than_a_wrong_one() -> None:
    page = words_page("OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey")

    assert locate("Product of Mexico", [page]) is None
    assert locate("", [page]) is None


def test_results_and_the_differing_warning_word_get_locations() -> None:
    typo = HEALTH_WARNING.replace("pregnancy", "pregnancey")
    page = words_page("OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey", typo)
    report = verify(
        OLD_TOM_APPLICATION, OLD_TOM_READING.model_copy(update={"health_warning": typo})
    )

    located = attach_locations(report, [page])

    brand = next(r for r in located.results if r.field is LabelField.BRAND)
    warning = next(r for r in located.results if r.field is LabelField.HEALTH_WARNING)
    changed = next(s for s in warning.diff if s.op is DiffOp.CHANGED)
    assert brand.location is not None and brand.location.box.top == 0
    assert warning.location is not None and warning.location.box.top == 200
    assert changed.location is not None
    assert changed.location.box.top == 200
    typo_index = typo.split().index("pregnancey")
    assert changed.location.box.left == 200 * typo_index


# ---- the real Tesseract ----


@pytest.mark.ocr
def test_ocr_reads_old_tom_well_enough_to_confirm_every_field() -> None:
    page = read_page(label("old-tom"), 0)

    results = verify(OLD_TOM_APPLICATION, OLD_TOM_READING).results
    confirmed = cross_check(results, page.text)

    assert all(result.status is Status.PASS for result in confirmed)


@pytest.mark.ocr
def test_ocr_alone_reads_old_tom_but_cannot_match_it() -> None:
    page = read_page(label("old-tom"), 0)

    report = verify(
        OLD_TOM_APPLICATION, reading_from_ocr([page], OLD_TOM_APPLICATION), read_by=Reader.OCR
    )

    assert report.verdict is Verdict.NEEDS_REVIEW
    statuses = {result.field: result.status for result in report.results}
    assert statuses[LabelField.HEALTH_WARNING] is Status.REVIEW  # bold can't be judged
    assert all(
        status is Status.PASS
        for field, status in statuses.items()
        if field is not LabelField.HEALTH_WARNING
    )


@pytest.mark.ocr
def test_ocr_locates_the_brand_near_the_top_of_old_tom() -> None:
    image = label("old-tom")
    location = locate("OLD TOM DISTILLERY", [read_page(image, 0)])

    assert location is not None
    assert location.box.top < image.image.height * 0.3


@pytest.mark.ocr
def test_ocr_locates_the_typo_in_the_warning_typo_label() -> None:
    truth = next(t for _, t in load_fixtures(SYNTHETIC) if t.id == "warning-typo")
    page = read_page(label("warning-typo"), 0)
    report = verify(truth.application, truth.printed)

    located = attach_locations(report, [page])

    warning = next(r for r in located.results if r.field is LabelField.HEALTH_WARNING)
    differing = [s for s in warning.diff if s.op is not DiffOp.SAME and s.found]
    assert warning.location is not None
    assert differing and all(segment.location is not None for segment in differing)


@pytest.mark.ocr
def test_a_sideways_warning_is_read_by_the_rotated_passes() -> None:
    image = label("warning-rotated")

    upright = read_page(image, 0)
    sideways = read_page(image, 0, angles=(0, 90, 270))

    assert not has_warning_header([upright])
    assert has_warning_header([sideways])
    warning = locate(HEALTH_WARNING, [sideways])
    assert warning is not None
    width, height = image.image.size
    box = warning.box
    assert box.left + box.width <= width and box.top + box.height <= height
    assert box.height > box.width  # a sideways block of text is tall and narrow


@pytest.mark.ocr
def test_a_blank_image_reads_as_no_text() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    blank = prepare_upload(buffer.getvalue())[0]

    assert read_page(blank, 0).text == ""


# ---- fixtures with sideways text ----


def test_fixtures_with_sideways_text_are_tagged_rotated() -> None:
    tagged = {
        truth.id
        for folder in ("synthetic", "cola")
        for _, truth in load_fixtures(FIXTURES_ROOT / folder)
        if "rotated" in truth.tags
    }

    assert tagged == {
        "warning-rotated",
        "cola-26239001000680",  # Switchback
        "cola-26244001000018",  # Tox
        "cola-26246001000514",  # Forever Alone
        "cola-26245001000184",  # FLOS
    }

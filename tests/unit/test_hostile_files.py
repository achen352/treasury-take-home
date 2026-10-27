"""Hostile upload fixtures: each file really is the attack it claims to be (all harmless)."""

import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import pytest
from PIL import Image, UnidentifiedImageError

from scripts import hostile_files
from scripts.fixtures import FIXTURES_ROOT

COMMITTED = FIXTURES_ROOT / "hostile"
EXPECTED = {
    "decompression-bomb.png": "reject",
    "polyglot-zip.png": "sanitize",
    "polyglot-html.png": "sanitize",
    "html-named.png": "reject",
    "svg-script.png": "reject",
    "pdf-named.jpg": "reject",
    "empty.png": "reject",
    "truncated.png": "reject",
    "animated.png": "sanitize",
    "png-named.jpg": "accept",
    "exif-instructions.jpg": "sanitize",
    "exif-rotated.jpg": "sanitize",
    "pdf-hidden-text.pdf": "sanitize",
    "pdf-javascript.pdf": "sanitize",
    "pdf-encrypted.pdf": "reject",
    "pdf-too-many-pages.pdf": "reject",
    "pdf-odd-page.pdf": "reject",
}


@pytest.fixture(scope="module", params=["committed", "fresh"])
def folder(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run every check on the committed files and on a fresh generation."""
    if request.param == "committed":
        return COMMITTED
    fresh = tmp_path_factory.mktemp("hostile")
    hostile_files.generate(fresh)
    return fresh


def test_manifest_lists_every_file_and_what_must_happen_to_it(folder: Path) -> None:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    assert {entry["file"]: entry["expect"] for entry in manifest} == EXPECTED
    assert all(entry["why"] for entry in manifest)
    assert all((folder / name).is_file() for name in EXPECTED)


def test_decompression_bomb_is_tiny_but_declares_billions_of_pixels(folder: Path) -> None:
    data = (folder / "decompression-bomb.png").read_bytes()
    width, height = struct.unpack(">II", data[16:24])  # IHDR width and height

    assert len(data) < 100_000
    assert width * height >= 2_500_000_000
    with pytest.raises(Image.DecompressionBombError):
        Image.open(folder / "decompression-bomb.png")


def test_zip_polyglot_is_both_a_valid_png_and_a_readable_zip(folder: Path) -> None:
    path = folder / "polyglot-zip.png"
    with Image.open(path) as image:
        image.verify()
    with zipfile.ZipFile(path) as archive:
        assert archive.read("payload.txt").startswith(b"This text was hidden")


def test_html_polyglot_is_a_valid_png_with_a_script_after_the_image(folder: Path) -> None:
    data = (folder / "polyglot-html.png").read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        image.verify()

    assert b"<script>" in data[data.index(b"IEND") :]


@pytest.mark.parametrize(
    ("name", "starts_with"),
    [
        ("html-named.png", b"<!DOCTYPE html>"),
        ("svg-script.png", b"<svg"),
        ("pdf-named.jpg", b"%PDF-"),
    ],
)
def test_files_posing_as_images_are_not_images(folder: Path, name: str, starts_with: bytes) -> None:
    data = (folder / name).read_bytes()

    assert data.startswith(starts_with)
    with pytest.raises(UnidentifiedImageError):
        Image.open(folder / name)


def test_svg_carries_a_script(folder: Path) -> None:
    assert b"<script" in (folder / "svg-script.png").read_bytes()


def test_empty_file_is_empty(folder: Path) -> None:
    assert (folder / "empty.png").stat().st_size == 0


def test_truncated_png_opens_but_cannot_be_decoded(folder: Path) -> None:
    with Image.open(folder / "truncated.png") as image, pytest.raises(OSError):
        image.load()


def test_animated_png_has_a_second_frame_that_differs(folder: Path) -> None:
    with Image.open(folder / "animated.png") as image:
        assert getattr(image, "n_frames", 1) == 2
        first = image.convert("RGB")
        image.seek(1)
        second = image.convert("RGB")

    assert first.tobytes() != second.tobytes()


def test_png_with_a_jpg_name_is_really_a_png(folder: Path) -> None:
    with Image.open(folder / "png-named.jpg") as image:
        assert image.format == "PNG"


def test_exif_carries_injection_text(folder: Path) -> None:
    with Image.open(folder / "exif-instructions.jpg") as image:
        description = image.getexif()[0x010E]  # ImageDescription

    assert "ignore previous instructions" in description.lower()


def test_exif_rotation_flag_is_set(folder: Path) -> None:
    with Image.open(folder / "exif-rotated.jpg") as image:
        assert image.getexif()[0x0112] == 6  # Orientation: rotate 90 degrees to display


# ---- PDFs: each one is checked with PDFium itself, independently of the upload code ----


def _open_pdf(folder: Path, name: str) -> pdfium.PdfDocument:
    return pdfium.PdfDocument((folder / name).read_bytes())


def test_pdf_with_no_pages_is_still_a_pdf(folder: Path) -> None:
    with pytest.raises(pdfium.PdfiumError):
        _open_pdf(folder, "pdf-named.jpg")


def test_hidden_text_pdf_draws_invisible_and_white_text_over_a_visible_label(
    folder: Path,
) -> None:
    data = (folder / "pdf-hidden-text.pdf").read_bytes()

    assert b"3 Tr" in data  # text render mode 3: invisible, as in a scanned PDF's text layer
    assert b"1 1 1 rg" in data  # white fill, drawn on a white page
    assert b"(OLD TOM DISTILLERY)" in data
    assert len(_open_pdf(folder, "pdf-hidden-text.pdf")) == 1


def test_javascript_pdf_runs_a_script_when_opened(folder: Path) -> None:
    data = (folder / "pdf-javascript.pdf").read_bytes()

    assert b"/OpenAction" in data
    assert b"/S /JavaScript" in data
    assert len(_open_pdf(folder, "pdf-javascript.pdf")) == 1


def test_encrypted_pdf_needs_a_password(folder: Path) -> None:
    assert b"/Encrypt" in (folder / "pdf-encrypted.pdf").read_bytes()
    with pytest.raises(pdfium.PdfiumError) as failure:
        _open_pdf(folder, "pdf-encrypted.pdf")
    assert failure.value.err_code == pdfium_c.FPDF_ERR_PASSWORD


def test_too_many_pages_pdf_has_one_page_more_than_a_label_allows(folder: Path) -> None:
    assert len(_open_pdf(folder, "pdf-too-many-pages.pdf")) == 7


def test_odd_page_pdf_has_a_page_far_too_thin_to_be_a_label(folder: Path) -> None:
    width, height = _open_pdf(folder, "pdf-odd-page.pdf")[0].get_size()

    assert min(width, height) < 36  # under half an inch
    assert max(width, height) > 3_000


def _png_content(data: bytes) -> tuple[object, ...]:
    """What a PNG holds, independent of how its zlib compressed it: the chunk layout, every
    chunk but the image data, each frame's decompressed pixels, and anything after IEND.

    Pillow's wheels bundle different zlib builds on Linux, macOS and Windows, so the compressed
    bytes of an identical image differ by OS.
    """
    layout: list[bytes] = []
    chunks: list[bytes] = []
    frames: list[bytearray] = []
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind in (b"IDAT", b"fdAT"):
            if not layout or layout[-1] != kind:
                layout.append(kind)
                frames.append(bytearray())
            frames[-1] += body if kind == b"IDAT" else body[4:]
            if kind == b"fdAT":
                chunks.append(body[:4])  # the frame sequence number
        else:
            layout.append(kind)
            chunks.append(kind + body)
        if kind == b"IEND":
            break
    pixels = [zlib.decompress(bytes(frame)) for frame in frames]
    return tuple(layout), tuple(chunks), tuple(pixels), data[offset:]


def test_a_fresh_generation_matches_the_committed_files(tmp_path: Path) -> None:
    # The files must come out the same on every OS, so regenerating never changes them.
    hostile_files.generate(tmp_path)

    for name in [*EXPECTED, "manifest.json"]:
        fresh, committed = (tmp_path / name).read_bytes(), (COMMITTED / name).read_bytes()
        if name == "truncated.png":
            # Half of a PNG's compressed bytes: checked as half of png-named.jpg instead.
            full = (tmp_path / "png-named.jpg").read_bytes()
            assert fresh == full[: len(full) // 2]
        elif committed.startswith(b"\x89PNG") and not name.startswith("decompression"):
            assert _png_content(fresh) == _png_content(committed), name
        else:
            assert fresh == committed, name

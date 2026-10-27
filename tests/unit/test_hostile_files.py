"""Hostile upload fixtures: each file really is the attack it claims to be (all harmless)."""

import io
import json
import struct
import zipfile
from pathlib import Path

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

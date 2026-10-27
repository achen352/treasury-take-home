"""Upload checks: only real label images get through, rebuilt from their pixels alone."""

import io
import json
import struct
import time
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat

from app.readers import uploads
from app.readers.uploads import (
    MAX_FILE_BYTES,
    MAX_IMAGES,
    PDF_LONG_SIDE,
    REJECTION_MESSAGES,
    LabelImage,
    UploadRejected,
    png_bytes,
    prepare_upload,
    prepare_uploads,
)
from scripts import hostile_files
from scripts.fixtures import FIXTURES_ROOT
from tests.disk_guard import no_disk_writes

HOSTILE = FIXTURES_ROOT / "hostile"
SYNTHETIC = FIXTURES_ROOT / "synthetic"
MANIFEST = json.loads((HOSTILE / "manifest.json").read_text(encoding="utf-8"))


def _encode(image: Image.Image, kind: str, **options: object) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, kind, **options)
    return buffer.getvalue()


def _only(data: bytes) -> Image.Image:
    images = prepare_upload(data)
    assert len(images) == 1
    return images[0].image


def _mean_difference(a: Image.Image, b: Image.Image) -> float:
    """Average per-channel difference (0-255) after scaling `b` to the size of `a`."""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB").resize(a.size))
    return sum(ImageStat.Stat(diff).mean) / 3


def _white_palette_image() -> Image.Image:
    image = Image.new("P", (30, 30), 0)
    image.putpalette([255, 255, 255] * 256)
    return image


def _png_chunk_types(data: bytes) -> list[bytes]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    kinds, offset = [], 8
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        kinds.append(data[offset + 4 : offset + 8])
        offset += 12 + length
    return kinds


# ---- the hostile files ----


@pytest.mark.parametrize("entry", MANIFEST, ids=[entry["file"] for entry in MANIFEST])
def test_every_hostile_file_gets_the_handling_its_manifest_lists(entry: dict[str, str]) -> None:
    data = (HOSTILE / entry["file"]).read_bytes()

    if entry["expect"] == "reject":
        with pytest.raises(UploadRejected):
            prepare_upload(data)
    else:
        images = prepare_upload(data)
        assert images
        assert all(isinstance(image, LabelImage) for image in images)


@pytest.mark.parametrize(
    "name", [entry["file"] for entry in MANIFEST if entry["expect"] == "reject"]
)
def test_rejections_use_fixed_plain_messages_that_repeat_nothing_from_the_file(name: str) -> None:
    with pytest.raises(UploadRejected) as rejected:
        prepare_upload((HOSTILE / name).read_bytes())

    assert str(rejected.value) in REJECTION_MESSAGES


def test_decompression_bomb_is_rejected_from_its_header_without_decoding() -> None:
    data = (HOSTILE / "decompression-bomb.png").read_bytes()

    started = time.perf_counter()
    with pytest.raises(UploadRejected):
        prepare_upload(data)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("name", ["polyglot-zip.png", "polyglot-html.png", "exif-instructions.jpg"])
def test_rebuilt_image_carries_nothing_but_pixels(name: str) -> None:
    label = prepare_upload((HOSTILE / name).read_bytes())[0]
    encoded = png_bytes(label)

    chunks = _png_chunk_types(encoded)

    assert label.image.info == {}
    assert chunks[0] == b"IHDR"
    assert chunks[-1] == b"IEND"
    assert set(chunks) == {b"IHDR", b"IDAT", b"IEND"}  # no text, metadata or trailing data
    for payload in (b"PK\x03\x04", b"payload", b"<script", b"<html", b"Exif", b"Ignore"):
        assert payload not in encoded


def test_exif_rotation_is_applied() -> None:
    upright = _only((HOSTILE / "exif-rotated.jpg").read_bytes())
    expected = hostile_files._small_label()

    assert upright.size == expected.size
    assert _mean_difference(upright, expected) < _mean_difference(upright, expected.rotate(180))


def test_animated_image_yields_its_first_frame_only() -> None:
    frame = _only((HOSTILE / "animated.png").read_bytes())

    assert frame.tobytes() == hostile_files._small_label().tobytes()


def test_a_png_named_jpg_is_accepted_because_its_content_is_png() -> None:
    assert _only((HOSTILE / "png-named.jpg").read_bytes()).size == (900, 300)


# ---- what is accepted, and how it comes out ----


def test_png_jpeg_and_webp_are_accepted() -> None:
    label = hostile_files._small_label()
    for kind in ("PNG", "JPEG", "WEBP"):
        assert _only(_encode(label, kind)).size == label.size


@pytest.mark.parametrize(
    ("kind", "data"),
    [
        ("TIFF", _encode(Image.new("RGB", (40, 40), "white"), "TIFF")),
        ("GIF", _encode(Image.new("RGB", (40, 40), "white"), "GIF")),
        ("BMP", _encode(Image.new("RGB", (40, 40), "white"), "BMP")),
        ("EPS", b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"),
        ("text", b"OLD TOM DISTILLERY"),
    ],
)
def test_other_types_are_rejected_by_their_first_bytes(kind: str, data: bytes) -> None:
    with pytest.raises(UploadRejected, match="PNG, JPEG, WebP or PDF"):
        prepare_upload(data)


def test_heic_gets_a_message_explaining_how_to_send_jpeg() -> None:
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + bytes(64)

    with pytest.raises(UploadRejected) as rejected:
        prepare_upload(heic)
    assert "HEIC" in str(rejected.value)
    assert "JPEG" in str(rejected.value)


def test_pillow_may_only_open_the_format_the_first_bytes_claim() -> None:
    jpeg_body = _encode(hostile_files._small_label(), "JPEG")
    disguised = b"\x89PNG\r\n\x1a\n" + jpeg_body

    with pytest.raises(UploadRejected):
        prepare_upload(disguised)


def test_files_over_the_size_limit_are_rejected_before_parsing() -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + bytes(MAX_FILE_BYTES)

    with pytest.raises(UploadRejected, match="10 MB"):
        prepare_upload(oversized)


def test_images_over_the_pixel_limit_are_rejected() -> None:
    over_limit = hostile_files._decompression_bomb(side=6_500)  # 42 megapixels

    with pytest.raises(UploadRejected, match="megapixels"):
        prepare_upload(over_limit)


def test_empty_and_truncated_files_are_rejected() -> None:
    jpeg = _encode(hostile_files._small_label(), "JPEG")
    for data in (b"", jpeg[: len(jpeg) // 2], (HOSTILE / "truncated.png").read_bytes()):
        with pytest.raises(UploadRejected):
            prepare_upload(data)


def test_gps_location_and_other_metadata_are_removed() -> None:
    exif = Image.Exif()
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (38.0, 53.0, 51.0)  # latitude
    gps[3], gps[4] = "W", (77.0, 2.0, 11.0)  # longitude
    exif[0x010F] = "Phone maker"
    photo = _encode(hostile_files._small_label(), "JPEG", exif=exif.tobytes())

    label = prepare_upload(photo)[0]
    encoded = png_bytes(label)

    assert label.image.info == {}
    assert not Image.open(io.BytesIO(encoded)).getexif()
    assert b"Phone maker" not in encoded


def test_transparency_is_flattened_onto_white_so_hidden_text_stays_hidden() -> None:
    original = Image.open(SYNTHETIC / "hidden-transparent-text" / "label.png")
    flattened = _only((SYNTHETIC / "hidden-transparent-text" / "label.png").read_bytes())
    white = Image.new("RGB", original.size, "white")
    fully_transparent = original.getchannel("A").point(lambda a: 255 if a == 0 else 0)

    # Wherever the original is fully transparent, the result must be plain white.
    revealed = Image.composite(flattened, white, fully_transparent)
    assert ImageChops.difference(revealed, white).getbbox() is None


def test_half_transparent_pixels_are_blended_with_white() -> None:
    half_black = Image.new("RGBA", (20, 20), (0, 0, 0, 128))

    pixel = _only(_encode(half_black, "PNG")).getpixel((5, 5))
    assert pixel == pytest.approx((127, 127, 127), abs=1)


@pytest.mark.parametrize(
    "image",
    [
        Image.new("CMYK", (30, 30), (0, 0, 0, 0)),
        Image.new("L", (30, 30), 255),
        Image.new("1", (30, 30), 1),
        Image.new("LA", (30, 30), (255, 255)),
        _white_palette_image(),
    ],
    ids=["cmyk", "grayscale", "one-bit", "grayscale-alpha", "palette"],
)
def test_every_colour_mode_comes_out_as_rgb(image: Image.Image) -> None:
    kind = "JPEG" if image.mode == "CMYK" else "PNG"
    result = _only(_encode(image, kind))

    assert result.mode == "RGB"
    assert result.getpixel((10, 10)) == pytest.approx((255, 255, 255), abs=2)


def test_a_palette_image_with_a_transparent_colour_is_flattened() -> None:
    palette = Image.new("P", (30, 30), 0)
    palette.putpalette([0, 0, 0] * 256)

    result = _only(_encode(palette, "PNG", transparency=0))
    assert result.getpixel((10, 10)) == (255, 255, 255)


def test_sixteen_bit_greys_keep_their_brightness() -> None:
    mid_grey = Image.new("I;16", (30, 30), 32768)

    pixel = _only(_encode(mid_grey, "PNG")).getpixel((10, 10))
    assert pixel == pytest.approx((128, 128, 128), abs=2)


def test_the_ai_copy_is_scaled_down_but_never_enlarged() -> None:
    big = prepare_upload((SYNTHETIC / "old-tom" / "label.png").read_bytes())[0]  # 1600 x 2000
    small = prepare_upload(_encode(hostile_files._small_label(), "PNG"))[0]  # 900 x 300

    def size(data: bytes) -> tuple[int, int]:
        return Image.open(io.BytesIO(data)).size

    assert size(png_bytes(big, max_side=1100)) == (880, 1100)
    assert size(png_bytes(small, max_side=1100)) == (900, 300)
    assert size(png_bytes(big)) == (1600, 2000)


# ---- PDF ----


def _pdf_of(image: Image.Image) -> bytes:
    return _encode(image.convert("RGB"), "PDF", resolution=200.0)


def test_pdf_pages_are_rendered_and_read_like_the_same_label_as_an_image() -> None:
    label = Image.open(SYNTHETIC / "old-tom" / "label.png")

    page = _only(_pdf_of(label))

    assert max(page.size) == pytest.approx(PDF_LONG_SIDE, abs=1)
    assert _mean_difference(page, label) < 8


def test_each_pdf_page_becomes_one_image() -> None:
    pages = [hostile_files._small_label(text) for text in ("FRONT", "BACK")]
    buffer = io.BytesIO()
    pages[0].save(buffer, "PDF", save_all=True, append_images=pages[1:])

    assert len(prepare_upload(buffer.getvalue())) == 2


def test_only_what_a_person_can_see_in_a_pdf_is_read() -> None:
    hidden = _only((HOSTILE / "pdf-hidden-text.pdf").read_bytes())
    visible_only = _only(hostile_files.pdf_document([hostile_files.PDF_VISIBLE_TEXT]))

    assert hidden.tobytes() == visible_only.tobytes()
    assert hidden.convert("L").getextrema()[0] < 100  # the visible text was drawn


def test_pdf_scripts_cannot_run() -> None:
    from pypdfium2.version import PDFIUM_INFO

    assert "V8" not in PDFIUM_INFO.flags  # no JavaScript engine in this PDFium build
    assert "XFA" not in PDFIUM_INFO.flags
    assert _only((HOSTILE / "pdf-javascript.pdf").read_bytes()).size


def test_a_pdfium_build_with_javascript_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uploads, "PDFIUM_FLAGS", ("V8", "XFA"))

    with pytest.raises(RuntimeError, match="JavaScript"):
        uploads.check_pdfium_build()


@pytest.mark.parametrize(
    "data",
    [
        (HOSTILE / "pdf-encrypted.pdf").read_bytes(),
        (HOSTILE / "pdf-named.jpg").read_bytes(),  # no pages
        (HOSTILE / "pdf-too-many-pages.pdf").read_bytes(),
        (HOSTILE / "pdf-odd-page.pdf").read_bytes(),
        b"%PDF-1.7\nThis is not really a PDF.\n",
    ],
    ids=["encrypted", "no-pages", "too-many-pages", "odd-page-size", "malformed"],
)
def test_unusable_pdfs_are_rejected(data: bytes) -> None:
    with pytest.raises(UploadRejected):
        prepare_upload(data)


# ---- several files for one label ----


def test_a_label_takes_at_most_six_images_and_each_pdf_page_counts() -> None:
    png = _encode(hostile_files._small_label(), "PNG")
    pages = [hostile_files._small_label(str(n)) for n in range(4)]
    buffer = io.BytesIO()
    pages[0].save(buffer, "PDF", save_all=True, append_images=pages[1:])
    four_page_pdf = buffer.getvalue()

    assert len(prepare_uploads([png] * MAX_IMAGES)) == MAX_IMAGES
    with pytest.raises(UploadRejected, match="6 images"):
        prepare_uploads([png] * (MAX_IMAGES + 1))
    with pytest.raises(UploadRejected, match="6 images"):
        prepare_uploads([four_page_pdf, four_page_pdf])
    with pytest.raises(UploadRejected):
        prepare_uploads([])


# ---- nothing touches the disk ----


def test_the_disk_guard_notices_a_write(tmp_path: Path) -> None:
    with no_disk_writes() as writes:
        (tmp_path / "file.txt").write_text("x", encoding="utf-8")

    assert writes


def test_checking_uploads_writes_nothing_to_disk() -> None:
    label = hostile_files._small_label()
    files = [
        _encode(label, "PNG"),
        _encode(label, "JPEG"),
        _encode(label, "WEBP"),
        _pdf_of(label),
        (HOSTILE / "exif-rotated.jpg").read_bytes(),
    ]

    def check_all() -> None:
        for image in prepare_uploads(files):
            png_bytes(image, max_side=1100)

    check_all()  # first run: imports may write bytecode caches
    with no_disk_writes() as writes:
        check_all()

    assert writes == []

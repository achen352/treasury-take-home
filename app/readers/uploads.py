"""Upload checks: each file is judged by its content, capped, and rebuilt from its pixels.

Nothing from an uploaded file survives except its pixels. Metadata (including GPS location),
extra animation frames and anything appended to the file are dropped, because the image is
decoded and drawn again from scratch. PDF pages are rendered, so only what a person would see
is read, never a PDF's hidden text layer. Everything happens in memory.
"""

import io
import threading
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageOps
from pypdfium2.version import PDFIUM_INFO

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_IMAGES = 6
# Larger images are scaled down after decoding, so six fit in a small server's memory; 4,000
# pixels is plenty for reading a label.
WORKING_SIDE = 4000
# PDF pages are rendered to this many pixels on the long side, so a small label gets a higher
# resolution than a large sheet.
PDF_LONG_SIDE = 2500
# A label page is between half an inch and 200 inches (the PDF format's own limit) on a side.
PDF_MIN_SIDE_POINTS = 36
PDF_MAX_SIDE_POINTS = 14_400
PDFIUM_FLAGS: tuple[str, ...] = tuple(PDFIUM_INFO.flags)

# Every rejection uses one of these fixed messages, so nothing from the file is ever echoed.
EMPTY = "The file is empty."
TOO_LARGE = "The file is larger than 10 MB."
UNSUPPORTED = "This file isn't a PNG, JPEG, WebP or PDF."
HEIC = (
    "This looks like an iPhone photo in HEIC format. Upload it from the iPhone's photo library, "
    "which sends a JPEG, or save it as JPEG first."
)
TOO_MANY_PIXELS = "The image is larger than 40 megapixels."
DAMAGED = "The file is damaged or incomplete."
PDF_LOCKED = "The PDF is password-protected."
PDF_NO_PAGES = "The PDF has no pages."
ODD_PAGE = "A page of the PDF is too small or too large to be a label."
TOO_MANY_IMAGES = f"A label can have at most {MAX_IMAGES} images, counting each PDF page."
NO_IMAGES = "Add at least one label image."
REJECTION_MESSAGES = frozenset(
    {
        EMPTY,
        TOO_LARGE,
        UNSUPPORTED,
        HEIC,
        TOO_MANY_PIXELS,
        DAMAGED,
        PDF_LOCKED,
        PDF_NO_PAGES,
        ODD_PAGE,
        TOO_MANY_IMAGES,
        NO_IMAGES,
    }
)

_HEIF_BRANDS = frozenset({b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1"})
_SIXTEEN_BIT = frozenset({"I", "I;16", "I;16B", "I;16L", "I;16N"})
_PDFIUM_LOCK = threading.Lock()  # PDFium isn't thread-safe


class UploadRejected(ValueError):
    """A file that can't be checked. The message is fixed text, safe to show to the user."""


@dataclass(frozen=True)
class LabelImage:
    """One upright RGB label image, rebuilt from pixels. Made only by `prepare_upload`."""

    image: Image.Image


def check_pdfium_build() -> None:
    """Refuse a PDFium build that could run JavaScript or XFA forms inside a PDF."""
    if {"V8", "XFA"} & set(PDFIUM_FLAGS):
        raise RuntimeError(
            "This PDFium build can run JavaScript in PDFs; install the standard pypdfium2 build."
        )


check_pdfium_build()


def prepare_uploads(files: Sequence[bytes]) -> list[LabelImage]:
    """Check every file for one label; together they may make at most MAX_IMAGES images."""
    if not files:
        raise UploadRejected(NO_IMAGES)
    if len(files) > MAX_IMAGES:
        raise UploadRejected(TOO_MANY_IMAGES)
    images: list[LabelImage] = []
    for data in files:
        images.extend(prepare_upload(data))
        if len(images) > MAX_IMAGES:
            raise UploadRejected(TOO_MANY_IMAGES)
    return images


def prepare_upload(data: bytes) -> list[LabelImage]:
    """Check one file and rebuild it as label images: one for an image, one per PDF page."""
    if not data:
        raise UploadRejected(EMPTY)
    if len(data) > MAX_FILE_BYTES:
        raise UploadRejected(TOO_LARGE)
    kind = _sniff(data)
    if kind is None:
        raise UploadRejected(HEIC if _is_heif(data) else UNSUPPORTED)
    if kind == "PDF":
        return [LabelImage(page) for page in _render_pdf(bytes(data))]
    return [LabelImage(_decode(data, kind))]


def png_bytes(label: LabelImage, max_side: int | None = None) -> bytes:
    """A fresh PNG of the label, scaled down to `max_side` on the long side (never enlarged)."""
    image = label.image
    if max_side is not None and max(image.size) > max_side:
        image = image.copy()
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _sniff(data: bytes) -> str | None:
    """The file type from its first bytes. The file name is never consulted."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data.startswith(b"%PDF-"):
        return "PDF"
    return None


def _is_heif(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS


def _decode(data: bytes, kind: str) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # Only the format the first bytes claim may open the file, so Pillow never tries
            # its other decoders on it (EPS, for one, would run Ghostscript).
            with Image.open(io.BytesIO(data), formats=[kind]) as image:
                if image.width * image.height > MAX_PIXELS:
                    raise UploadRejected(TOO_MANY_PIXELS)
                image.seek(0)  # an animated image is read from its first frame only
                image.load()
                return _rebuilt(ImageOps.exif_transpose(image))
    except UploadRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UploadRejected(TOO_MANY_PIXELS) from None
    except Exception:  # any decoder failure on untrusted data means the file is unusable
        raise UploadRejected(DAMAGED) from None


def _rebuilt(image: Image.Image) -> Image.Image:
    """Fresh RGB pixels with transparency flattened onto white, and no metadata at all."""
    if image.mode in _SIXTEEN_BIT:
        # Scale 16-bit greys down to 8 bits; a plain conversion would clip them to white.
        image = image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    if image.has_transparency_data:
        # Fully transparent pixels become white, so text hidden in them stays hidden.
        white = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(white, image.convert("RGBA"))
    rgb = image.convert("RGB")
    if max(rgb.size) > WORKING_SIDE:
        rgb.thumbnail((WORKING_SIDE, WORKING_SIDE), Image.Resampling.LANCZOS)
    return Image.frombytes("RGB", rgb.size, rgb.tobytes())


def _render_pdf(data: bytes) -> list[Image.Image]:
    with _PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(data)  # bytes, so it's read from memory, never a path
        except pdfium.PdfiumError as error:
            raise UploadRejected(_pdf_failure(error)) from None
        try:
            if len(pdf) > MAX_IMAGES:
                raise UploadRejected(TOO_MANY_IMAGES)
            return [_render_page(pdf[index]) for index in range(len(pdf))]
        except pdfium.PdfiumError:
            raise UploadRejected(DAMAGED) from None
        finally:
            pdf.close()


def _render_page(page: pdfium.PdfPage) -> Image.Image:
    try:
        width, height = page.get_size()
        if min(width, height) < PDF_MIN_SIDE_POINTS or max(width, height) > PDF_MAX_SIDE_POINTS:
            raise UploadRejected(ODD_PAGE)
        bitmap = page.render(
            scale=PDF_LONG_SIDE / max(width, height),
            fill_color=(255, 255, 255, 255),
            may_draw_forms=False,
        )
        try:
            return _rebuilt(bitmap.to_pil())
        finally:
            bitmap.close()
    finally:
        page.close()


def _pdf_failure(error: pdfium.PdfiumError) -> str:
    code = getattr(error, "err_code", None)
    if code == pdfium_c.FPDF_ERR_PASSWORD:
        return PDF_LOCKED
    if code == pdfium_c.FPDF_ERR_SUCCESS:  # it opened, but has no pages
        return PDF_NO_PAGES
    return DAMAGED

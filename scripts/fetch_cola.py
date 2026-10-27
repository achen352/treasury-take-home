"""Downloads approved labels from TTB's public COLA registry, politely.

    python -m scripts.fetch_cola 26257001000366 [more TTB IDs...]

For each TTB ID this saves registry.json (the registry's own fields) and every label image to
tests/fixtures/cola/<TTB ID>/. It makes one request at a time with a pause after each, and only
ever contacts ttbonline.gov over HTTPS. Registry file names are never used as local paths.
"""

import html
import io
import re
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor

from PIL import Image
from pydantic import BaseModel

from scripts.fixtures import FIXTURES_ROOT

BASE = "https://ttbonline.gov/colasonline"
DETAIL_URL = BASE + "/viewColaDetails.do?action=publicDisplaySearchBasic&ttbid={ttb_id}"
FORM_URL = BASE + "/viewColaDetails.do?action=publicFormDisplay&ttbid={ttb_id}"
IMAGE_URL = BASE + "/publicViewAttachment.do?filename={filename}&filetype=l"
OUTPUT = FIXTURES_ROOT / "cola"
PAUSE_SECONDS = 2.0
MAX_BYTES = 20 * 1024 * 1024
USER_AGENT = "cola-label-verifier test-data fetcher (one request every 2 seconds)"
EXTENSIONS = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "TIFF": ".tif", "BMP": ".bmp"}


class LabelImage(BaseModel):
    filename: str  # as the registry names it; only ever sent URL-encoded
    image_type: str
    dimensions: str
    saved_as: str = ""


class ColaForm(BaseModel):
    product_type: str
    source: str
    applicant: str
    images: list[LabelImage]


class ColaRecord(BaseModel):
    ttb_id: str
    url: str
    status: str
    brand_name: str
    fanciful_name: str
    class_type_code: str
    origin_code: str
    approval_date: str
    qualifications: str
    total_bottle_capacity: str
    product_type: str
    source: str
    applicant: str
    images: list[LabelImage]


def _text(fragment: str) -> str:
    """Visible text of an HTML fragment, with whitespace collapsed."""
    without_tags = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(html.unescape(without_tags).replace("\xa0", " ").split())


def parse_detail(page: str) -> dict[str, str]:
    """The labelled fields of a COLA detail page, such as "Brand Name" -> "BELLE ISLE"."""
    pairs = re.findall(r"<strong>\s*([^<:]+?):?\s*</strong>(.*?)</td>", page, re.DOTALL)
    return {label.strip(): _text(value) for label, value in pairs}


def parse_form(page: str) -> ColaForm:
    """Product type, source, applicant and label images from the printable COLA form."""
    checked = [
        html.unescape(alt)
        for tag in re.findall(r"<input[^>]*type=\"checkbox\"[^>]*>", page)
        if re.search(r"\bchecked\b", tag)
        for alt in re.findall(r'alt="([^"]*)"', tag)
    ]

    def choice(question: str) -> str:
        prefix = f"{question}: "
        return next((alt.removeprefix(prefix) for alt in checked if alt.startswith(prefix)), "")

    applicant = ""
    block = re.search(
        r"8\. NAME AND ADDRESS OF APPLICANT.*?<div class=\"data\">(.*?)</div>", page, re.DOTALL
    )
    if block:
        lines = (_text(line) for line in re.split(r"<br\s*/?>", block.group(1)))
        applicant = "\n".join(line for line in lines if line)

    images = []
    for match in re.finditer(
        r'<img src="/colasonline/publicViewAttachment\.do\?filename=([^"&]*)&(?:amp;)?filetype=l"'
        r'[^>]*alt="Label Image: ([^"]*)"',
        page,
    ):
        dimensions = re.findall(r"Actual Dimensions:\s*(.*?)<br", page[: match.start()])
        images.append(
            LabelImage(
                filename=html.unescape(match.group(1)),
                image_type=html.unescape(match.group(2)),
                dimensions=_text(dimensions[-1]) if dimensions else "",
            )
        )
    return ColaForm(
        product_type=choice("Type of Product"),
        source=choice("Source of Product"),
        applicant=applicant,
        images=images,
    )


# The registry serves label images only within the session that viewed the form.
OPENER = urllib.request.build_opener(HTTPCookieProcessor(CookieJar()))


def http_get(url: str) -> bytes:
    if not url.startswith(BASE + "/"):
        raise ValueError(f"Refusing to fetch outside the COLA registry: {url}")
    # The check above pins the scheme and host to the registry's HTTPS address.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with OPENER.open(request, timeout=30) as response:
        data: bytes = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"Response larger than {MAX_BYTES} bytes: {url}")
    return data


def _short_type(image_type: str) -> str:
    lowered = image_type.lower()
    return next((kind for kind in ("front", "back", "neck", "strip") if kind in lowered), "other")


def _image_extension(data: bytes, url: str) -> str:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            kind = image.format or ""
    except Exception as error:
        raise ValueError(f"The registry returned something that is not an image: {url}") from error
    if kind not in EXTENSIONS:
        raise ValueError(f"Unexpected image format {kind!r}: {url}")
    return EXTENSIONS[kind]


def fetch(
    ttb_ids: Sequence[str],
    out_dir: Path = OUTPUT,
    *,
    get: Callable[[str], bytes] = http_get,
    sleep: Callable[[float], object] = time.sleep,
) -> list[ColaRecord]:
    def polite_get(url: str) -> bytes:
        data = get(url)
        sleep(PAUSE_SECONDS)
        return data

    records = []
    for ttb_id in ttb_ids:
        if not re.fullmatch(r"\d{14}", ttb_id):
            raise ValueError(f"A TTB ID is 14 digits: {ttb_id!r}")
        detail_url = DETAIL_URL.format(ttb_id=ttb_id)
        fields = parse_detail(polite_get(detail_url).decode("utf-8", "replace"))
        if fields.get("Status") != "APPROVED":
            raise ValueError(f"{ttb_id} is not approved (status {fields.get('Status')!r})")
        form = parse_form(polite_get(FORM_URL.format(ttb_id=ttb_id)).decode("utf-8", "replace"))

        folder = out_dir / ttb_id
        folder.mkdir(parents=True, exist_ok=True)
        for index, image in enumerate(form.images, start=1):
            url = IMAGE_URL.format(filename=quote(image.filename, safe=""))
            data = polite_get(url)
            image.saved_as = f"{index}-{_short_type(image.image_type)}{_image_extension(data, url)}"
            (folder / image.saved_as).write_bytes(data)

        record = ColaRecord(
            ttb_id=ttb_id,
            url=detail_url,
            status=fields["Status"],
            brand_name=fields.get("Brand Name", ""),
            fanciful_name=fields.get("Fanciful Name", ""),
            class_type_code=fields.get("Class/Type Code", ""),
            origin_code=fields.get("Origin Code", ""),
            approval_date=fields.get("Approval Date", ""),
            qualifications=fields.get("Qualifications", ""),
            total_bottle_capacity=fields.get("Total Bottle Capacity", ""),
            product_type=form.product_type,
            source=form.source,
            applicant=form.applicant,
            images=form.images,
        )
        (folder / "registry.json").write_text(
            record.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        records.append(record)
    return records


if __name__ == "__main__":
    for fetched in fetch(sys.argv[1:]):
        print(fetched.ttb_id, fetched.product_type, fetched.source, fetched.brand_name)

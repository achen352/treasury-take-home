"""The COLA registry downloader: parses public pages and fetches politely (no network here)."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts import fetch_cola
from scripts.fixtures import FIXTURES_ROOT

PAGES = FIXTURES_ROOT / "cola_pages"
TTB_ID = "26257001000366"
DETAIL = (PAGES / f"detail-{TTB_ID}.html").read_text(encoding="utf-8")
FORM = (PAGES / f"form-{TTB_ID}.html").read_text(encoding="utf-8")


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buffer, "PNG")
    return buffer.getvalue()


class FakeRegistry:
    """Serves the saved pages and a small image, recording every request."""

    def __init__(self, form: str = FORM, image: bytes | None = None) -> None:
        self.form = form
        self.image = png_bytes() if image is None else image
        self.requests: list[str] = []

    def get(self, url: str) -> bytes:
        self.requests.append(url)
        if "publicDisplaySearchBasic" in url:
            return DETAIL.encode()
        if "publicFormDisplay" in url:
            return self.form.encode()
        return self.image


def test_detail_page_fields_are_read() -> None:
    fields = fetch_cola.parse_detail(DETAIL)

    assert fields["TTB ID"] == TTB_ID
    assert fields["Status"] == "APPROVED"
    assert fields["Brand Name"] == "BELLE ISLE"
    assert fields["Class/Type Code"] == "STRAIGHT BOURBON WHISKY"
    assert fields["Origin Code"] == "VIRGINIA"


def test_form_gives_product_type_source_applicant_and_images() -> None:
    form = fetch_cola.parse_form(FORM)

    assert form.product_type == "Distilled Spirits"
    assert form.source == "Domestic"
    assert (
        form.applicant.splitlines()[0] == "Belle Isle Craft Spirits, Belle Isle Craft Spirits Inc."
    )
    assert "Richmond VA 23224" in form.applicant
    assert [(image.filename, image.image_type) for image in form.images] == [
        ("AS26 Front.png", "Brand (front) or keg collar"),
        ("AS26 Back.png", "Back"),
    ]
    assert all(image.dimensions == "9 inches W X 9 inches H" for image in form.images)


def test_fetch_saves_registry_fields_and_every_label_image(tmp_path: Path) -> None:
    registry = FakeRegistry()

    [record] = fetch_cola.fetch([TTB_ID], tmp_path, get=registry.get, sleep=lambda _: None)

    folder = tmp_path / TTB_ID
    saved = json.loads((folder / "registry.json").read_text(encoding="utf-8"))
    assert saved["brand_name"] == record.brand_name == "BELLE ISLE"
    assert [image.saved_as for image in record.images] == ["1-front.png", "2-back.png"]
    assert all((folder / image.saved_as).is_file() for image in record.images)


def test_fetch_is_polite_one_request_at_a_time_with_a_pause(tmp_path: Path) -> None:
    registry = FakeRegistry()
    pauses: list[float] = []

    fetch_cola.fetch([TTB_ID], tmp_path, get=registry.get, sleep=pauses.append)

    assert len(registry.requests) == 4  # detail, form, two images
    assert len(pauses) == len(registry.requests)
    assert all(pause >= 1.0 for pause in pauses)
    assert all(url.startswith("https://ttbonline.gov/colasonline/") for url in registry.requests)


def test_registry_filenames_are_never_used_as_local_paths(tmp_path: Path) -> None:
    registry = FakeRegistry(form=FORM.replace("AS26 Front.png", "../../evil.png"))

    [record] = fetch_cola.fetch([TTB_ID], tmp_path, get=registry.get, sleep=lambda _: None)

    assert record.images[0].saved_as == "1-front.png"
    assert not (tmp_path.parent / "evil.png").exists()
    assert "..%2F..%2Fevil.png" in registry.requests[2]  # sent URL-encoded, not as a path


def test_a_non_image_response_is_refused(tmp_path: Path) -> None:
    registry = FakeRegistry(image=b"<html>not an image</html>")

    with pytest.raises(ValueError, match="not an image"):
        fetch_cola.fetch([TTB_ID], tmp_path, get=registry.get, sleep=lambda _: None)


def test_only_approved_labels_are_fetched(tmp_path: Path) -> None:
    registry = FakeRegistry()
    original = fetch_cola.parse_detail

    def surrendered(html: str) -> dict[str, str]:
        return {**original(html), "Status": "SURRENDERED"}

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fetch_cola, "parse_detail", surrendered)
        with pytest.raises(ValueError, match="not approved"):
            fetch_cola.fetch([TTB_ID], tmp_path, get=registry.get, sleep=lambda _: None)


@pytest.mark.parametrize("bad_id", ["123", "2625700100036x", "../26257001000366"])
def test_ttb_ids_must_be_14_digits(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(ValueError, match="TTB ID"):
        fetch_cola.fetch([bad_id], tmp_path, get=FakeRegistry().get, sleep=lambda _: None)


def test_the_http_client_keeps_the_registry_session_cookie() -> None:
    # The registry only serves label images inside the session that viewed the form.
    handlers = fetch_cola.OPENER.handlers

    assert any(isinstance(handler, fetch_cola.HTTPCookieProcessor) for handler in handlers)

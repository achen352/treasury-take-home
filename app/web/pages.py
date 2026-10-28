"""The single-label page: the form, and checking a label against its application."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.config import Settings
from app.domain.models import Report
from app.readers import uploads
from app.readers.dual import check_label
from app.readers.uploads import LabelImage, UploadRejected, prepare_uploads
from app.web.forms import FIELDS, HINTS, LABELS, REQUIRED, form_values, read_application
from app.web.guards import client_address, too_many_response
from app.web.paste import PasteTooLong, parse_application_text
from app.web.samples import find_sample, load_samples
from app.web.view import build_results

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
router = APIRouter()

# The form has a handful of text fields; anything beyond these bounds is not a real browser.
MAX_FORM_FIELDS = 40
MAX_FILE_PARTS = 20  # more than MAX_IMAGES, so too many files get a message, not a crash
MAX_PASTE_BYTES = 128 * 1024  # room for MAX_PASTE_CHARS of any script
ACCEPT = "image/jpeg,image/png,image/webp,application/pdf"  # JPEG first: iPhones then send JPEG


@router.get("/", response_class=HTMLResponse)
def page(request: Request, sample: str | None = None) -> Response:
    values: dict[str, str] = {}
    if sample:
        found = find_sample(sample)
        if found is None:
            return _error(request, 404, "There is no sample label with that name.")
        values = form_values(found.application)
    return _render(request, values=values, sample=sample or "")


class CheckRefused(Exception):
    """A check that can't go ahead at all (another site, too many, busy). Safe to show."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class CheckOutcome:
    values: dict[str, str]
    sample_id: str
    errors: dict[str, str] = field(default_factory=dict)  # by field; "images" for the uploads
    report: Report | None = None
    images: list[LabelImage] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def server_timing(self) -> str:
        """How long each part took, for the browser's developer tools and the smoke test."""
        return ", ".join(
            f"{name};dur={seconds * 1000:.0f}" for name, seconds in self.timings.items()
        )


async def run_check(request: Request) -> CheckOutcome:
    """Check the label posted in a form: the page and the batch both come through here."""
    if _from_another_site(request):
        raise CheckRefused(403, "Labels can only be checked from this site's own page.")
    settings: Settings = request.app.state.settings
    if not request.app.state.limiter.allow(
        client_address(request.scope, settings.client_ip_header)
    ):
        raise CheckRefused(429, "That's a lot of checks in a short time. Please wait a minute.")
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        raise CheckRefused(415, "Send the label with the form on this page.")
    form = await request.form(
        max_files=MAX_FILE_PARTS, max_fields=MAX_FORM_FIELDS, max_part_size=MAX_PASTE_BYTES
    )
    values = {name: value for name in FIELDS if isinstance(value := form.get(name), str)}
    pasted = form.get("application_text")
    pasted = pasted if isinstance(pasted, str) else ""
    paste_error = ""
    if pasted.strip():
        # Without the page's script, pasted text fills the fields that were left empty. The
        # product type and source come from it when given, since their controls always have one.
        try:
            parsed = parse_application_text(pasted)
        except PasteTooLong as too_long:
            paste_error = str(too_long)
        else:
            for name, value in parsed.values.items():
                if name in ("beverage_type", "imported") or not values.get(name, "").strip():
                    values[name] = value
    values["application_text"] = pasted
    sample_id = form.get("sample")
    sample_id = sample_id if isinstance(sample_id, str) else ""
    outcome = CheckOutcome(values=values, sample_id=sample_id)
    # Browsers send an empty part when no file is chosen; file names are never read.
    files = [part for part in form.getlist("images") if isinstance(part, UploadFile) and part.size]

    application, errors = read_application(values)
    if paste_error:
        application, errors = None, {**errors, "application_text": paste_error}
    if files:
        datas = [await part.read() for part in files]
    elif sample_id:
        sample = find_sample(sample_id)
        if sample is None:
            raise CheckRefused(404, "There is no sample label with that name.")
        datas = [path.read_bytes() for path in sample.images]
    else:
        datas = []
    if application is None:
        outcome.errors = errors
        return outcome
    try:
        outcome.images = prepare_uploads(datas)
    except UploadRejected as rejected:
        outcome.errors = {"images": str(rejected)}
        return outcome

    extras: dict[str, Any] = {}
    if request.app.state.ocr_reader is not None:
        extras["ocr_reader"] = request.app.state.ocr_reader
    # Only a few checks run at once, so a small server's memory holds them all.
    slots: asyncio.Semaphore = request.app.state.check_slots
    try:
        await asyncio.wait_for(slots.acquire(), timeout=settings.check_wait_seconds)
    except TimeoutError:
        raise CheckRefused(
            503, "The checker is busy right now. Please try again in a moment."
        ) from None
    timings: dict[str, float] = {}
    started = time.perf_counter()
    try:
        outcome.report = await check_label(
            outcome.images,
            application,
            settings,
            extractor=request.app.state.extractor,
            timings=timings,
            **extras,
        )
    finally:
        slots.release()
    outcome.timings = {"total": time.perf_counter() - started, **timings}
    logger.info(
        "check took %.2f s (ai %.2f s, ocr %.2f s, %d images)",
        outcome.timings["total"],
        timings.get("ai", 0.0),
        timings.get("ocr", 0.0),
        len(outcome.images),
    )
    return outcome


@router.post("/check", response_class=HTMLResponse)
async def check(request: Request) -> Response:
    try:
        outcome = await run_check(request)
    except CheckRefused as refused:
        if refused.status == 429:
            return too_many_response()
        return _error(request, refused.status, refused.message)
    if outcome.report is None:
        return _render(
            request,
            values=outcome.values,
            sample=outcome.sample_id,
            errors=outcome.errors,
            status=422,
        )
    response = _render(
        request,
        values=outcome.values,
        sample=outcome.sample_id,
        results=build_results(outcome.report, outcome.images),
    )
    response.headers["Server-Timing"] = outcome.server_timing()
    return response


@router.post("/application/parse")
async def parse_application(request: Request) -> Response:
    """Pasted application text, read into the form's fields for the page to fill in."""
    if _from_another_site(request):
        return JSONResponse({"error": "Only this site's own page can do that."}, status_code=403)
    form = await request.form(max_files=0, max_fields=5, max_part_size=MAX_PASTE_BYTES)
    text = form.get("text")
    try:
        parsed = parse_application_text(text if isinstance(text, str) else "")
    except PasteTooLong as too_long:
        return JSONResponse({"error": str(too_long)}, status_code=422)
    return JSONResponse(
        {
            "values": parsed.values,
            "filled": [LABELS[name] for name in parsed.filled],
            "missing": [LABELS[name] for name in parsed.missing],
        }
    )


def _from_another_site(request: Request) -> bool:
    """Whether a post came from another site's page. Browsers say so in Sec-Fetch-Site; with
    Referrer-Policy: no-referrer they send "Origin: null" even for this site's own forms."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site in ("cross-site", "same-site")
    origin = request.headers.get("origin")
    return (
        bool(origin) and origin != "null" and urlsplit(origin).netloc != request.headers.get("host")
    )


def _render(
    request: Request,
    *,
    values: dict[str, str],
    sample: str,
    errors: dict[str, str] | None = None,
    results: object = None,
    status: int = 200,
) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "values": values,
            "sample": sample,
            "samples": load_samples(),
            "errors": errors or {},
            "labels": LABELS,
            "hints": HINTS,
            "required": REQUIRED,
            "results": results,
            "accept": ACCEPT,
            "max_bytes": uploads.MAX_FILE_BYTES,
            "max_files": uploads.MAX_IMAGES,
            "too_large": uploads.TOO_LARGE,
            "too_many": uploads.TOO_MANY_IMAGES,
        },
        status_code=status,
    )


def _error(request: Request, status: int, message: str) -> Response:
    return templates.TemplateResponse(
        request, "error.html", {"message": message}, status_code=status
    )

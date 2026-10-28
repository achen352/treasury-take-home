"""The single-label page: the form, and checking a label against its application."""

import asyncio
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.config import Settings
from app.readers import uploads
from app.readers.dual import check_label
from app.readers.uploads import UploadRejected, prepare_uploads
from app.web.forms import FIELDS, LABELS, form_values, read_application
from app.web.guards import client_address, too_many_response
from app.web.samples import find_sample, load_samples
from app.web.view import build_results

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
router = APIRouter()

# The form has a handful of text fields; anything beyond these bounds is not a real browser.
MAX_FORM_FIELDS = 40
MAX_FIELD_BYTES = 16 * 1024
MAX_FILE_PARTS = 20  # more than MAX_IMAGES, so too many files get a message, not a crash
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


@router.post("/check", response_class=HTMLResponse)
async def check(request: Request) -> Response:
    if _from_another_site(request):
        return _error(request, 403, "Labels can only be checked from this site's own page.")
    settings: Settings = request.app.state.settings
    if not request.app.state.limiter.allow(
        client_address(request.scope, settings.client_ip_header)
    ):
        return too_many_response()
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith(("multipart/form-data", "application/x-www-form-urlencoded")):
        return _error(request, 415, "Send the label with the form on this page.")
    form = await request.form(
        max_files=MAX_FILE_PARTS, max_fields=MAX_FORM_FIELDS, max_part_size=MAX_FIELD_BYTES
    )
    values = {name: value for name in FIELDS if isinstance(value := form.get(name), str)}
    sample_id = form.get("sample")
    sample_id = sample_id if isinstance(sample_id, str) else ""
    # Browsers send an empty part when no file is chosen; file names are never read.
    files = [part for part in form.getlist("images") if isinstance(part, UploadFile) and part.size]

    application, errors = read_application(values)
    if files:
        datas = [await part.read() for part in files]
    elif sample_id:
        sample = find_sample(sample_id)
        if sample is None:
            return _error(request, 404, "There is no sample label with that name.")
        datas = [path.read_bytes() for path in sample.images]
    else:
        datas = []
    if application is None:
        return _render(request, values=values, sample=sample_id, errors=errors, status=422)

    try:
        images = prepare_uploads(datas)
    except UploadRejected as rejected:
        return _render(
            request, values=values, sample=sample_id, errors={"images": str(rejected)}, status=422
        )

    extras: dict[str, Any] = {}
    if request.app.state.ocr_reader is not None:
        extras["ocr_reader"] = request.app.state.ocr_reader
    # Only a few checks run at once, so a small server's memory holds them all.
    slots: asyncio.Semaphore = request.app.state.check_slots
    try:
        await asyncio.wait_for(slots.acquire(), timeout=settings.check_wait_seconds)
    except TimeoutError:
        return _error(request, 503, "The checker is busy right now. Please try again in a moment.")
    timings: dict[str, float] = {}
    started = time.perf_counter()
    try:
        report = await check_label(
            images,
            application,
            settings,
            extractor=request.app.state.extractor,
            timings=timings,
            **extras,
        )
    finally:
        slots.release()
    total = time.perf_counter() - started
    logger.info(
        "check took %.2f s (ai %.2f s, ocr %.2f s, %d images)",
        total,
        timings.get("ai", 0.0),
        timings.get("ocr", 0.0),
        len(images),
    )
    response = _render(
        request, values=values, sample=sample_id, results=build_results(report, images)
    )
    # How long each part took, for the browser's developer tools and the smoke test; no content.
    response.headers["Server-Timing"] = ", ".join(
        f"{name};dur={seconds * 1000:.0f}" for name, seconds in {"total": total, **timings}.items()
    )
    return response


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

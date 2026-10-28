"""The batch page: the browser reads a spreadsheet and checks its labels one at a time here.

Nothing is kept between requests. The browser holds the spreadsheet, the images and the results,
and sends the results back only to have them turned into a CSV.
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import UploadFile

from app.domain.models import Status
from app.web.batch import MAX_ROWS, BatchResult, SheetProblem, export_csv, read_sheet, template_csv
from app.web.forms import LABELS, form_values
from app.web.pages import CheckRefused, _from_another_site, run_check, templates
from app.web.samples import load_samples
from app.web.view import FIELD_NAMES, STATUS_WORDS, summary_of

router = APIRouter()
_RESULTS = TypeAdapter(list[BatchResult])
MAX_EXPORT_BYTES = 2 * 1024 * 1024


@router.get("/batch", response_class=HTMLResponse)
def batch_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "batch.html", {"max_rows": MAX_ROWS})


@router.get("/batch/template.csv")
def batch_template() -> Response:
    return Response(
        template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="labels-template.csv"'},
    )


@router.post("/batch/read")
async def batch_read(request: Request) -> Response:
    if _from_another_site(request):
        return JSONResponse({"error": "Only this site's own page can do that."}, status_code=403)
    form = await request.form(max_files=1, max_fields=5)
    sheet = form.get("sheet")
    data = await sheet.read() if isinstance(sheet, UploadFile) else b""
    try:
        read = read_sheet(data)
    except SheetProblem as problem:
        return JSONResponse({"error": str(problem)}, status_code=422)
    return JSONResponse(
        {
            "rows": [
                {
                    "number": row.number,
                    "images": row.images,
                    "values": row.values,
                    "errors": row.errors,
                }
                for row in read.rows
            ],
            "unknown_columns": read.unknown_columns,
        }
    )


@router.get("/batch/samples")
def batch_samples() -> Response:
    """The example batch: every sample label, checked by name instead of by uploaded images."""
    return JSONResponse(
        {
            "rows": [
                {
                    "number": index + 2,
                    "sample": sample.id,
                    "images": [path.name for path in sample.images],
                    "values": form_values(sample.application),
                    "errors": {},
                }
                for index, sample in enumerate(load_samples())
            ]
        }
    )


@router.post("/batch/check")
async def batch_check(request: Request) -> Response:
    try:
        outcome = await run_check(request)
    except CheckRefused as refused:
        headers = {"Retry-After": "60"} if refused.status == 429 else {}
        return JSONResponse({"error": refused.message}, status_code=refused.status, headers=headers)
    if outcome.report is None:
        first = next(iter(outcome.errors.items()), ("", "This label couldn't be checked."))
        field_name = LABELS.get(first[0], "")
        message = f"{field_name}: {first[1]}" if field_name else first[1]
        return JSONResponse({"error": message, "errors": outcome.errors}, status_code=422)
    report = outcome.report
    response = JSONResponse(
        {
            "verdict": report.verdict.value,
            "summary": summary_of(report.results),
            "items": [
                {
                    "name": FIELD_NAMES[result.field],
                    "status": result.status.value,
                    "status_word": STATUS_WORDS[result.status],
                    "expected": result.expected,
                    "found": result.found,
                    "notes": list(result.notes) if result.status is not Status.PASS else [],
                }
                for result in report.results
            ],
            "notes": list(report.notes),
        }
    )
    response.headers["Server-Timing"] = outcome.server_timing()
    return response


@router.post("/batch/export")
async def batch_export(request: Request) -> Response:
    if _from_another_site(request):
        return JSONResponse({"error": "Only this site's own page can do that."}, status_code=403)
    form = await request.form(max_files=0, max_fields=5, max_part_size=MAX_EXPORT_BYTES)
    raw = form.get("results")
    try:
        results = _RESULTS.validate_python(json.loads(raw if isinstance(raw, str) else ""))
    except (ValueError, ValidationError):
        return JSONResponse({"error": "Those aren't batch results."}, status_code=422)
    if len(results) > MAX_ROWS:
        return JSONResponse({"error": f"At most {MAX_ROWS} results."}, status_code=422)
    return Response(
        export_csv(results),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="label-results.csv"'},
    )

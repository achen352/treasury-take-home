"""Application factory. Run with: python -m app.server"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.formparsers import MultiPartParser

from app.config import ExtractorMode, Settings
from app.readers.ai import make_extractor
from app.readers.dual import OcrReader
from app.readers.extractor import Extractor
from app.readers.uploads import MAX_FILE_BYTES
from app.web.guards import AccessCodeMiddleware, BodyLimitMiddleware, RateLimiter
from app.web.middleware import DOCS_CSP, RequestContextMiddleware, SecurityHeadersMiddleware
from app.web.pages import router as pages
from app.web.routes import router

STATIC = Path(__file__).resolve().parent / "web" / "static"

# Starlette writes an upload over 1 MB to a temporary file on disk. Uploads are capped at
# MAX_FILE_BYTES each, so they are kept in memory up to that size instead: nothing touches disk.
MultiPartParser.spool_max_size = MAX_FILE_BYTES


def create_app(
    settings: Settings | None = None,
    *,
    extractor: Extractor | None = None,
    ocr_reader: OcrReader | None = None,
) -> FastAPI:
    """The app. Tests pass stand-in readers; otherwise the AI reader is built at startup."""
    if settings is None:
        settings = Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if extractor is not None or settings.extractor_mode is ExtractorMode.OCR:
            app.state.extractor = extractor
            yield
            return
        # One HTTP client for the app's life, so connections to the provider are reused.
        async with httpx2.AsyncClient() as client:
            app.state.extractor = make_extractor(settings, client)
            yield

    app = FastAPI(
        title="COLA Label Verifier",
        # API docs widen the attack surface, so they are opt-in for local development.
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_docs else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.extractor = extractor
    app.state.ocr_reader = ocr_reader
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)
    app.state.check_slots = asyncio.Semaphore(settings.max_concurrent_checks)
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(
        AccessCodeMiddleware, code_sha256=settings.access_code_sha256, limiter=app.state.limiter
    )
    # Last added runs outermost: security headers must also wrap the 500s
    # produced by RequestContextMiddleware.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_overrides={"/docs": DOCS_CSP} if settings.enable_docs else None,
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(router)
    app.include_router(pages)
    return app

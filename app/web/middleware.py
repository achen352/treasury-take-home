"""ASGI middleware: request IDs and a last-resort error handler.

Written as plain ASGI (not BaseHTTPMiddleware) so it also wraps responses
produced by exception handlers and never buffers request bodies.
"""

import logging
import re
import uuid

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

STRICT_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
# FastAPI's Swagger UI page pulls assets from jsDelivr and boots with an inline script.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
BASELINE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}

REQUEST_ID_HEADER = "X-Request-ID"
# Request IDs are written to logs, so only short, boring values are trusted from clients.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _request_id_from(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate: str = value.decode("latin-1")
            if _SAFE_REQUEST_ID.fullmatch(candidate):
                return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Tags every response with a request ID and turns unhandled errors into a generic 500."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id_from(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        response_started = False
        status = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
            # The access log: never the query string, which can carry the access code.
            logger.info(
                "%s %s %s (request_id=%s)", scope["method"], scope["path"], status, request_id
            )
        except Exception:
            # Full detail goes to the server log only; the client gets an opaque reference.
            logger.exception("Unhandled error (request_id=%s)", request_id)
            if response_started:
                raise
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
            await response(scope, receive, send_with_request_id)


class SecurityHeadersMiddleware:
    """Adds hardening headers to every HTTP response, including error responses."""

    def __init__(self, app: ASGIApp, csp_overrides: dict[str, str] | None = None) -> None:
        self.app = app
        self.csp_overrides = csp_overrides or {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        csp = self.csp_overrides.get(scope["path"], STRICT_CSP)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = csp
                for name, value in BASELINE_HEADERS.items():
                    headers[name] = value
                headers.setdefault("Cache-Control", "no-store")
            await send(message)

        await self.app(scope, receive, send_with_headers)

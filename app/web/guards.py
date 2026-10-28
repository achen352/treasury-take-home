"""Guards in front of the page: the access code, rate limits and the request size."""

import hashlib
import hmac
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import parse_qsl, urlencode

from starlette.requests import cookie_parser
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ACCESS_COOKIE = "access"
ACCESS_COOKIE_DAYS = 30
OPEN_PATHS = ("/healthz", "/static/")  # the health check, and files that reveal nothing
LOCKED_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>Access denied | COLA Label Verifier</title>"
    '<link rel="stylesheet" href="/static/app.css"></head><body><main>'
    "<h1>Access denied</h1><p>This site needs an access key. Open it with the link from the "
    "submission, which includes the key.</p></main></body></html>"
)
TOO_MANY_PAGE = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>Please wait | COLA Label Verifier</title>"
    '<link rel="stylesheet" href="/static/app.css"></head><body><main>'
    "<h1>Please wait a minute</h1><p>That's a lot of checks in a short time. Please wait a "
    'minute and try again. <a href="/">Back to the form</a></p></main></body></html>'
)

TOO_LARGE_PAGE = (
    '<!doctype html><html lang="en"><title>Too large</title>'
    "<p>That upload is too large. A label's images can total {limit} MB at most.</p></html>"
)
NO_LENGTH_PAGE = (
    '<!doctype html><html lang="en"><title>Length required</title>'
    "<p>The upload didn't say how large it is.</p></html>"
)


class BodyLimitMiddleware:
    """Refuses a POST that is too large, or doesn't say how large it is, before reading it."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        length = headers.get(b"content-length")
        if length is None:
            await HTMLResponse(NO_LENGTH_PAGE, status_code=411)(scope, receive, send)
            return
        if not length.isdigit() or int(length) > self.max_bytes:
            page = TOO_LARGE_PAGE.format(limit=self.max_bytes // (1024 * 1024))
            await HTMLResponse(page, status_code=413)(scope, receive, send)
            return

        received = 0

        async def counted() -> Message:
            # A client that sends more than it declared is cut off.
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    return {"type": "http.disconnect"}
            return message

        await self.app(scope, counted, send)


class RateLimiter:
    """At most `per_minute` and `per_day` attempts per client address, in sliding windows."""

    def __init__(
        self,
        per_minute: int,
        per_day: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_clients: int = 10_000,
    ) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self.clock = clock
        self.max_clients = max_clients
        self._attempts: dict[str, deque[float]] = {}

    def allow(self, client: str) -> bool:
        """Whether this client may make another attempt now; an allowed attempt is recorded."""
        now = self.clock()
        attempts = self._attempts.pop(client, None) or deque()
        while attempts and now - attempts[0] >= 86_400:
            attempts.popleft()
        recent = sum(1 for moment in attempts if now - moment < 60)
        allowed = recent < self.per_minute and len(attempts) < self.per_day
        if allowed:
            attempts.append(now)
        self._attempts[client] = attempts  # re-inserted, so the dict stays oldest-first
        while len(self._attempts) > self.max_clients:
            del self._attempts[next(iter(self._attempts))]  # forget the least recent address
        return allowed

    def tracked(self) -> int:
        return len(self._attempts)


def too_many_response() -> HTMLResponse:
    return HTMLResponse(TOO_MANY_PAGE, status_code=429, headers={"Retry-After": "60"})


def client_address(scope: Scope, header: str | None = None) -> str:
    """The client's address: from the hosting proxy's own header if one is configured, which
    clients can't forge, else from the connection."""
    if header:
        headers: dict[bytes, bytes] = dict(scope["headers"])
        value = headers.get(header.lower().encode("latin-1"))
        if value:
            return value.decode("latin-1").strip()
    client = scope.get("client")
    return str(client[0]) if client else "unknown"


class AccessCodeMiddleware:
    """Locks the site behind a code given only in the submission link.

    The link carries ?key=<code> once. A correct code is kept in a secure cookie and the visitor
    is sent to the same page without it, so the code leaves the address bar and the history.
    Only the code's SHA-256 is configured, and codes are compared in constant time.
    """

    def __init__(
        self,
        app: ASGIApp,
        code_sha256: str | None,
        limiter: RateLimiter,
        client_ip_header: str | None = None,
    ) -> None:
        self.app = app
        self.code_sha256 = code_sha256
        self.limiter = limiter
        self.client_ip_header = client_ip_header

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.code_sha256 is None
            or scope["path"].startswith(OPEN_PATHS)
        ):
            await self.app(scope, receive, send)
            return

        query = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        key = next((value for name, value in query if name == "key"), None)
        if key is not None:
            if self._valid(key):
                rest = urlencode([(name, value) for name, value in query if name != "key"])
                path = scope["path"] if not scope["path"].startswith("//") else "/"
                redirect = RedirectResponse(path + (f"?{rest}" if rest else ""), status_code=303)
                redirect.set_cookie(
                    ACCESS_COOKIE,
                    key,
                    max_age=ACCESS_COOKIE_DAYS * 86_400,
                    path="/",
                    secure=True,
                    httponly=True,
                    samesite="strict",
                )
                await redirect(scope, receive, send)
                return
            if not self.limiter.allow(client_address(scope, self.client_ip_header)):
                await too_many_response()(scope, receive, send)
                return
            await HTMLResponse(LOCKED_PAGE, status_code=403)(scope, receive, send)
            return

        cookies = cookie_parser(dict(scope["headers"]).get(b"cookie", b"").decode("latin-1"))
        cookie = cookies.get(ACCESS_COOKIE)
        if cookie is not None and self._valid(cookie):
            await self.app(scope, receive, send)
            return
        await HTMLResponse(LOCKED_PAGE, status_code=403)(scope, receive, send)

    def _valid(self, code: str) -> bool:
        digest = hashlib.sha256(code.encode()).hexdigest()
        return hmac.compare_digest(digest, self.code_sha256 or "")

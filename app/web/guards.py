"""Guards in front of the page: request size now; the access code and rate limits join it."""

from starlette.responses import HTMLResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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

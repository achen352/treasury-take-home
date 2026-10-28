"""The smoke test of the live site, run here against a faked site."""

import re
from collections.abc import Callable

import httpx2
import pytest

from scripts import smoke

CODE = "test-access-code-not-real-0123456789"
URL = "https://example-app.fly.dev"
HEADERS = {
    "content-security-policy": "default-src 'self'",
    "strict-transport-security": "max-age=63072000",
    "x-content-type-options": "nosniff",
    "cache-control": "no-store",
    "x-request-id": "abc123",
}
RESULTS = '<div class="verdict verdict-matches"><p class="verdict-words">Matches</p></div>'


def fake_site(
    *, locked: bool = True, verdict_html: str = RESULTS
) -> Callable[[httpx2.Request], httpx2.Response]:
    def handle(request: httpx2.Request) -> httpx2.Response:
        path, query = request.url.path, request.url.query.decode()
        has_cookie = f"access={CODE}" in request.headers.get("cookie", "")
        if path == "/healthz":
            return httpx2.Response(200, json={"status": "ok"}, headers=HEADERS)
        if path.startswith("/static/"):
            return httpx2.Response(200, text="body {}", headers=HEADERS)
        if path == "/" and query == f"key={CODE}":
            return httpx2.Response(
                303,
                headers={
                    **HEADERS,
                    "location": "/",
                    "set-cookie": f"access={CODE}; HttpOnly; Path=/; SameSite=strict; Secure",
                },
            )
        if locked and not has_cookie:
            return httpx2.Response(403, text="needs the link", headers=HEADERS)
        if path == "/check":
            return httpx2.Response(
                200,
                text=verdict_html,
                headers={**HEADERS, "server-timing": "ai;dur=1800, ocr;dur=900, total;dur=2100"},
            )
        return httpx2.Response(200, text="<form>", headers=HEADERS)

    return handle


def run(
    handler: Callable[[httpx2.Request], httpx2.Response],
    code: str | None,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    with httpx2.Client(transport=httpx2.MockTransport(handler), base_url=URL) as client:
        status = smoke.main(["--url", URL], client=client, code=code)
    return status, capsys.readouterr().out


def test_a_healthy_site_passes_every_check(capsys: pytest.CaptureFixture[str]) -> None:
    status, out = run(fake_site(), CODE, capsys)

    assert status == 0
    assert "Matches" in out
    assert re.search(r"total;dur=2100", out)
    assert CODE not in out


def test_a_site_that_is_not_locked_fails(capsys: pytest.CaptureFixture[str]) -> None:
    status, out = run(fake_site(locked=False), CODE, capsys)

    assert status == 1
    assert "FAIL" in out


def test_a_sample_that_does_not_match_fails(capsys: pytest.CaptureFixture[str]) -> None:
    status, _ = run(
        fake_site(verdict_html='<p class="verdict-words">Needs review</p>'), CODE, capsys
    )

    assert status == 1


def test_without_a_code_only_the_public_checks_run(capsys: pytest.CaptureFixture[str]) -> None:
    status, out = run(fake_site(), None, capsys)

    assert status == 0
    assert "skipped" in out.lower()


def test_the_code_comes_from_the_environment_and_is_never_printed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SMOKE_ACCESS_CODE", CODE)

    assert smoke.access_code() == CODE
    status, out = run(fake_site(), smoke.access_code(), capsys)
    assert status == 0 and CODE not in out

"""Hardening headers are present on every response, including errors."""

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(params=["ok", "not_found", "server_error"])
def any_response(request: pytest.FixtureRequest, app: FastAPI) -> httpx2.Response:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    paths = {"ok": "/healthz", "not_found": "/nope", "server_error": "/boom"}
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.get(paths[request.param])


def csp_directives(response: httpx2.Response) -> dict[str, str]:
    policy = response.headers["Content-Security-Policy"]
    directives = (part.strip().split(" ", 1) for part in policy.split(";") if part.strip())
    return {d[0]: (d[1] if len(d) > 1 else "") for d in directives}


def test_strict_content_security_policy(any_response: httpx2.Response) -> None:
    csp = csp_directives(any_response)

    assert csp["default-src"] == "'self'"
    assert csp["frame-ancestors"] == "'none'"
    assert csp["object-src"] == "'none'"
    assert csp["base-uri"] == "'none'"
    assert "unsafe-inline" not in any_response.headers["Content-Security-Policy"]


def test_baseline_hardening_headers(any_response: httpx2.Response) -> None:
    headers = any_response.headers

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    hsts_max_age = int(headers["Strict-Transport-Security"].split("max-age=")[1].split(";")[0])
    assert hsts_max_age >= 31_536_000
    for feature in ("camera=()", "microphone=()", "geolocation=()"):
        assert feature in headers["Permissions-Policy"]


def test_responses_are_not_cached_by_default(any_response: httpx2.Response) -> None:
    # Results pages will contain submitted label data; keep them out of shared caches.
    assert any_response.headers["Cache-Control"] == "no-store"


def test_app_does_not_advertise_its_server(any_response: httpx2.Response) -> None:
    assert "server" not in {name.lower() for name in any_response.headers}


def test_docs_page_csp_is_relaxed_only_on_the_docs_path() -> None:
    # Swagger UI loads from a CDN with an inline bootstrap script; that must not
    # weaken the policy anywhere else, even when docs are enabled.
    app = create_app(Settings(_env_file=None, enable_docs=True))  # type: ignore[call-arg]

    with TestClient(app) as client:
        docs_csp = client.get("/docs").headers["Content-Security-Policy"]
        health_csp = client.get("/healthz").headers["Content-Security-Policy"]

    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "'unsafe-inline'" not in health_csp
    assert "cdn.jsdelivr.net" not in health_csp

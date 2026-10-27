"""Health check, error responses, request IDs, and the API docs toggle."""

import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

INTERNAL_DETAIL = "db password is hunter2 at /srv/app/secret.py"


def test_health_check_reports_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_is_a_plain_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert "Traceback" not in response.text


def test_unhandled_exception_returns_generic_500_with_request_id(app: FastAPI) -> None:
    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError(INTERNAL_DETAIL)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    request_id = response.headers["X-Request-ID"]
    assert response.json() == {"detail": "Internal server error", "request_id": request_id}
    assert INTERNAL_DETAIL not in response.text
    assert "Traceback" not in response.text


def test_every_response_gets_a_generated_request_id(client: TestClient) -> None:
    first = client.get("/healthz").headers["X-Request-ID"]
    second = client.get("/does-not-exist").headers["X-Request-ID"]

    assert re.fullmatch(r"[0-9a-f]{32}", first)
    assert re.fullmatch(r"[0-9a-f]{32}", second)
    assert first != second


def test_safe_client_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "agent-42.retry_1"})

    assert response.headers["X-Request-ID"] == "agent-42.retry_1"


@pytest.mark.parametrize(
    "unsafe_id",
    ["<script>alert(1)</script>", "a" * 65, "id with spaces", "../../etc/passwd"],
)
def test_unsafe_client_request_id_is_replaced(client: TestClient, unsafe_id: str) -> None:
    # Request IDs end up in logs, so untrusted values must not be reflected.
    response = client.get("/healthz", headers={"X-Request-ID": unsafe_id})

    assert response.headers["X-Request-ID"] != unsafe_id
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_api_docs_can_be_enabled_for_local_development() -> None:
    app = create_app(Settings(_env_file=None, enable_docs=True))  # type: ignore[call-arg]

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

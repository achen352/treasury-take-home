"""The production launch settings for uvicorn."""

import socket
import threading
import time

import httpx2
import pytest
import uvicorn

from app.config import Settings
from app.main import create_app
from app.server import uvicorn_options


def test_real_server_does_not_advertise_itself(settings: Settings) -> None:
    options = uvicorn_options(settings) | {"app": create_app(settings), "factory": False}
    options.pop("host")
    options.pop("port")
    server = uvicorn.Server(uvicorn.Config(**options, log_level="warning"))

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.05)
        response = httpx2.get(f"http://127.0.0.1:{port}/healthz")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert response.status_code == 200
    assert "server" not in {name.lower() for name in response.headers}


def test_trusts_forwarded_headers_only_from_configured_proxies(settings: Settings) -> None:
    # Spoofed X-Forwarded-For would defeat per-IP rate limiting, so only localhost
    # is trusted unless a deployment (e.g. Render's proxy) says otherwise.
    assert uvicorn_options(settings)["forwarded_allow_ips"] == "127.0.0.1"

    render = Settings(_env_file=None, forwarded_allow_ips="*")  # type: ignore[call-arg]
    assert uvicorn_options(render)["forwarded_allow_ips"] == "*"


def test_listens_on_the_platform_provided_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "10000")

    options = uvicorn_options(Settings(_env_file=None))  # type: ignore[call-arg]

    assert options["port"] == 10000
    assert options["host"] == "0.0.0.0"  # noqa: S104 - container needs all interfaces

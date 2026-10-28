"""The access code, rate limits and other guards in front of the page."""

import asyncio
import hashlib
import logging
import re
import subprocess
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.constants import HEALTH_WARNING
from app.main import create_app
from app.readers.extractor import ImageReading
from app.web.guards import RateLimiter
from scripts.fixtures import FIXTURES_ROOT
from tests.fakes import FakeExtractor, FakeOcr
from tests.samples import OLD_TOM_LABEL_LINES, OLD_TOM_READING

CODE = "test-access-code-not-real-0123456789"
CODE_HASH = hashlib.sha256(CODE.encode()).hexdigest()
OLD_TOM_PNG = (FIXTURES_ROOT / "synthetic" / "old-tom" / "label.png").read_bytes()
FORM = {
    "beverage_type": "spirits",
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "bottler": "Old Tom Distillery, Louisville, Kentucky",
}


def make_client(extractor: FakeExtractor | None = None, **overrides: object) -> TestClient:
    settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    app = create_app(
        settings,
        extractor=extractor or FakeExtractor(ImageReading(OLD_TOM_READING)),
        ocr_reader=FakeOcr([(*OLD_TOM_LABEL_LINES, HEALTH_WARNING)] * 6),
    )
    # Secure cookies are only sent over HTTPS, as on the real site.
    return TestClient(app, base_url="https://testserver", raise_server_exceptions=False)


@pytest.fixture
def locked() -> Iterator[TestClient]:
    with make_client(access_code_sha256=CODE_HASH) as client:
        yield client


def check(client: TestClient, **headers: str) -> int:
    response = client.post(
        "/check", data=FORM, files=[("images", ("l.png", OLD_TOM_PNG))], headers=headers
    )
    return response.status_code


# ---- the access code ----


def test_without_the_code_every_page_is_locked(locked: TestClient) -> None:
    page = locked.get("/")

    assert page.status_code == 403
    assert "needs the link from the submission" in page.text
    assert check(locked) == 403


def test_the_health_check_and_static_files_stay_open(locked: TestClient) -> None:
    assert locked.get("/healthz").status_code == 200
    assert locked.get("/static/app.css").status_code == 200


def test_the_code_in_the_link_sets_a_secure_cookie_and_leaves_the_address_bar(
    locked: TestClient,
) -> None:
    response = locked.get(f"/?sample=old-tom&key={CODE}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/?sample=old-tom"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"access={CODE}")
    for attribute in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
        assert attribute.lower() in cookie.lower()


def test_the_cookie_then_opens_every_page(locked: TestClient) -> None:
    locked.get(f"/?key={CODE}")

    assert locked.get("/").status_code == 200
    assert check(locked) == 200


def test_a_wrong_code_or_cookie_is_refused(locked: TestClient) -> None:
    assert locked.get("/?key=wrong-code").status_code == 403
    locked.cookies.set("access", "wrong-code", domain="testserver")
    assert locked.get("/").status_code == 403


def test_wrong_codes_count_against_the_rate_limit() -> None:
    with make_client(access_code_sha256=CODE_HASH, rate_limit_per_minute=3) as client:
        statuses = [client.get(f"/?key=guess-{n}").status_code for n in range(5)]

    assert statuses[:3] == [403, 403, 403]
    assert statuses[3:] == [429, 429]


def test_with_no_code_configured_the_site_is_open() -> None:
    with make_client() as client:
        assert client.get("/").status_code == 200


def test_the_stored_value_must_be_a_sha256_hash() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        Settings(_env_file=None, access_code_sha256=CODE)  # type: ignore[call-arg]


def test_the_code_never_reaches_the_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with make_client(access_code_sha256=CODE_HASH) as client:
        client.get(f"/?key={CODE}")
        client.get("/?key=wrong-guess")

    assert CODE not in caplog.text
    assert "wrong-guess" not in caplog.text
    assert re.search(r"GET / 303", caplog.text)  # requests are logged, without their query


def test_the_server_keeps_query_strings_out_of_its_access_log() -> None:
    from app.server import uvicorn_options

    assert uvicorn_options(Settings(_env_file=None))["access_log"] is False  # type: ignore[call-arg]


def test_the_helper_makes_a_random_code_and_its_hash() -> None:
    done = subprocess.run(  # nosec B603 - our own script
        [sys.executable, "-m", "scripts.access_code"], capture_output=True, text=True, check=True
    )
    code = re.search(r"Code[^:]*:\s*(\S+)", done.stdout)
    digest = re.search(r"SHA-256[^:]*:\s*([0-9a-f]{64})", done.stdout)

    assert code is not None and digest is not None
    assert len(code.group(1)) >= 22
    assert hashlib.sha256(code.group(1).encode()).hexdigest() == digest.group(1)


# ---- rate limits and other guards ----


def test_more_than_ten_checks_a_minute_from_one_address_get_a_friendly_429() -> None:
    with make_client() as client:
        statuses = [check(client) for _ in range(11)]
        response = client.post("/check", data=FORM, files=[("images", ("l.png", OLD_TOM_PNG))])

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429
    assert "try again" in response.text.lower()
    assert "retry-after" in {name.lower() for name in response.headers}


def test_the_daily_limit_applies_too() -> None:
    clock = [0.0]
    limiter = RateLimiter(per_minute=10, per_day=200, clock=lambda: clock[0])

    allowed = 0
    for _ in range(300):
        clock[0] += 61  # past the minute window each time
        allowed += limiter.allow("203.0.113.9")

    assert allowed == 200


def test_the_limiter_forgets_old_addresses_so_it_cannot_grow_without_bound() -> None:
    limiter = RateLimiter(per_minute=10, per_day=200, max_clients=100)

    for n in range(1_000):
        limiter.allow(f"198.51.100.{n}")

    assert limiter.tracked() <= 100


def test_at_most_two_checks_run_at_once_and_a_third_is_told_to_try_again() -> None:
    slow = FakeExtractor(ImageReading(OLD_TOM_READING), delay=1.0)
    with make_client(slow, max_concurrent_checks=2, check_wait_seconds=0.2) as client:

        async def three_at_once() -> list[int]:
            return await asyncio.gather(*(asyncio.to_thread(check, client) for _ in range(3)))

        statuses = sorted(asyncio.run(three_at_once()))

    assert statuses == [200, 200, 503]


def test_a_post_from_another_site_is_refused() -> None:
    with make_client() as client:
        assert check(client, origin="https://evil.example") == 403
        assert check(client, **{"sec-fetch-site": "cross-site"}) == 403
        assert check(client, origin="https://testserver") == 200
        assert check(client) == 200  # tools that send no Origin can't be cross-site requests

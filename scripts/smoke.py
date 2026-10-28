"""Checks the live site end to end.

    python -m scripts.smoke                 # https://cola-label-verifier.fly.dev
    python -m scripts.smoke --url https://...

Without an access code it checks only what anyone can see: the health check, that the page is
locked, the security headers and the static files. With SMOKE_ACCESS_CODE (from the environment
or .env) it also signs in through the link and checks the OLD TOM sample, which costs one AI
reading (about $0.006). The code is never printed.
"""

import argparse
import os
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

import httpx2
from dotenv import dotenv_values

from app.web.forms import form_values
from app.web.samples import find_sample

DEFAULT_URL = "https://cola-label-verifier.fly.dev"
SAMPLE = "old-tom"
MAX_SECONDS = 10.0
SECURITY_HEADERS = (
    "content-security-policy",
    "strict-transport-security",
    "x-content-type-options",
    "cache-control",
    "x-request-id",
)
_UNSET = object()


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str = ""


def access_code() -> str | None:
    """The access code for the live site, from the environment or .env, if there is one."""
    return os.environ.get("SMOKE_ACCESS_CODE") or dotenv_values(".env").get("SMOKE_ACCESS_CODE")


def run_checks(client: httpx2.Client, code: str | None) -> list[Result]:
    results = []
    health = client.get("/healthz")
    results.append(
        Result("health check answers", health.status_code == 200, f"HTTP {health.status_code}")
    )
    locked = client.get("/")
    results.append(
        Result(
            "page is locked without the code",
            locked.status_code == 403,
            f"HTTP {locked.status_code}",
        )
    )
    missing = [name for name in SECURITY_HEADERS if name not in locked.headers]
    results.append(
        Result(
            "security headers are present",
            not missing,
            f"missing: {', '.join(missing)}" if missing else "",
        )
    )
    static = client.get("/static/app.css")
    results.append(Result("static files are served", static.status_code == 200))
    if code is None:
        return results

    entry = client.get("/", params={"key": code}, follow_redirects=False)
    cookie = entry.headers.get("set-cookie", "").lower()
    signed_in = (
        entry.status_code == 303
        and "key=" not in entry.headers.get("location", "")
        and all(flag in cookie for flag in ("httponly", "secure", "samesite=strict"))
    )
    results.append(
        Result(
            "the link signs in and leaves the address bar", signed_in, f"HTTP {entry.status_code}"
        )
    )
    page = client.get("/")
    results.append(
        Result(
            "the page opens with the cookie", page.status_code == 200, f"HTTP {page.status_code}"
        )
    )

    sample = find_sample(SAMPLE)
    if sample is None:
        return [*results, Result(f"the {SAMPLE} sample exists", False)]
    started = time.perf_counter()
    checked = client.post("/check", data={**form_values(sample.application), "sample": SAMPLE})
    seconds = time.perf_counter() - started
    found = re.search(r'class="verdict-words">([^<]+)<', checked.text)
    verdict = found.group(1).strip() if found else f"no verdict (HTTP {checked.status_code})"
    timing = checked.headers.get("server-timing", "no Server-Timing")
    results.append(
        Result(
            f"the {SAMPLE} sample matches within {MAX_SECONDS:.0f} s",
            verdict == "Matches" and seconds <= MAX_SECONDS,
            f"{verdict} in {seconds:.1f} s ({timing})",
        )
    )
    return results


def main(
    argv: Sequence[str] | None = None,
    *,
    client: httpx2.Client | None = None,
    code: object = _UNSET,
) -> int:
    parser = argparse.ArgumentParser(description="Check the live site end to end.")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)
    found = access_code() if code is _UNSET else code
    secret = found if isinstance(found, str) and found else None

    own_client = client is None
    http = client or httpx2.Client(base_url=args.url, timeout=60)
    try:
        results = run_checks(http, secret)
    finally:
        if own_client:
            http.close()

    print(f"Smoke test of {args.url}")
    for result in results:
        mark = "PASS" if result.ok else "FAIL"
        print(f"  {mark}  {result.name}" + (f"  ({result.detail})" if result.detail else ""))
    if secret is None:
        print("  skipped: signing in and checking a sample (no SMOKE_ACCESS_CODE)")
    failed = [result for result in results if not result.ok]
    print("All checks passed." if not failed else f"{len(failed)} check(s) failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

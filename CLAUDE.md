# Working notes for Claude Code

This file carries the project context between machines. Claude Code reads it automatically, and
the README explains the project itself. To resume, open the repo in Claude Code and say "resume
from CLAUDE.md".

## Where things stand (end of M4, 2026-10-28)

- M0 to M4 are done: the skeleton, the checking engine, the test data, the label readers and
  the single-label page. 1,039 tests pass, browser tests included. The README is current.
- **M5 in progress (2026-10-28): the demo runs on Fly.io**, at https://cola-label-verifier.fly.dev
  (the user's `personal` org; app `cola-label-verifier`, one `shared-cpu-1x` machine with 512 MB
  in `iad`, which suspends when idle). CI deploys from main after the tests and container checks
  pass, using the GitHub secret `FLY_API_TOKEN` (a deploy token, 90 days, made 2026-10-28). The
  Fly secrets are `LLM_API_KEY` (OpenAI) and `ACCESS_CODE_SHA256`; `REQUIRE_ACCESS_CODE=true`
  keeps the app from starting without the hash. `fly deploy` creates 2 machines by default;
  it was scaled to 1 (`fly scale count 1`), because the rate limits live in memory.
  - Why Fly: Render's free 0.1 CPU took 16 to 23 s per OCR pass (measured under
    `docker --cpus=0.1`); AI-only mode to avoid OCR gave 3 false Matches (warning-typo,
    injection-header-bold-claim, NUMA); the user preferred Fly to Render Starter on price.
    Hugging Face's free tier looked generous but 2026 reports say Docker Spaces need a paid plan.
  - Still to do: run `python -m scripts.smoke` signed in (`SMOKE_ACCESS_CODE` in `.env` must be
    the code, not the hash), measure the 11 samples live (p50/p95, OCR time, wake from
    suspend), and finish the README's M5 numbers.
- Checked live on 2026-10-28 through the page, with OpenAI and Tesseract: OLD TOM matched in 2.6 s
  with every field outlined in the right place; Belle Isle came out Needs review in 3.6 s.
- Live URL: <https://cola-label-verifier.fly.dev> (locked; the code is in the submission link).
- **M4 test list approved on 2026-10-28.** The page uses a plain form post, a server-rendered
  results page and one small self-hosted script (no HTMX; the instructions allow any stack).
  Playwright and axe run in Chromium, downloaded to `.venv/ms-playwright` (set
  `PLAYWRIGHT_BROWSERS_PATH`). About 10 curated samples ship in `app/samples`. Limits per IP:
  10 checks a minute and 200 a day, at most 2 checks at once, and a 30 MB request cap. Large images
  are scaled to 4,000 px. Uploads stay in memory (Starlette's 1 MB spool is raised to 10 MB).
  POSTs from other origins are refused.
  - **Access code (the user's idea):** `ACCESS_CODE_SHA256` holds only the hash. The submission
    link carries `?key=<code>` once; the server sets an `HttpOnly`/`Secure`/`SameSite=Strict`
    cookie and redirects without the query. `/healthz` and `/static` stay open; query strings
    are kept out of the logs; wrong codes count against the rate limit; with no hash set, the
    site is open. `python -m scripts.access_code` makes a code and its hash.
  - New dependencies: Jinja2 and python-multipart (runtime); Playwright and
    axe-playwright-python (dev).
- **Provider changed on 2026-10-28: OpenAI `gpt-5.4-mini` reads the labels** (reasoning effort
  "low", deadlines 15 s for the first token and 25 s in all, the split reader on). The user added
  an OpenAI key after Kimi proved too slow and unreliable: queue stalls on a quarter to half of
  calls, and `kimi-k3.1-pro-highspeed` returned 429 for hours. Kimi still works by configuration
  (`.env.example` shows how). In the user's `.env`, the OpenAI key was first added as
  `LLM_API_KEY_1`; the app reads `LLM_API_KEY`.
- **Model check on 2026-10-28:** `gpt-5.6-luna` ($0.20/$1.20 per 1M, against mini's $0.75/$4.50)
  was twice as slow (p50 4.1 s, p95 11.6 s) and slightly less accurate (39 of 58 correct against
  41; it misread the `wine` class/type) than `gpt-5.4-mini`, so mini stays. There's no
  `gpt-5.5-mini`; `gpt-5.5` costs about 6.7 times as much as mini. The user has $30 of OpenAI
  credit with auto-reload off, which caps spending.
- **Evaluation (gpt-5.4-mini with Tesseract, 58 labels):** no false Matches, 71% correct, every
  drawn label right, 4 of 19 real labels right (most real-label reviews are OCR failing to
  confirm), p50 2.2 s and p95 5.4 s. Rerun with `python -m scripts.eval`.
- **Decided during M3 (see the README's Design decisions):**
  - The AI never sees the application. It reports the most prominent name as `brand`, plus the
    other names and every name-and-address statement. Code (`candidates.py`) picks the
    bottler, fanciful name and class/type. A brand found only among the other names goes to
    review, never passes (the gate caught `sticker-over-brand`).
  - Bold problems go to review, not fail: the AI was wrong on 8 of 18 approved labels.
  - PDF uploads are rendered with pypdfium2; HEIC isn't decoded (iPhones send JPEG).
- **Not done from the M3 plan, by the user's call to keep it simple:** the RapidOCR comparison and
  the pixel bold check (both listed as limitations in the README). OCR timing under
  `docker --cpus=0.1` moves to M5.
- The Mac has Tesseract 5.5.3 (Homebrew) and Docker; the `.venv` is set up.

## How we work (the user's preferences)

- **The user steers design.** Raise real choices as questions with a recommendation, and don't
  re-litigate settled decisions.
- **Test-driven, with approval.** Each milestone starts with a plain-English test list, and
  nothing is implemented until the user approves it. Then go red, green, refactor without
  stopping. Commit failing tests as `test:` and implementations as `feat:` (or `fix:`), and push
  to `main` on GitHub (`achen352/treasury-take-home`). That's authorized.
- **Keep the README current every milestone:** the requirement table, design decisions and the
  test-case list at the bottom. Keep prompt injection to a bullet or two under Security.
- **Security first** (the user is a cybersecurity major, and the audience is federal), but keep
  it proportionate.
- **Cost-conscious.** No paid services beyond the AI reader. The user's OpenAI key pays for it
  (Kimi credits before), and a small Fly.io machine hosts the demo (a few dollars a month at
  most). Keep evaluation runs deliberate.
- **Keep it proportionate.** It's a take-home: when tuning starts to sprawl, the user prefers a
  simple choice plus an honest README limitation over more experiments.
- **Python lives only in the project `.venv`.** Use pip with pip-tools hash-locked files; no
  `uv`, no `--user`, no global installs. Ask before installing anything system-wide.
- **Don't read or borrow from other applicants' public submissions** for this take-home.
- **Non-ASCII in source.** Never type `\uXXXX`, because the file tools decode it into a literal
  and possibly invisible character. Use `\N{NAME}` for confusable or invisible characters.
  Visible Chinese, Japanese or Korean literals are fine. After writing Unicode test data, scan the
  file for unintended characters.
- **Explain any new tool or service before adding it.** The user hadn't heard of Dependabot when
  they found it.

## Decisions to keep (details in the README's Design decisions)

- **The AI only transcribes and code decides.** Results are Matches, Needs review or Does not
  match, and the tool never approves.
- **Two readers.** The vision model reads; Tesseract OCR confirms one-way (disagreement → Review
  only). If the model is unreachable, OCR alone reads and the report is flagged offline (never
  Matches).
- **Several images per application** (front, back, neck). Readings are merged, and a field that
  differs between images goes to Review.
- **Provider: OpenAI `gpt-5.4-mini`** since 2026-10-28; it was Kimi before that. The README lists two
  cost-driven limitations: OpenAI's commercial API, which isn't FedRAMP, reads the uploads, so
  only public or test labels should be uploaded; and a small Fly.io machine is used instead of
  Azure. The agency path is Azure OpenAI or OCR-only mode.
- **Warning:** exact words; header in capitals; spacing, line-break hyphens and body case
  ignored; "(I)" read as "(1)"; punctuation-only differences → Review. Bold problems → Review
  (since 2026-10-28).
- **Other scripts:** a name in a different script from the application → Review; a name printed
  in both scripts is compared in the application's script.

## M3 (done)

What was built is in the README: the M3 test list, How well it reads, and Design decisions.
The readers live in `app/readers/` (`uploads.py`, `ai.py`, `ocr.py`, `dual.py`); M4's page calls
`dual.check_label(images, application, settings, extractor=...)` after `uploads.prepare_uploads`.
Results carry `Location` boxes from OCR for the outlines M4 draws.

## Later milestones

- **M4, the single-label page:** done; see the README's M4 test list.
- **M5, the demo deploy:** on Fly.io; see "Where things stand". Keep-warm isn't needed (the
  machine suspends and wakes on the next visit).
- **M6, batch:**
  - a CSV plus multiple images, about 8 in parallel, with a cap of 300
  - failures listed first
  - CSV export that neutralizes formula injection (`= + - @`, tab, CR)
  - random, unguessable job IDs that expire after an hour
- **M7:** finish the README with the evaluation table, tools, trade-offs and data handling.
- **Stretch:**
  - Azure App Service
  - a "please retake" check for blur and glare
  - estimating warning type size from the physical label size COLA records

## Open items with the user

- **Spot-check: done.** The user confirmed FLOS (missing words) and Ohanyan (no comma).
  Switchback's header is clearly bold, so it now expects "Matches". Bold detection in heavy
  condensed typefaces stays a known hard case for M3's readers.
- **Usage limit.** Set a monthly budget limit in the OpenAI dashboard before the demo goes live.
- **CLAUDE.md before submission.** Decide whether this file stays in the public repo.

## Setting up on a Mac

```bash
git clone https://github.com/achen352/treasury-take-home.git cola-label-verifier
cd cola-label-verifier
brew install python@3.13 tesseract          # tesseract is needed from M3
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/pre-commit install                # gitleaks + ruff on every commit
cp .env.example .env                        # then add LLM_API_KEY (Kimi); never commit it
.venv/bin/python -m pytest
```

Docker Desktop for Mac can also build the image locally. On the Windows machine it conflicts
with Valorant's anti-cheat.

## Gotchas learned the hard way

- **Test labels must regenerate identically on every OS.** The generator pins Pillow's basic
  text layout, because Linux builds default to Raqm. A test compares the committed fixtures with
  a fresh run.
- **CI logs need a GitHub login.** CI turns failed test names into annotations, which the public
  API serves: `/repos/achen352/treasury-take-home/check-runs/<job id>/annotations`.
- **The COLA registry:**
  - it serves label images only within the session that opened the form, so keep the cookie
  - search origin codes: Japan `59`, South Korea `5D`, China `96`, Ukraine `6N`
  - fetch one request every two seconds
- **The pre-commit hook may reformat files and abort the commit.** Re-stage and commit again.
- **Check CI after every push** (`gh run list --limit 4`). A Linux-only failure went unnoticed
  for two pushes. Reproduce Linux locally with
  `docker run --rm -v "$PWD":/repo:ro python:3.13-slim sh -c "pip install -q --require-hashes
  --no-deps -r /repo/requirements-dev.txt && cd /repo && python -m pytest -q -p no:cacheprovider"`.
- **Generated files differ by OS.** Pillow's Linux wheel bundles a different zlib, so the same PNG
  compresses to different bytes; compare PNGs by content. `zipfile` records the OS unless
  `create_system` is set. Regenerating synthetic labels on the Mac rewrites three background-photo
  JPEGs (a different encoder); restore them with `git checkout` unless they were meant to change.
- **Tesseract:** page mode 3 keeps a paragraph's lines in order (mode 11 interleaves columns).
  It reads PNG from stdin 4.5 times faster than PPM. Tilted photos give no text at all, and real
  COLA scans come back with misreads ("érink", "durng"), so the word-for-word warning cross-check
  sends those to review.
- **Lock files on the Mac.** `pip-tools` isn't in the lock files; install it into the `.venv`
  (`.venv/bin/python -m pip install pip-tools`). Compiling on macOS drops `colorama`, a
  Windows-only dependency of pytest and bandit, so put its pinned, hashed entry back (copy it
  from git) or the Windows machine's `--require-hashes` install breaks. In zsh, pass
  `--extra dev` as written, not through a `${var:+...}` expansion.
- **Ruff S105 and Bandit B105 flag names such as `PASS` and `token`** as possible passwords.
  Rename the variable or add a commented suppression.
- **Read files with `encoding="utf-8"`.** Windows' default code page breaks on non-ASCII
  fixtures.
- **Kimi latency (measured 2026-10-27 from the Mac, about 45 calls).**
  - With thinking on, `kimi-k2.6` takes 68 to 72 s (about 2,500 reasoning tokens). Always send
    thinking off.
  - With thinking off at 1100 px, a call takes 4.6 to 6.0 s: about 0.7 s network (the servers
    are behind Cloudflare, far away), about 1.6 to 2 s reading the image, and about 2.7 s
    writing about 150 tokens at about 55 tokens/s. Full size (1600×2000) takes 6.7 to 7.9 s;
    640 px takes about 4.7 s. JPEG and PNG are the same.
  - About 1 call in 4 stalled for 9 to 16 s before its first token. Concurrent calls stall
    together, so a backup ("hedged") request doesn't help. No rate-limit headers; the account
    is paid.
  - The `k3` models can't turn thinking off (low effort still reasons 180 to 300 tokens):
    `kimi-k3` 8 to 10 s, `kimi-k3.1-pro-highspeed` 5.6 s. `k2.7-code-highspeed` only allows
    thinking on.
  - A bare prompt once dropped "GOVERNMENT WARNING:" from the warning and "Distilled and
    bottled by" from the bottler; an explicit prompt fixed both.
  - Tesseract reads the OLD TOM label in 0.44 s of CPU on the Mac. Under `docker --cpus=0.1` one
    pass took 16 to 23 s (worse than linear); at 0.5 CPU, 1.1 to 1.9 s; at 1 CPU, about 0.8 s.

# Working notes for Claude Code

This file carries the project context between sessions and machines. Claude Code reads it
automatically, and the README explains the project itself. To resume, open the repo in Claude Code
and say "resume from CLAUDE.md".

## Where things stand (end of M7, 2026-10-28)

- **All milestones are done**: M0 skeleton, CI and security scans; M1 checking engine; M2 test
  data; M3 label readers; M4 single-label page; M5 deploy; M6 batch; M7 final README. Each
  milestone's approved test list is at the bottom of the README.
- **Live:** <https://cola-label-verifier.fly.dev>, locked by an access code that's in the
  submission link. Fly.io app `cola-label-verifier` in the user's `personal` org: one
  `shared-cpu-1x` machine with 1 GB in `iad`, suspended when idle.
  - CI deploys from main after the tests and container checks pass, using the GitHub secret
    `FLY_API_TOKEN` (a deploy token, 90 days, made 2026-10-28).
  - Fly secrets: `LLM_API_KEY` (OpenAI) and `ACCESS_CODE_SHA256`. `REQUIRE_ACCESS_CODE=true`
    keeps the app from starting without the hash. The user keeps the code itself in `.env` as
    `SMOKE_ACCESS_CODE`; `python -m scripts.smoke` signs in with it.
  - Keep one machine (`fly scale count 1`): the rate limits (30 a minute, 500 a day) live in
    memory, and `fly deploy` would otherwise create two.
  - Measured live: median 3.3 s over the 11 samples. A 22-label batch took 131 s with no errors;
    after about 15 labels in a row the shared CPU throttles and OCR takes 15 to 26 s. The user
    chose to document that rather than pay for more CPU. 512 MB was killed for lack of memory
    with two large labels at once, hence 1 GB.
- **Reader:** OpenAI `gpt-5.4-mini`, reasoning effort low, the warning read in its own call,
  deadlines of 15 s to the first token and 25 s in all. Tesseract cross-checks. Kimi still works
  by configuration (`.env.example`).
- **Evaluation:** `python -m scripts.eval --split` matches the live setup (the script's default
  reads the warning in the same call); `--mode ocr` is the offline mode. Results are in the
  README's "How well it reads". Keep runs deliberate: one full run costs about $0.35.
  - Final run: no false Matches in either mode, 69% correct with the AI. 10 of the 15 approved
    real labels that should match came out Does not match, because the AI read a different line
    as the class/type or brand ("Junmai" for "Sake", "100% Estate Chardonnay" for "Estate
    Chardonnay"). Readings vary between runs; the README says so.

## Open items

- **OpenAI budget.** The user should set a monthly budget limit in the OpenAI dashboard.
- **Ideas beyond the brief:** Azure App Service; a "please retake" check for blur and glare;
  warning type size from the physical label size COLA records; RapidOCR and a pixel-based bold
  check (both dropped to keep the scope proportionate, listed as README limitations).

## How we work (the user's preferences)

- **The user steers design.** Raise real choices as questions with a recommendation, and don't
  re-litigate settled decisions.
- **Test-driven, with approval.** Each milestone starts with a plain-English test list, and
  nothing is implemented until the user approves it. Then go red, green, refactor without
  stopping. Commit failing tests as `test:` and implementations as `feat:` (or `fix:`), and push
  to `main` on GitHub (`achen352/treasury-take-home`). That's authorized.
- **Keep the README current:** the requirement table, design decisions, limitations and the
  test-case list at the bottom. A test checks its sections and links.
- **Security first** (the audience is federal), but keep it proportionate.
- **Cost-conscious.** No paid services beyond the AI reader and a small Fly.io machine.
- **Keep it proportionate.** It's a take-home: when tuning starts to sprawl, the user prefers a
  simple choice plus an honest README limitation over more experiments.
- **Python lives only in the project `.venv`.** Use pip with pip-tools hash-locked files; no
  `uv`, no `--user`, no global installs. Ask before installing anything system-wide.
- **Don't read or borrow from other applicants' public submissions** for this take-home.
- **Non-ASCII in source.** Never type `\uXXXX`, because the file tools decode it into a literal
  and possibly invisible character. Use `\N{NAME}` for confusable or invisible characters.
  Visible Chinese, Japanese or Korean literals are fine. After writing Unicode test data, scan the
  file for unintended characters.
- **Explain any new tool or service before adding it.**
- **Never print or commit secrets.** `.env` is gitignored; pass keys through pipes, not commands.

## Decisions to keep (details in the README's Design decisions)

- **The AI only transcribes and code decides.** Results are Matches, Needs review or Does not
  match, and the tool never approves.
- **The AI never sees the application.** It reports the most prominent name as the brand, plus
  the other names and statements; `candidates.py` picks the bottler, fanciful name and class/type.
  A brand found only among the other names goes to review.
- **Two readers, one-way.** OCR disagreement only sends a field to review. If the AI is
  unreachable, OCR alone reads and the report is flagged offline (never Matches).
- **Several images per application.** Readings are merged, and a field that differs between
  images goes to review.
- **Warning:** exact words; header in capitals; spacing, line-break hyphens and body case
  ignored; "(I)" read as "(1)"; punctuation-only differences and bold problems go to review.
- **Other scripts:** a name in a different script from the application goes to review; a name
  printed in both scripts is compared in the application's script.
- **Batches run in the browser**, one label per request, so the server keeps nothing.
- **Cost-driven limitations, stated in the README:** OpenAI's commercial API (not FedRAMP) reads
  the uploads, so only public or test labels; a Fly.io machine instead of Azure. The agency path
  is Azure OpenAI or OCR-only mode.

## Setting up on a Mac

```bash
git clone https://github.com/achen352/treasury-take-home.git cola-label-verifier
cd cola-label-verifier
brew install python@3.13 tesseract
python3.13 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/pre-commit install                # gitleaks + ruff on every commit
cp .env.example .env                        # then add LLM_API_KEY (OpenAI); never commit it
PLAYWRIGHT_BROWSERS_PATH=.venv/ms-playwright .venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest
```

## Gotchas learned the hard way

- **Check CI after every push** (`gh run list --limit 4`). A Linux-only failure once went
  unnoticed for two pushes. Reproduce Linux locally with
  `docker run --rm -v "$PWD":/repo:ro python:3.13-slim sh -c "pip install -q --require-hashes
  --no-deps -r /repo/requirements-dev.txt && cd /repo && python -m pytest -q -p no:cacheprovider"`.
- **CI logs need a GitHub login.** CI turns failed test names into annotations, which the public
  API serves: `/repos/achen352/treasury-take-home/check-runs/<job id>/annotations`.
- **Generated files differ by OS.** The label generator pins Pillow's basic text layout, because
  Linux builds default to Raqm. Pillow's Linux wheel bundles a different zlib, so compare PNGs by
  content, not bytes. `zipfile` records the OS unless `create_system` is set. Regenerating
  synthetic labels on the Mac rewrites three background-photo JPEGs; restore them with
  `git checkout` unless they were meant to change.
- **Lock files on the Mac.** Install `pip-tools` into the `.venv`. Compiling on macOS drops
  `colorama`, a Windows-only dependency of pytest and bandit, so put its pinned, hashed entry back
  (copy it from git) or a Windows `--require-hashes` install breaks.
- **The pre-commit hook may reformat files and abort the commit.** Re-stage and commit again.
- **Ruff S105 and Bandit B105 flag names such as `PASS` and `token`** as possible passwords.
  Rename the variable or add a commented suppression.
- **Read files with `encoding="utf-8"`.** Windows' default code page breaks on non-ASCII
  fixtures.
- **Tesseract:** page mode 3 keeps a paragraph's lines in order (mode 11 interleaves columns).
  It reads PNG from stdin 4.5 times faster than PPM. Tilted photos give no text at all, and real
  COLA scans come back with misreads, so the word-for-word warning cross-check sends those to
  review. One OCR pass took 16 to 23 s at 0.1 CPU (`docker --cpus=0.1`), about 1 s at 1 CPU.
- **The COLA registry** serves label images only within the session that opened the form, so
  keep the cookie. Search origin codes: Japan `59`, South Korea `5D`, China `96`, Ukraine `6N`.
  Fetch one request every two seconds.
- **Kimi (measured 2026-10-27):** always send thinking off (on, `kimi-k2.6` takes about 70 s).
  With it off, a call took 4.6 to 6.0 s, and about 1 in 4 stalled 9 to 16 s before the first
  token; concurrent calls stall together, so hedged requests don't help. The `k3` models can't
  turn thinking off. That's why the demo moved to OpenAI.
- **Starlette spools uploads over 1 MB to disk** unless `MultiPartParser.spool_max_size` is
  raised; the app raises it to the 10 MB file cap so nothing touches disk.
- **Browsers send `Origin: null`** on the page's own form posts under `Referrer-Policy:
  no-referrer`; the cross-site check relies on `Sec-Fetch-Site` instead.

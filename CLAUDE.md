# Working notes for Claude Code

This file carries the project context between machines. Claude Code reads it automatically, and
the README explains the project itself. To resume, open the repo in Claude Code and say "resume
from CLAUDE.md".

## Where things stand (end of M2, 2026-10-27)

- M0 (skeleton, CI, security scans, container, Render deploy), M1 (checking engine) and M2 (test
  data, real-label fixes, other scripts) are done. 693 tests pass, and CI and the Security
  workflow are green.
- Fixtures: 39 synthetic labels, 19 real COLA labels and 12 hostile files.
- Live URL: <https://treasury-take-home-1uz2.onrender.com> (only `/healthz`).
- **Next: M3, the label readers.** The decisions below were agreed on 2026-10-27, after measuring
  Kimi's latency. Next step: the user approves the M3 test list, then red, green, refactor.
- The Mac now has Tesseract 5.5.3 (Homebrew) and Docker; the `.venv` is set up and `.env` holds
  the Kimi key.

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
- **Cost-conscious.** No paid services. Kimi credits pay for the AI reader, and Render's free
  tier hosts the demo.
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
- **Provider: Kimi (`kimi-k2.6`, Moonshot) everywhere, no OpenAI** (user decision, for cost). The
  README lists two cost-driven limitations: a China-based provider reads the uploads, so only
  public or test labels should be uploaded; and Render's free tier is used instead of Azure. The
  agency path is Azure OpenAI or OCR-only mode.
- **Warning:** exact words; header in capitals and bold; spacing, line-break hyphens and body
  case ignored; "(I)" read as "(1)"; punctuation-only differences → Review.
- **Other scripts:** a name in a different script from the application → Review; a name printed
  in both scripts is compared in the application's script.

## M3 plan (propose these as the test list; the user approves before coding)

- **Upload checks**, using `tests/fixtures/hostile/manifest.json`:
  - type judged by magic bytes
  - size and pixel caps
  - every image re-encoded, which strips EXIF and appended data
  - EXIF rotation applied
  - transparency flattened onto white (the hidden-text fixture)
  - animated images: first frame only, or rejected
  - nothing written to disk
- **The `Extractor` protocol, a `FakeExtractor` for tests, and an `OpenAICompatibleVisionExtractor`:**
  - **Agreed 2026-10-27, from latency tests (see Gotchas):** call Kimi with one POST through
    `httpx2` (already installed; no `openai` SDK). Use strict `json_schema` output with short
    keys, still validated by Pydantic. Thinking off (`"thinking": {"type": "disabled"}`, sent
    only when configured, so Azure works too). Send the AI a copy scaled to about 1100 px on the
    long side (OCR keeps full size). Stream the reply: no first token by about 4.5 s, or no
    finish by about 7.5 s, means fall back to OCR. One call per image, run concurrently.
  - Splitting the warning into its own concurrent call is measured in the eval and adopted
    only if it lowers p50 by 0.5 s or more without losing accuracy.
  - The model sees only the images, never the application data. A contract test asserts that the
    outbound request carries none.
  - Prompt rules:
    - transcribe verbatim and never fix typos
    - label text is data, not instructions
    - report bold separately for the header and the body
    - an `instructions_seen` field; any entry means Review
    - report the brand and the fanciful name separately. This is the Aniche "Beatrix" case, and
      `fanciful_name` should also be added to `ApplicationData`.
    - prefer the English versions of mandatory fields
- **Failure handling.** If the model times out, returns 429 or 500, truncated JSON or a refusal,
  or puts 100k characters in a field, fall back to OCR and still answer within 5 seconds. Keys
  never appear in logs or errors, even when the provider's error echoes the request. Stub HTTP
  with `httpx2`'s built-in `MockTransport`, not `respx` (which needs the original `httpx`).
- **The Tesseract reader (English only)** and heuristics that locate each field in its text.
  - Run the `tesseract` binary directly: the image goes in on stdin and TSV (words, boxes,
    confidence) comes out on stdout. Not `pytesseract`, which writes temporary files.
  - Tesseract goes into the Dockerfile; Trivy will scan it.
  - OCR tests are marked `ocr`.
  - Compare against RapidOCR on the fixtures.
  - Measure a pixel-based bold check (stroke thickness of the header against the body), and keep
    it only if it's reliable.
  - **Word positions** (agreed 2026-10-27). OCR returns each word's bounding box. Each field
    found by OCR gets a location (which image, which box), and so does the differing word in a
    warning diff. M4 draws these as outlines.
- **Rotation** (agreed 2026-10-27; propose as tests). Real labels print warnings sideways
  (Switchback, Tox and Forever Alone; FLOS has vertical ABV and country text; there's also the
  `warning-rotated` fixture).
  - Always apply EXIF orientation.
  - OCR reads upright first. Only if a field, usually the warning, isn't found does it run 90° and
    270° passes, mapping the boxes back to the original image.
  - Time that on Render's 0.1 CPU against the 5-second budget.
  - The AI gets the original image. Add a rotated crop of the warning region only if the eval
    shows sideways warnings being misread.
  - Tag fixtures with sideways text (`rotated`) so the eval reports them separately.
- **The dual reader and merging images:** run the model and OCR concurrently; the offline mode
  is described under Decisions.
- **`scripts/eval.py`** runs the readers over the synthetic and COLA fixtures. It reports
  per-field accuracy, overall accuracy, false-Matches rate, false-Review rate and p50/p95 latency,
  broken down by tag (`adversarial`, `hard-to-read`, `cola`, `other-script`, `deviation`). Gate:
  no "Matches" on any fixture whose acceptable results exclude it.

## Later milestones

- **M4, the single-label page:**
  - upload several images, an application form, and a "Sample labels" picker
  - results shown with an icon and words, never color alone
  - each field outlined on the label image, marked with an icon and its name (not color alone),
    and the differing word in the warning outlined. Clicking a result zooms to its spot, and the
    zoom turns sideways text upright. Rotate buttons on each image. A field OCR couldn't find
    says so instead of showing an outline.
  - the diff and both readings when they disagree
  - text at 18px or larger, `dir="auto"` for right-to-left scripts, an offline banner
  - a notice that images go to Kimi (Moonshot), so upload only public or test labels
  - an axe accessibility scan
  - web tests: `<script>`, `{{ 7*7 }}`, RTL characters, `../` filenames, empty, truncated and
    50 MB files, JSON instead of a form, rate limiting
- **M5, the demo deploy:**
  - Kimi on Render; `render.yaml` already sets the URL and model, and the key goes in Render's
    dashboard
  - protect the personal credits with per-IP rate limits and an optional `ACCESS_CODE`
  - keep-warm cron every 10 minutes; a smoke test of the live URL; latency from Render to
    Moonshot against 5 seconds
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
- **Usage limit.** Set one in the Moonshot console, if it offers one.
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
  - Tesseract reads the OLD TOM label in 0.44 s of CPU here, so roughly 4 s on Render's 0.1 CPU.

# COLA Label Verifier

A prototype that helps TTB label specialists check alcohol label artwork against the application
it was submitted with. It answers the take-home exercise in
[treasurytakehome-rgb/instructions](https://github.com/treasurytakehome-rgb/instructions).

> **Status: work in progress.** The checking engine and the test data are built and tested. The
> label readers, the web page, batch upload and the final deployment are next (see
> [Progress](#progress)). Live URL: <https://treasury-take-home-1uz2.onrender.com> (only
> `/healthz` responds so far).

## The brief, and how this project answers it

Each row is a requirement from the brief, with the stakeholder who raised it.

| The brief asks for | How this prototype answers | Status |
|---|---|---|
| Check that the label matches the application: brand, class/type, alcohol content, net contents, bottler, country of origin, government warning (*Technical requirements; Sarah Chen*) | A rules engine checks each field and cites the regulation it applies (27 CFR parts 4, 5, 7 and 16). | Built |
| The warning must be word for word, with "GOVERNMENT WARNING:" in capitals and bold (*Jenny Park*) | Exact wording, a capitalized header and bold type are all enforced. Jenny's title-case example is one of the tests. | Built |
| "STONE'S THROW" vs "Stone's Throw" needs judgment (*Dave Morrison*) | Three outcomes: **Matches**, **Needs review**, **Does not match**. Cosmetic differences pass with a note, and near misses go to a person. The tool never approves a label. | Built |
| Results in about 5 seconds, because the last vendor took 30 to 40 (*Sarah Chen*) | The AI model makes one call to read the label, and the checks themselves are plain code that runs in milliseconds. Latency is measured against 5 seconds. | Planned (M3, M5) |
| Simple enough for agents over 50: "clean, obvious, no hunting for buttons" (*Sarah Chen*) | One page with one main button and large text. Results are shown with an icon and words, never color alone, and an automated accessibility scan checks the page (Section 508). | Planned (M4) |
| Batch uploads of 200 to 300 labels at once (*Sarah Chen, for Janet*) | A batch upload takes a spreadsheet of application data, and failures are listed first. | Planned (M6) |
| The agency runs on Azure under FedRAMP (*Marcus Williams*) | Not used here, for cost: the prototype runs on Render's free tier and reads labels with Kimi (see [Limitations](#assumptions-and-limitations)). The Docker image and the AI adapter move to Azure App Service and Azure OpenAI by configuration alone. | Documented path |
| The firewall blocks many outbound ML endpoints (*Marcus Williams*) | A local OCR reader (Tesseract) keeps working when the AI service can't be reached, and the result is marked as read offline. | Planned (M3) |
| A standalone proof of concept, not integrated with COLA (*Marcus Williams*) | Standalone. The public COLA registry is used only offline, as a source of real test labels. | By design |
| Store nothing sensitive (*Marcus Williams*) | No database, images are processed in memory, and logs hold no label content. | By design (enforced as uploads arrive in M3 and M4) |
| Handle labels photographed at angles, in bad light or with glare (*Jenny Park*) | 12 badly photographed test labels. Unreadable fields go to a person instead of being guessed. | Test labels built; readers in M3 |
| Create or source test labels; AI image generation suggested (*Additional context*) | 39 labels drawn by code (three on AI-generated photo backgrounds), 19 real approved labels from the public COLA registry, and 12 hostile files. | Built |
| A repo with a README, and a deployed URL (*Deliverables*) | This repository and the Render URL above. | In progress |

## What COLA is

TTB, Treasury's Alcohol and Tobacco Tax and Trade Bureau, must approve the label of most alcohol
sold in the United States. The approval is a **Certificate of Label Approval (COLA)**. Applicants
file Form 5100.31 through COLAs Online, the system Sarah mentions went online in 2003. An agent
then checks the label artwork against the application, about 150,000 times a year across 47
agents. Approved labels are published in the
[Public COLA Registry](https://ttbonline.gov/colasonline/publicSearchColasBasic.do).

What a label must show depends on the product:

- 27 CFR part 5 covers spirits.
- Part 4 covers wine.
- Part 7 covers malt beverages.
- Part 16 covers the government health warning, which must appear on all of them.

Mandatory information must be in English, except the brand name. For wine, the place of
production and the producer's name are also exempt (27 CFR 5.55, 7.55, 4.38(c)).

The brief says the prototype should stand alone ("we're not looking to integrate with COLA
directly"). The agent supplies the application data and label images, and the app never connects
to COLA. The public registry is used only offline, by a small downloader, to collect real approved
labels as test data.

## How it works

```
label images (front, back, ...) --> upload checks --> AI reader --+
                                                 \--> OCR reader --+--> checking engine
application data ----------------------------------------------------+         |
                                                                               v
                                         Matches / Needs review / Does not match, with evidence
```

- **The readers only transcribe.** The checking engine, plain Python, decides. Each field gets
  Pass, Review or Fail, with the text found, the text expected, a plain-language note and its CFR
  section.
- **Overall result.** Any Fail means "Does not match". Otherwise, any Review means "Needs review".
  Otherwise the result is "Matches".
- **The OCR reader can only move a field toward a person.** If it can't confirm what the AI read,
  the field goes to review. It can never turn a review or a fail into a pass.

## Design decisions

These are the decisions that shape the project, and why each was made. This section is updated
as the work goes on.

| Decision | Why |
|---|---|
| **The AI only transcribes; code decides.** | Every result is deterministic, explainable and unit-tested. The model can't be lenient, quietly fix a typo in a warning, or be talked into a pass. |
| **Three outcomes, never "approved".** | The routine checks are automated and judgment calls go to the agent, which answers Dave's concern that review needs judgment. |
| **Two independent readers, one-way.** | A vision model reads the label, and Tesseract OCR independently confirms it. With two readers a majority vote can't break a tie, so disagreement only ever sends a field to review. |
| **Several images per application.** | Real COLAs put the brand on the front and the warning on the back, so checking one image would fail the warning on most real labels. |
| **Warning rules settled against real labels.** | Exact wording and header capitals are required. Spacing, hyphens at line breaks and the body's capitalization don't count. A difference in punctuation alone goes to review instead of failing, because 3 of 19 approved labels have one. |
| **Forgiving names, strict judgments.** | Differences in case, punctuation, spacing or common abbreviations ("Co." and "Company") pass with a note, and near misses go to review. A name printed in another script, such as a Hangul brand against a romanized application, goes to review, because 27 CFR 5.55 and 7.55 allow non-English brand names. |
| **Careful numbers.** | A percentage counts as the ABV only when the words around it say alcohol, so "100% Blue Agave" isn't an ABV. Proof must equal twice the ABV. Volumes must match exactly within metric or US units and within 0.5% across them (750 mL = 25.4 fl oz). Pints, quarts and wine ABV ranges are supported. |
| **Kimi reads the labels, through one swappable adapter.** | The vision reader speaks the OpenAI-compatible API, so the provider is configuration, not code. This prototype uses Moonshot AI's Kimi model in development and in the demo, because the author already has credits for it and the exercise has no budget. In an agency, the same adapter would point at Azure OpenAI in Treasury's own tenant. The trade-off is listed under [Limitations](#assumptions-and-limitations). |
| **Render's free tier, with Azure as the path.** | Render gives a live URL at no cost with the least setup. The same Docker image is what Azure App Service would run. |
| **Python, FastAPI, server-rendered pages.** | The pages are plain HTML from the server, made interactive with HTMX, so there is no frontend build. pytest makes test-first work easy, and Python has strong libraries for images and fuzzy matching. |
| **Test-driven, with approved test lists.** | Each milestone starts with a plain-English list of test cases agreed before coding. Commits come in `test:` and `feat:` pairs, so `git log` shows each test failing before the code that makes it pass. |
| **Test labels drawn from their own ground truth.** | Each label is drawn from its truth file, so the right answer is known exactly. AI image generation is used only for photo backgrounds, because AI-generated label text is garbled. Real approved labels come from the public registry. |
| **Import for hard problems, write small rules.** | Well-maintained libraries handle image decoding, OCR, fuzzy matching and the web framework. The label rules are short, readable code. All dependencies are hash-pinned. |

## What real labels taught us

The 19 approved labels in [tests/fixtures/cola](tests/fixtures/cola/README.md) changed the
engine. Given perfect readings of the first 16, the first version of the engine got 8 right. Each
miss led to a fix:

- an ABV printed without a % sign
- proof written as "PROOF 108" or "85.6° US PROOF"
- pints
- warning text run together or hyphenated by tight typesetting
- a "(1)" drawn like "(I)"
- bottler wording in any order
- "Republic of Armenia" as a country name
- ABV ranges such as "14% TO 15%"

Four approved labels differ from the regulation's text, and the tool reports them:

- **FLOS** was approved with "because" and "a" missing from its warning, so the result is **Does
  not match**.
- **NUMA, Ohanyan and Forever Alone** differ only in punctuation, so the result is **Needs
  review**.

## Security

- **Uploads (M3):**
  - file type is judged by content, not by file name
  - size and pixel limits stop decompression bombs
  - every image is re-encoded, which drops metadata and anything appended to the file
  - nothing is written to disk
- **Prompt injection.** Text printed on a label to steer the AI can at most make one reading
  wrong, because the model only transcribes, has no tools, and never decides. The OCR
  cross-check catches a reading that drifts from what's printed. A tripwire, which works in
  several languages, sends any label that addresses an AI to a person. Hidden and look-alike
  characters are stripped or flagged.
- **Web:**
  - a strict Content-Security-Policy
  - HSTS, nosniff and no-store headers, and no framing
  - generic error pages that carry only a request ID
  - API docs switched off
- **Secrets.** `.env` is ignored by git, and `.env.example` documents the variables. gitleaks
  scans every commit and the full history in CI. Keys are never logged.
- **Supply chain:**
  - hash-locked dependencies
  - pip-audit, Bandit and a Trivy image scan
  - a CycloneDX SBOM
  - Dependabot
  - GitHub Actions pinned by commit SHA
- **Container.** A multi-stage build, a base image pinned by digest, a non-root user, and no
  pip in the runtime image.
- **What production would still need:**
  - a FedRAMP-authorized model provider and host (see [Limitations](#assumptions-and-limitations))
  - FedRAMP authorization and an ATO
  - single sign-on
  - an audit log of who checked what
  - records retention
  - a Section 508 audit

## Dependencies

The app imports few libraries, all open source under permissive licenses. Every package,
including the ones these pull in, is pinned to an exact version and checked against a hash on
install. That comes to 18 runtime packages in all.

| Library | Used for | License |
|---|---|---|
| FastAPI, Starlette, Uvicorn | Web framework and server | MIT, BSD-3-Clause, BSD-3-Clause |
| Pydantic, pydantic-settings | Data validation and settings | MIT |
| RapidFuzz | Similarity scores for near-miss names | MIT |
| Pillow | Image decoding and re-encoding, and drawing test labels | MIT-CMU |
| DejaVu fonts (bundled, test labels only) | Drawing test labels identically on every OS | Bitstream Vera (permissive) |

Planned for M3: the `openai` client library and `pytesseract` (both Apache-2.0), plus the
Tesseract OCR engine (Apache-2.0), installed in the container image. Test and lint tools
(pytest, Hypothesis, Ruff, mypy) are development-only and never ship.

Keeping them safe:

- **pip-audit** checks every pinned version against known vulnerabilities, on every push and
  weekly.
- **A CycloneDX SBOM** (software bill of materials) lists every component, which federal buyers
  ask for under Executive Order 14028.
- **Trivy** scans the finished container image.
- **Dependabot**, GitHub's update bot, opens a pull request when a pinned library, the base image
  or a CI action has a newer version. It never changes anything by itself. Each update is
  reviewed, tested by CI and merged by hand.

## Assumptions and limitations

Two limitations come from keeping the prototype free to run. Neither is what an agency
deployment should do:

- **Kimi, a China-based AI provider, reads the labels.** Images uploaded to the demo are sent to
  Moonshot AI's API. Upload only public or test labels, such as the samples in this repository.
  For agency use, point the adapter at a FedRAMP-authorized model, such as Azure OpenAI in
  Treasury's tenant. Alternatively, run the OCR-only mode (`EXTRACTOR_MODE=ocr`), which sends
  nothing outside the server.
- **Render's free tier hosts the demo.** It isn't FedRAMP-authorized or on Azure, where the
  agency runs. It has 0.1 CPU and 512 MB of memory, and it sleeps when idle, so the first request
  after a quiet spell is slow. The same Docker image runs on Azure App Service.

The rest are scope limits:

- **Warning type size isn't measured.** That needs the label's physical size, which COLA records,
  so it's a possible later addition.
- **Puerto Rico's exception isn't handled.** Spirits and malt beverages sold there may carry
  Spanish-only mandatory text (27 CFR 5.55(c), 7.55(c)).
- **Class/type is compared as text.** Standards of identity, such as what qualifies a whiskey as
  "straight bourbon", aren't checked.
- **Wine ABV tolerances (27 CFR 4.36) aren't applied.** The label must state what the application
  states.
- **OCR reads English only.** A value in another script can't be confirmed by OCR, so it goes to
  review.

## Run it

Requires Python 3.13.

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows (Git Bash); use .venv/bin/activate on macOS/Linux
pip install --require-hashes -r requirements-dev.txt
cp .env.example .env              # then fill in your keys; .env is gitignored
pytest                            # run the test suite
python -m app.server              # http://127.0.0.1:8000/healthz
```

Or with Docker:

```bash
docker build -t cola-label-verifier .
docker run --rm -p 8000:8000 --env-file .env cola-label-verifier
```

Test data:

```bash
python -m scripts.generate_labels         # redraw the synthetic labels (deterministic)
python -m scripts.hostile_files           # rewrite the harmless hostile upload files
python -m scripts.fetch_cola <TTB ID>     # fetch an approved label from the public registry
```

Lock files are generated from `pyproject.toml` with hashes:

```bash
pip-compile --strip-extras --generate-hashes --allow-unsafe -o requirements.txt pyproject.toml
pip-compile --strip-extras --generate-hashes --allow-unsafe --extra dev -o requirements-dev.txt pyproject.toml
pip-compile --strip-extras --generate-hashes --allow-unsafe --extra security -o requirements-security.txt pyproject.toml
```

## Project layout

```
app/
  domain/            the checking engine: pure Python, no I/O
    rules/           one module per kind of check (names, alcohol, net contents, warning)
    crosscheck.py    the one-way policy for when the two readers disagree
    injection.py     the tripwire for text addressed to an AI
    verifier.py      runs every rule and combines the results
  web/               routes and security middleware
scripts/             test-label generator, hostile files, COLA downloader, fonts
tests/
  unit/ integration/ security/
  fixtures/          synthetic/, cola/, hostile/, backgrounds/
```

## Progress

| Milestone | Scope | Status |
|---|---|---|
| M0 | Project skeleton, CI and security scans, container, security headers, first deploy | Done |
| M1 | Checking engine: every rule, the cross-check policy and the verifier | Done |
| M2 | Test data: drawn labels, real COLA labels, hostile files; fixes found by real labels; other scripts | Done |
| M3 | Label readers: upload checks, AI reader (Kimi), OCR reader, merging images, evaluation script | Next |
| M4 | Single-label page | |
| M5 | Demo deployment: Kimi on Render, latency check, keep-warm, usage limits | |
| M6 | Batch upload | |
| M7 | Final README: evaluation results, tools, trade-offs | |

## Test cases

693 test cases (228 test functions, many run over several inputs) cover the checking engine, the
test data and the web skeleton. All of them run in CI on every push. Each group below was agreed
in plain English before its code was written.

| Area | File | What it proves |
|---|---|---|
| Configuration | `tests/unit/test_config.py` | Settings load from the environment, keys stay masked, bad values fail fast |
| Web basics | `tests/integration/test_app_basics.py` | Health check, generic errors with request IDs, API docs off |
| Security headers | `tests/security/test_headers.py` | Hardening headers on every response, including errors |
| Server launch | `tests/integration/test_server_launch.py` | No server banner, trusted proxies only, platform port |
| Models | `tests/unit/test_domain_models.py` | A reading can't carry a verdict; unknown fields and long values are rejected |
| Normalization | `tests/unit/test_normalize.py` | Text, ABV and volume parsing, hidden and look-alike characters, scripts |
| Name rules | `tests/unit/test_rules_names.py` | Brand, class/type, bottler, country |
| Number rules | `tests/unit/test_rules_numbers.py` | Alcohol content, proof, net contents |
| Warning rule | `tests/unit/test_rules_warning.py` | Wording, capitals, bold, real-label typesetting |
| Tripwire | `tests/unit/test_injection.py` | AI-addressed text in any disguise or language |
| Cross-check | `tests/unit/test_crosscheck.py` | Disagreement never improves a result |
| Verifier | `tests/unit/test_verifier.py` | The whole report, required fields, fuzzing |
| Test data | `tests/unit/test_label_fixtures.py`, `test_generate_labels.py`, `test_cola_fixtures.py`, `test_hostile_files.py`, `test_fetch_cola.py` | Every fixture agrees with the engine and is what it claims to be |

<details>
<summary><b>M0: skeleton and security baseline</b></summary>

- Settings load from environment variables and from `.env`; the API key never appears when
  settings are printed or serialized; an invalid reader mode fails fast with a clear error;
  defaults are secure (docs off, no key).
- The health check reports ok; unknown routes are a plain 404; an unhandled error returns a
  generic 500 with a request ID and no internals.
- Every response gets a request ID; a safe client-supplied ID is echoed, and an unsafe one is
  replaced.
- API docs are off by default and can be enabled for local development (with a relaxed CSP on
  `/docs` only).
- Every response, errors included, carries a strict CSP, HSTS, nosniff, frame and referrer
  protections, and no-store; the server doesn't advertise itself.
- The real server trusts forwarded headers only from configured proxies and listens on the
  platform's `PORT`.
- CI: the image runs as a non-root user, serves `/healthz` without a Server header, and ships
  without pip.

</details>

<details>
<summary><b>M1: checking engine</b></summary>

**Normalizing text and numbers**

1. Case, quote style, extra spaces and punctuation are ignored: `STONE'S THROW` equals
   `Stone's Throw`.
2. Common abbreviations count as equal: `Co.`/`Company`, `Dist.`/`Distillery`, `&`/`and`.
3. Normalizing twice gives the same result as once (property test).
4. Alcohol formats parse: `45% Alc./Vol.`, `45% ALC/VOL`, `Alc. 45% by Vol.`,
   `ALCOHOL 45% BY VOLUME`, and proof from `(90 Proof)`.
5. Volumes convert to mL (`750 mL`, `75 cL`, `0.75 L`, `1 Liter`, `25.4 fl oz`), and conversions
   round-trip (property test).
6. Unreadable text gives "unknown", never an error.

**Brand and class/type**

7. An exact match passes.
8. Differences only in case or punctuation pass with a note (Dave's example).
9. A near miss (similarity of 90 or more, such as `DISTILLERY` vs `DISTILLERS`) goes to review.
10. Anything else fails, and a missing brand fails.

**Alcohol content**

11. The same value in another format passes; a different value fails.
12. Proof must be twice the ABV: `45% (90 Proof)` passes, `45% (80 Proof)` fails.
13. A spirits label without ABV fails; beer or wine with no ABV on either side passes.
14. Unreadable alcohol text goes to review.

**Net contents**

15. Equal volumes in any unit pass; different volumes fail.
16. Unreadable volumes go to review; a missing volume fails.

**Bottler and country of origin**

17. The bottler check is forgiving: cosmetic differences pass, near misses go to review, and
    unrelated or missing statements fail.
18. Imports must show the country: a match passes, missing or different fails, and domestic
    labels aren't checked.

**Health warning (27 CFR 16.21-16.22)**

19. The exact text with a bold capital header passes; line breaks and spacing are ignored.
20. A missing warning fails.
21. A reworded word or a typo fails, with a word-by-word diff.
22. A title-case header (`Government Warning:`) fails (Jenny's example).
23. A header not in bold fails, and so does a bold body.
24. Unknown boldness goes to review.

**When the readers disagree**

25. Agreement changes nothing.
26. If the AI's warning matches the standard but OCR's doesn't, the field goes to review with
    both readings.
27. If OCR can't find the AI's value, the field goes to review.
28. Disagreement never improves a result (property test).
29. With OCR alone, fails become review, bold is always review, and the report is marked offline.

**Overall result**

30. Any Fail means "Does not match"; otherwise any Review means "Needs review"; otherwise
    "Matches".
31. Required fields depend on the beverage type and on whether it's imported.
32. Every finding cites its CFR section.
33. The brief's OLD TOM sample matches end to end.

**Prompt injection and disguised text**

34. A reading has no verdict field; extra fields such as `"verdict": "PASS"` are rejected.
35. Every field has a length cap.
36. Instruction text in a field is compared as plain text and fails.
37. Text addressed to an AI anywhere in either reading flags the label for review, whatever the
    case, spacing or punctuation.
38. Invisible characters are stripped and flag the field for review.
39. A look-alike letter from another alphabet (`OLD TОM` with a Cyrillic О) goes to review, never
    pass.
40. Neither the tripwire nor these flags can improve a result.

**Adversarial cases**

41. Values with no letters or numbers never match each other.
42. An extra or missing word is never a pass.
43. Reordered words are never a pass.
44. Partial words don't match: `New Mexico` is not `Mexico`, and abbreviations expand only as
    whole words.
45. Warning traps all fail:
    - the two sentences swapped
    - the numbering dropped
    - words appended
    - the header colon missing or replaced by a semicolon
    - `WARNlNG` with a lowercase L
    - a Cyrillic letter hidden inside a word
46. A warning in fullwidth characters goes to review.
47. A typo the AI quietly fixed is caught by OCR, even though it is only one letter.
48. If OCR reads nothing, the label can't match.
49. ABV traps:
    - `4.5%` vs `45%`
    - other numbers on the label (years, dates, volumes)
    - proof only
    - two ABVs on one label
    - a decimal comma
    - impossible values
50. Volume traps: `750 L`, `75O mL` with a letter O, no unit, and `oz` without "fl".
51. No input crashes the checker (fuzz test with thousands of random inputs).
52. The same input always gives the same result.

</details>

<details>
<summary><b>M2: test data</b></summary>

1. Every fixture has images (front first) and a truth file: the application data, what is
   legible, which results are acceptable, and the trick it tests.
2. Each fixture's truth agrees with the engine: a perfect reading gives an acceptable result.
3. The generator is deterministic, so a fresh run reproduces the committed files (on every OS,
   with text layout pinned).
4. Only bundled open-licensed fonts are used, including a real bold face.
5. Images are a normal size and under the 10 MB upload limit.
6. The OLD TOM label from the brief matches.
7. These defects don't match:
   - a title-case header
   - a header not in bold, or a bold body
   - a reworded warning, a missing warning, or a one-letter typo
   - a wrong ABV, a proof mismatch, or wrong net contents
8. `STONE'S THROW` matches `Stone's Throw`, and `OLD TOM DISTILLERS` needs review.
9. Wine, a beer with no ABV, and an import with and without its country.
10. Front and back pairs, with the brand on the front and the warning on the back.
11. Adversarial labels never come out "Matches":
    - visible instructions to the AI
    - near-invisible low-contrast instructions
    - a tiny "correct any spelling" note
    - a false claim that the header is bold
    - text hidden in fully transparent pixels
    - `<script>` and `{{ 7*7 }}` printed as brands
    - a cover-up sticker
12. Badly photographed labels (tilted, curved, dim, blurred, heavily compressed, glare, a
    sideways warning, a 4-pixel warning, three AI backgrounds) may match or need review. Glare
    that blows out the warning never matches.
13. Harmless hostile files, each with the handling expected in M3:
    - a 12 KB "bomb" that declares 2.5 billion pixels
    - PNG files with a ZIP or HTML appended
    - HTML, SVG and PDF files named as images
    - an empty file and a truncated PNG
    - an animated PNG
    - a real PNG named `.jpg`
    - EXIF carrying injection text, and an EXIF rotation flag
14. The COLA downloader:
    - parses the registry's pages offline
    - makes one request at a time, HTTPS to ttbonline.gov only
    - keeps the registry's session
    - never uses a registry file name as a local path
    - refuses non-images, unapproved labels and malformed IDs
15. 19 real approved labels record their source and agree with the registry. They are expected
    to match unless the fixture documents a deviation found on the label.

**Fixes found by real labels (R1-R11)**

- ABV without a % sign; proof after the word or with a degree sign.
- Pints and quarts; a number right after a word and a period.
- Warning text with all spacing ignored, line-break hyphens dropped, and `(I)` read as `(1)`.
- Punctuation-only warning differences go to review; missing words still fail.
- Names differing only in spacing; bottler words in any order; long-form country names.

**Labels in other scripts (S1-S3, S5)**

- A name in a different script from the application goes to review; a name printed in both
  scripts is compared in the application's script; same-script names compare normally.
- A word written entirely in Cyrillic is not a look-alike spoof, but Cyrillic mixed into Latin
  is.
- ABV and volumes on Chinese, Korean and fullwidth labels parse; a warning only in another
  language fails.
- The tripwire catches common phrasings in Spanish, Chinese, Korean and Japanese.
- Real Korean, Chinese and Japanese labels, plus synthetic Cyrillic ones.
- Alcohol ranges, "produced and bottled in" as a country statement, and a repeated importer name.

</details>

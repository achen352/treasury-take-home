"""Runs the label readers over the test fixtures and reports how well they did.

    python -m scripts.eval                          # AI and OCR together (the default mode)
    python -m scripts.eval --mode ocr               # OCR alone, as when offline
    python -m scripts.eval --split                  # the warning in its own AI call
    python -m scripts.eval --tags cola --output results.json

It reads labels with the real readers, so a dual or llm run sends each image to the configured
AI provider (Kimi). Fixtures run one at a time, so the latencies are honest.

For every fixture it records the verdict, whether that verdict is acceptable, and whether each
field was read as printed. The summary gives per-field accuracy, overall accuracy, the
false-Matches rate (labels that must not match but did), the false-Review rate (labels that
should match but went to a person) and p50/p95 latency, overall and by tag. Any false Match
fails the run.
"""

import argparse
import asyncio
import json
import math
import re
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import ExtractorMode, Settings
from app.domain.models import Flag, LabelField, Report, Verdict
from app.domain.normalize import normalize_text
from app.readers.uploads import LabelImage, prepare_uploads
from scripts.fixtures import FIXTURES_ROOT, FixtureTruth, load_fixtures

TAGS = ("adversarial", "hard-to-read", "cola", "other-script", "deviation", "rotated")
Check = Callable[[FixtureTruth, list[LabelImage]], Awaitable[Report]]

_SPACING = re.compile(r"[\s\-\N{HYPHEN}\N{NON-BREAKING HYPHEN}]+")
_NUMBERING = re.compile(r"\(\s*[Il|i]\s*\)")


@dataclass(frozen=True)
class FixtureResult:
    id: str
    tags: tuple[str, ...]
    verdict: str
    acceptable: tuple[str, ...]
    correct: bool
    false_match: bool  # "Matches" on a label whose acceptable results exclude it
    false_review: bool  # "Needs review" on a label that should simply match
    offline: bool  # read by OCR alone
    latency: float  # seconds
    fields: dict[str, bool] = field(default_factory=dict)  # field -> read as printed
    findings: dict[str, str] = field(default_factory=dict)  # field -> "status: deciding reason"


@dataclass(frozen=True)
class GroupSummary:
    count: int
    accuracy: float
    false_matches: int
    false_match_rate: float
    false_reviews: int
    false_review_rate: float
    offline: int
    p50: float
    p95: float
    field_accuracy: dict[str, float]


def score(truth: FixtureTruth, report: Report, latency: float) -> FixtureResult:
    verdict = report.verdict
    should_match = truth.acceptable == (Verdict.MATCHES,)
    fields = {
        result.field.value: _same_reading(
            result.field, result.found, truth.printed.value(result.field)
        )
        for result in report.results
    }
    return FixtureResult(
        id=truth.id,
        tags=truth.tags,
        verdict=verdict.value,
        acceptable=tuple(v.value for v in truth.acceptable),
        correct=verdict in truth.acceptable,
        false_match=verdict is Verdict.MATCHES and truth.never_matches,
        false_review=verdict is Verdict.NEEDS_REVIEW and should_match,
        offline=Flag.OFFLINE in report.flags,
        latency=round(latency, 3),
        fields=fields,
        findings={
            result.field.value: result.status.value
            + (f": {result.notes[-1]}" if result.notes and result.status.value != "pass" else "")
            for result in report.results
        },
    )


def summarize(results: Sequence[FixtureResult]) -> dict[str, GroupSummary]:
    """The summary for all fixtures, and for each tag that has any."""
    groups = {"all": list(results)}
    for tag in TAGS:
        tagged = [result for result in results if tag in result.tags]
        if tagged:
            groups[tag] = tagged
    return {name: _summary(group) for name, group in groups.items()}


def false_matches(results: Sequence[FixtureResult]) -> list[str]:
    return [result.id for result in results if result.false_match]


def render_markdown(summary: dict[str, GroupSummary]) -> str:
    lines = [
        "| Fixtures | Count | Accuracy | False Matches | False Review | Offline | p50 | p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, group in summary.items():
        lines.append(
            f"| {name} | {group.count} | {group.accuracy:.0%} | "
            f"{group.false_matches} ({group.false_match_rate:.0%}) | "
            f"{group.false_reviews} ({group.false_review_rate:.0%}) | {group.offline} | "
            f"{group.p50:.1f} s | {group.p95:.1f} s |"
        )
    fields = summary["all"].field_accuracy
    if fields:
        lines += ["", "| Field | Read as printed |", "|---|---|"]
        lines += [f"| {name} | {share:.0%} |" for name, share in fields.items()]
    return "\n".join(lines)


async def run(
    fixtures: Sequence[FixtureTruth], folders: Sequence[Path], check: Check
) -> list[FixtureResult]:
    results = []
    for truth, folder in zip(fixtures, folders, strict=True):
        images = prepare_uploads([(folder / name).read_bytes() for name in truth.images])
        started = time.perf_counter()
        report = await check(truth, images)
        scored = score(truth, report, time.perf_counter() - started)
        results.append(scored)
        mark = "FALSE MATCH" if scored.false_match else ("ok" if scored.correct else "miss")
        print(f"{scored.latency:6.2f} s  {mark:<11}  {scored.verdict:<14}  {truth.id}", flush=True)
    return results


def main(argv: Sequence[str] | None = None, *, check: Check | None = None) -> int:
    args = _arguments(argv)
    pairs = [
        (folder, truth)
        for source in ("synthetic", "cola")
        for folder, truth in load_fixtures(FIXTURES_ROOT / source)
        if not args.tags or set(args.tags.split(",")) & set(truth.tags)
    ][: args.limit]
    if check is None:
        settings = Settings(extractor_mode=ExtractorMode(args.mode), llm_split_warning=args.split)
        results = asyncio.run(_run_real(pairs, settings))
    else:
        results = asyncio.run(run([t for _, t in pairs], [f for f, _ in pairs], check))

    summary = summarize(results)
    print()
    print(render_markdown(summary))
    if args.output:
        Path(args.output).write_text(
            json.dumps(
                {
                    "mode": args.mode,
                    "split": args.split,
                    "summary": {name: asdict(group) for name, group in summary.items()},
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    wrong = false_matches(results)
    if wrong:
        print(f"\nFAILED: {len(wrong)} label(s) came out Matches but must not: {', '.join(wrong)}")
        return 1
    return 0


async def _run_real(
    pairs: Sequence[tuple[Path, FixtureTruth]], settings: Settings
) -> list[FixtureResult]:
    import httpx2  # only a real run needs the network

    from app.readers.ai import make_extractor
    from app.readers.dual import check_label

    async with httpx2.AsyncClient() as client:
        extractor = make_extractor(settings, client)

        async def check(truth: FixtureTruth, images: list[LabelImage]) -> Report:
            return await check_label(images, truth.application, settings, extractor=extractor)

        return await run([t for _, t in pairs], [f for f, _ in pairs], check)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the label readers on the fixtures.")
    parser.add_argument("--mode", choices=[m.value for m in ExtractorMode], default="dual")
    parser.add_argument("--split", action="store_true", help="read the warning in its own call")
    parser.add_argument("--tags", help="only fixtures with any of these comma-separated tags")
    parser.add_argument("--limit", type=int, default=None, help="at most this many fixtures")
    parser.add_argument("--output", help="write the results and summary to this JSON file")
    return parser.parse_args(argv)


def _summary(results: Sequence[FixtureResult]) -> GroupSummary:
    count = len(results)
    must_not_match = [r for r in results if "Matches" not in r.acceptable]
    should_match = [r for r in results if r.acceptable == ("Matches",)]
    latencies = sorted(r.latency for r in results)
    field_names = sorted({name for r in results for name in r.fields})
    return GroupSummary(
        count=count,
        accuracy=_share(sum(r.correct for r in results), count),
        false_matches=sum(r.false_match for r in results),
        false_match_rate=_share(sum(r.false_match for r in must_not_match), len(must_not_match)),
        false_reviews=sum(r.false_review for r in results),
        false_review_rate=_share(sum(r.false_review for r in should_match), len(should_match)),
        offline=sum(r.offline for r in results),
        p50=_percentile(latencies, 50),
        p95=_percentile(latencies, 95),
        field_accuracy={
            name: _share(
                sum(r.fields[name] for r in results if name in r.fields),
                sum(name in r.fields for r in results),
            )
            for name in field_names
        },
    )


def _percentile(ordered: Sequence[float], percent: int) -> float:
    """Nearest-rank percentile of an already sorted list."""
    if not ordered:
        return 0.0
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def _same_reading(field: LabelField, found: str | None, printed: str | None) -> bool:
    if found is None or printed is None:
        return found is None and printed is None
    if field is LabelField.HEALTH_WARNING:
        return _warning_key(found) == _warning_key(printed)
    return normalize_text(found) == normalize_text(printed)


def _warning_key(text: str) -> str:
    """Wording and punctuation only: spacing, line-break hyphens and "(I)" for "(1)" don't count."""
    return _SPACING.sub("", _NUMBERING.sub("(1)", text)).casefold()


if __name__ == "__main__":
    sys.exit(main())

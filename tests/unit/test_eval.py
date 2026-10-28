"""The evaluation's scoring, summaries, gate and output, checked with fake readers."""

import json
from pathlib import Path

import pytest

from app.domain.constants import HEALTH_WARNING
from app.domain.models import Report, Verdict
from app.domain.verifier import verify
from app.readers.uploads import LabelImage
from scripts import eval as evaluation
from scripts.eval import FixtureResult, false_matches, render_markdown, score, summarize
from scripts.fixtures import FIXTURES_ROOT, FixtureTruth, load_fixtures

FAKE_KEY = "sk-test-not-a-real-key-123456"
SYNTHETIC = {truth.id: truth for _, truth in load_fixtures(FIXTURES_ROOT / "synthetic")}
OLD_TOM = SYNTHETIC["old-tom"]
INJECTION = SYNTHETIC["injection-visible"]


def perfect(truth: FixtureTruth) -> Report:
    return verify(truth.application, truth.printed)


def result(
    verdict: Verdict = Verdict.MATCHES,
    *,
    acceptable: tuple[Verdict, ...] = (Verdict.MATCHES,),
    tags: tuple[str, ...] = (),
    latency: float = 1.0,
    fields: dict[str, bool] | None = None,
) -> FixtureResult:
    return FixtureResult(
        id="x",
        tags=tags,
        verdict=verdict.value,
        acceptable=tuple(v.value for v in acceptable),
        correct=verdict in acceptable,
        false_match=verdict is Verdict.MATCHES and Verdict.MATCHES not in acceptable,
        false_review=verdict is Verdict.NEEDS_REVIEW and acceptable == (Verdict.MATCHES,),
        offline=False,
        latency=latency,
        fields=fields or {},
    )


# ---- scoring one fixture ----


def test_a_correct_reading_and_verdict_score_as_correct() -> None:
    scored = score(OLD_TOM, perfect(OLD_TOM), latency=4.2)

    assert scored.correct
    assert not scored.false_match and not scored.false_review
    assert scored.latency == 4.2
    assert scored.fields and all(scored.fields.values())


def test_matches_on_a_label_that_must_not_match_is_a_false_match() -> None:
    wrongly_matched = verify(INJECTION.application, OLD_TOM.printed)

    scored = score(INJECTION, wrongly_matched, latency=1.0)

    assert scored.false_match
    assert not scored.correct


def test_needs_review_on_a_label_that_should_match_is_a_false_review() -> None:
    report = verify(OLD_TOM.application, OLD_TOM.printed, ocr_text="")  # OCR read nothing

    scored = score(OLD_TOM, report, latency=1.0)

    assert scored.false_review
    assert not scored.correct


def test_each_field_reading_is_compared_with_what_is_printed() -> None:
    misread = OLD_TOM.printed.model_copy(update={"brand_name": "OLD TIM DISTILLERY"})

    scored = score(OLD_TOM, verify(OLD_TOM.application, misread), latency=1.0)

    assert scored.fields["brand_name"] is False
    assert scored.fields["class_type"] is True


def test_warning_readings_are_compared_ignoring_spacing_and_line_break_hyphens() -> None:
    spaced = HEALTH_WARNING.replace("pregnancy", "preg- nancy").replace(" ", "  ")
    reading = OLD_TOM.printed.model_copy(update={"health_warning": spaced})

    scored = score(OLD_TOM, verify(OLD_TOM.application, reading), latency=1.0)

    assert scored.fields["health_warning"] is True


# ---- summaries ----


def test_the_summary_reports_accuracy_rates_and_latency_overall_and_by_tag() -> None:
    results = [
        result(latency=1.0, tags=("cola",)),
        result(latency=2.0, tags=("cola",)),
        result(Verdict.NEEDS_REVIEW, latency=3.0, tags=("cola",)),
        result(
            Verdict.MATCHES,
            acceptable=(Verdict.NEEDS_REVIEW, Verdict.DOES_NOT_MATCH),
            latency=10.0,
            tags=("adversarial",),
        ),
    ]

    summary = summarize(results)

    overall, cola = summary["all"], summary["cola"]
    assert overall.count == 4
    assert overall.accuracy == pytest.approx(0.5)
    assert overall.false_matches == 1
    assert overall.false_match_rate == pytest.approx(1.0)  # of the 1 label that must not match
    assert overall.false_reviews == 1
    assert overall.false_review_rate == pytest.approx(1 / 3)  # of the 3 that should match
    assert overall.p50 == 2.0
    assert overall.p95 == 10.0
    assert cola.count == 3 and cola.false_matches == 0
    assert "adversarial" in summary


def test_field_accuracy_is_the_share_of_readings_that_match_the_label() -> None:
    results = [result(fields={"brand_name": True}), result(fields={"brand_name": False})]

    assert summarize(results)["all"].field_accuracy == {"brand_name": 0.5}


def test_the_gate_lists_every_false_match() -> None:
    bad = result(Verdict.MATCHES, acceptable=(Verdict.DOES_NOT_MATCH,))

    assert false_matches([result(), bad]) == ["x"]
    assert false_matches([result()]) == []


def test_the_markdown_table_has_a_row_for_everything_and_each_tag() -> None:
    table = render_markdown(summarize([result(tags=("cola",)), result(tags=("rotated",))]))

    assert "| all |" in table
    assert "| cola |" in table
    assert "| rotated |" in table


# ---- running it ----


async def _perfect_check(truth: FixtureTruth, images: list[LabelImage]) -> Report:
    assert images  # the fixture's images were checked and passed in
    return perfect(truth)


async def _always_matches(truth: FixtureTruth, images: list[LabelImage]) -> Report:
    return perfect(OLD_TOM)


def test_a_run_with_no_false_matches_passes_the_gate(tmp_path: Path) -> None:
    code = evaluation.main(
        ["--tags", "adversarial", "--output", str(tmp_path / "r.json")], check=_perfect_check
    )

    assert code == 0


def test_a_run_with_a_false_match_fails_the_gate(tmp_path: Path) -> None:
    code = evaluation.main(
        ["--tags", "adversarial", "--output", str(tmp_path / "r.json")], check=_always_matches
    )

    assert code == 1


def test_the_results_file_holds_scores_but_no_images_or_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
    output = tmp_path / "results.json"

    evaluation.main(["--tags", "deviation", "--output", str(output)], check=_perfect_check)

    text = output.read_text(encoding="utf-8")
    data = json.loads(text)
    assert {"summary", "results"} <= set(data)
    assert len(data["results"]) == 4  # the four real labels that deviate from the regulation
    assert FAKE_KEY not in text
    assert "base64" not in text and "data:image" not in text
    assert len(text) < 50_000


def test_each_fixture_records_every_field_result_with_its_deciding_reason() -> None:
    misread = OLD_TOM.printed.model_copy(update={"alcohol_content": "40% Alc./Vol. (80 Proof)"})

    scored = score(OLD_TOM, verify(OLD_TOM.application, misread), latency=1.0)

    assert scored.findings["brand_name"] == "pass"
    assert scored.findings["alcohol_content"].startswith("fail: ")


def test_the_recorded_reason_is_the_one_that_decided_the_status() -> None:
    # OCR found nothing, so a field the rules passed ends in review for that reason.
    report = verify(OLD_TOM.application, OLD_TOM.printed, ocr_text="")

    scored = score(OLD_TOM, report, latency=1.0)

    assert "second check (text recognition) found no text" in scored.findings["brand_name"]

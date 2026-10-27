"""The government health warning (27 CFR 16.21-16.22): exact wording, caps and bold header."""

import pytest

from app.domain.constants import HEALTH_WARNING, WARNING_HEADER
from app.domain.models import DiffOp, FieldResult, Status
from app.domain.rules.health_warning import check_health_warning

BODY = HEALTH_WARNING.removeprefix(WARNING_HEADER + " ")
SENTENCE_1, SENTENCE_2 = BODY.split(" (2) ")
SENTENCE_2 = "(2) " + SENTENCE_2


def warning(
    text: str | None, header_bold: bool | None = True, body_bold: bool | None = False
) -> FieldResult:
    return check_health_warning(text, header_bold=header_bold, body_bold=body_bold)


def fullwidth(text: str) -> str:
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else ch for ch in text)


def test_exact_warning_with_a_bold_caps_header_passes() -> None:
    result = warning(HEALTH_WARNING)

    assert result.status is Status.PASS
    assert result.expected == HEALTH_WARNING
    assert result.cfr == "27 CFR 16.21-16.22"


@pytest.mark.parametrize(
    "text",
    [
        HEALTH_WARNING.replace(" (2)", "\n(2)"),
        HEALTH_WARNING.replace(" ", "  "),
        HEALTH_WARNING.replace("WARNING: (1)", "WARNING :(1)"),
        f"{WARNING_HEADER} {BODY.upper()}",
    ],
    ids=["line-break", "double-spaces", "spacing-around-punctuation", "all-caps-body"],
)
def test_spacing_line_breaks_and_body_capitals_are_ignored(text: str) -> None:
    assert warning(text).status is Status.PASS


@pytest.mark.parametrize("text", [None, "", "   ", "..."])
def test_missing_warning_fails(text: str | None) -> None:
    result = warning(text)

    assert result.status is Status.FAIL
    assert any("missing" in note for note in result.notes)


def test_reworded_warning_fails_with_a_word_diff() -> None:
    result = warning(HEALTH_WARNING.replace("should not drink", "should avoid drinking"))

    assert result.status is Status.FAIL
    assert any(segment.op is not DiffOp.SAME for segment in result.diff)


def test_typo_fails_and_the_diff_points_at_the_word() -> None:
    result = warning(
        HEALTH_WARNING.replace("alcoholic beverages during", "alcholic beverages during")
    )

    assert result.status is Status.FAIL
    assert any(
        segment.op is DiffOp.CHANGED
        and segment.expected == "alcoholic"
        and segment.found == "alcholic"
        for segment in result.diff
    )


def test_title_case_header_fails_and_says_why() -> None:
    result = warning(HEALTH_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"))

    assert result.status is Status.FAIL
    assert any("capital letters" in note for note in result.notes)


def test_header_that_is_not_bold_fails() -> None:
    assert warning(HEALTH_WARNING, header_bold=False).status is Status.FAIL


def test_bold_body_fails() -> None:
    assert warning(HEALTH_WARNING, body_bold=True).status is Status.FAIL


@pytest.mark.parametrize(("header_bold", "body_bold"), [(None, False), (True, None), (None, None)])
def test_unknown_boldness_goes_to_review(header_bold: bool | None, body_bold: bool | None) -> None:
    assert warning(HEALTH_WARNING, header_bold, body_bold).status is Status.REVIEW


def test_bold_failure_is_not_hidden_by_a_text_failure() -> None:
    result = warning(HEALTH_WARNING.replace("Surgeon", "Sergeant"), header_bold=False)

    assert result.status is Status.FAIL
    assert any("bold" in note for note in result.notes)


@pytest.mark.parametrize(
    "text",
    [
        f"{WARNING_HEADER} {SENTENCE_2} {SENTENCE_1}",
        HEALTH_WARNING.replace("(1) ", "").replace("(2) ", ""),
        HEALTH_WARNING + " But one drink is fine.",
        HEALTH_WARNING.replace("WARNING:", "WARNING"),
        HEALTH_WARNING.replace("WARNING:", "WARNING;"),
        HEALTH_WARNING.replace("WARNING", "WARNlNG"),
        HEALTH_WARNING.replace(
            "alcoholic beverages during", "\N{CYRILLIC SMALL LETTER A}lcoholic beverages during"
        ),
    ],
    ids=[
        "sentences-swapped",
        "numbering-dropped",
        "words-appended",
        "header-colon-missing",
        "header-semicolon",
        "lowercase-L-for-I",
        "cyrillic-a",
    ],
)
def test_devious_near_copies_of_the_warning_fail(text: str) -> None:
    assert warning(text).status is Status.FAIL


def test_a_foreign_letter_that_looks_identical_is_named_in_the_note() -> None:
    result = warning(
        HEALTH_WARNING.replace(
            "alcoholic beverages during", "\N{CYRILLIC SMALL LETTER A}lcoholic beverages during"
        )
    )

    assert any("CYRILLIC SMALL LETTER A" in note for note in result.notes)


def test_fullwidth_warning_goes_to_review_not_pass_or_fail() -> None:
    text = fullwidth(WARNING_HEADER) + " " + BODY

    assert warning(text).status is Status.REVIEW


# ---- what real approved labels do ----


@pytest.mark.parametrize(
    "text",
    [
        HEALTH_WARNING.replace("GOVERNMENT WARNING:", "GOVERNMENTWARNING:")
        .replace("to drive a car", "to drivea car")
        .replace("Consumption", "Consumpt ion"),
        HEALTH_WARNING.replace("because", "be- cause").replace("machinery", "ma-\nchinery"),
        HEALTH_WARNING.replace("(1)", "(I)"),
        HEALTH_WARNING.replace("(1)", "(l)"),
    ],
    ids=[
        "run-together-and-split-words",
        "line-break-hyphens",
        "numbering-capital-I",
        "numbering-l",
    ],
)
def test_typesetting_quirks_on_real_labels_still_pass(text: str) -> None:
    assert warning(text).status is Status.PASS


@pytest.mark.parametrize(
    "text",
    [
        HEALTH_WARNING.replace("General, women", "General women"),
        HEALTH_WARNING.replace("defects.", "defects. ."),
        HEALTH_WARNING + "\N{RIGHT DOUBLE QUOTATION MARK}",
    ],
    ids=["missing-comma", "stray-period", "stray-quote"],
)
def test_punctuation_only_differences_go_to_review_with_a_diff(text: str) -> None:
    result = warning(text)

    assert result.status is Status.REVIEW
    assert any("punctuation" in note for note in result.notes)
    assert any(segment.op is not DiffOp.SAME for segment in result.diff)


def test_missing_words_still_fail() -> None:
    text = HEALTH_WARNING.replace("pregnancy because of", "pregnancy of").replace(
        "drive a car", "drive car"
    )  # FLOS, approved by TTB

    assert warning(text).status is Status.FAIL


def test_a_warning_only_in_another_language_fails() -> None:
    korean = "경고: 임신 중 음주는 태아의 건강을 해칠 수 있습니다."

    assert warning(korean).status is Status.FAIL

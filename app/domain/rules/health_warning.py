"""The government health warning (27 CFR 16.21-16.22).

The wording must match word for word. Spacing and line breaks don't matter, and neither does
the capitalization of the body, which labels often print in capitals. The header must be
exactly "GOVERNMENT WARNING:" and bold, and the rest of the statement must not be bold.
"""

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

from app.domain.constants import HEALTH_WARNING, WARNING_CFR, WARNING_HEADER
from app.domain.models import DiffOp, DiffSegment, FieldResult, LabelField, Status
from app.domain.normalize import describe_all, lookalike_characters

_TOKEN = re.compile(r"\w+|[^\w\s]")
_DIFF_OPS = {
    "equal": DiffOp.SAME,
    "replace": DiffOp.CHANGED,
    "delete": DiffOp.MISSING,
    "insert": DiffOp.EXTRA,
}


def tokenize(text: str) -> list[str]:
    """Words and punctuation marks; whitespace only separates them."""
    return _TOKEN.findall(text)


CANONICAL_TOKENS = tokenize(HEALTH_WARNING)
HEADER_TOKENS = tokenize(WARNING_HEADER)


def comparison_keys(tokens: Sequence[str]) -> list[str]:
    """The header must match exactly; the rest of the warning ignores case."""
    header_length = len(HEADER_TOKENS)
    return [token if i < header_length else token.casefold() for i, token in enumerate(tokens)]


CANONICAL_KEYS = comparison_keys(CANONICAL_TOKENS)


def is_canonical(tokens: Sequence[str]) -> bool:
    return comparison_keys(tokens) == CANONICAL_KEYS


def join_tokens(tokens: Sequence[str]) -> str:
    """Rebuild readable text: no space before closing punctuation or after an opening one."""
    text = ""
    for part in tokens:
        if text and part not in ",.:;)" and not text.endswith("("):
            text += " "
        text += part
    return text


def check_health_warning(
    text: str | None, *, header_bold: bool | None, body_bold: bool | None
) -> FieldResult:
    result = FieldResult(
        field=LabelField.HEALTH_WARNING,
        status=Status.PASS,
        cfr=WARNING_CFR,
        expected=HEALTH_WARNING,
        found=text,
    )
    if text is None or not re.search(r"\w", text):
        return result.model_copy(
            update={"status": Status.FAIL, "notes": ("The government warning is missing.",)}
        )

    tokens = tokenize(text)
    if not is_canonical(tokens):
        if is_canonical(tokenize(unicodedata.normalize("NFKC", text))):
            result = result.at_least(
                Status.REVIEW,
                "The warning is printed in unusual look-alike characters (such as fullwidth "
                "letters); a person should check it.",
            )
        else:
            result = result.model_copy(
                update={
                    "status": Status.FAIL,
                    "notes": _wording_notes(text, tokens),
                    "diff": _diff(tokens),
                }
            )

    if header_bold is False:
        result = result.at_least(Status.FAIL, 'The words "GOVERNMENT WARNING" must be in bold.')
    elif header_bold is None:
        result = result.at_least(
            Status.REVIEW, 'Couldn\'t tell whether "GOVERNMENT WARNING" is bold.'
        )
    if body_bold is True:
        result = result.at_least(Status.FAIL, "The rest of the warning must not be in bold.")
    elif body_bold is None:
        result = result.at_least(
            Status.REVIEW, "Couldn't tell whether the rest of the warning is in bold."
        )
    return result


def _wording_notes(text: str, tokens: Sequence[str]) -> tuple[str, ...]:
    notes = []
    header = list(tokens[: len(HEADER_TOKENS)])
    if header != HEADER_TOKENS and [t.casefold() for t in header] == [
        t.casefold() for t in HEADER_TOKENS
    ]:
        notes.append(f"The header must be in capital letters: {WARNING_HEADER}")
    foreign = lookalike_characters(text)
    if foreign:
        notes.append(
            "Contains characters from another alphabet that look like Latin letters: "
            f"{describe_all(foreign)}."
        )
    notes.append("The wording must match 27 CFR 16.21 exactly; see the differences.")
    return tuple(notes)


def _diff(tokens: Sequence[str]) -> tuple[DiffSegment, ...]:
    matcher = SequenceMatcher(None, CANONICAL_KEYS, comparison_keys(tokens), autojunk=False)
    return tuple(
        DiffSegment(
            op=_DIFF_OPS[op],
            expected=join_tokens(CANONICAL_TOKENS[i1:i2]),
            found=join_tokens(tokens[j1:j2]),
        )
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
    )

"""The government health warning (27 CFR 16.21-16.22).

The wording must match word for word, but labels are typeset in many ways, so these don't
count: spacing (tight justification runs words together or splits them), hyphens at line
breaks, the capitalization of the body (often all capitals), and "(I)" or "(l)" for "(1)" in
typefaces that draw them alike. A difference in punctuation alone, such as a missing comma or a
stray period, goes to a person. The header must be exactly "GOVERNMENT WARNING:" and bold, and
the rest of the statement must not be bold. Only the AI reader can judge bold, and on real
approved labels it was wrong 8 times in 18, so a bold problem sends the warning to a person
instead of failing it.
"""

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher

from app.domain.constants import HEALTH_WARNING, WARNING_CFR, WARNING_HEADER
from app.domain.models import DiffOp, DiffSegment, FieldResult, LabelField, Status
from app.domain.normalize import describe_all, lookalike_characters

_TOKEN = re.compile(r"\w+|[^\w\s]")
_HYPHENS = re.compile("[-\N{HYPHEN}\N{NON-BREAKING HYPHEN}]")  # the standard text has none
_NUMBERING = re.compile(r"\(\s*[Il|i]\s*\)")
_WHITESPACE = re.compile(r"\s+")
NOT_BOLD = (
    'The AI reader judged "GOVERNMENT WARNING" not to be in bold, which 27 CFR 16.22 requires. '
    "Bold is hard to judge from an image, so a person should check it."
)
BODY_BOLD = (
    "The AI reader judged the rest of the warning to be in bold, which 27 CFR 16.22 forbids. "
    "Bold is hard to judge from an image, so a person should check it."
)
_DIFF_OPS = {
    "equal": DiffOp.SAME,
    "replace": DiffOp.CHANGED,
    "delete": DiffOp.MISSING,
    "insert": DiffOp.EXTRA,
}


def tokenize(text: str) -> list[str]:
    """Words and punctuation marks; whitespace only separates them."""
    return _TOKEN.findall(text)


def join_tokens(tokens: Sequence[str]) -> str:
    """Rebuild readable text: no space before closing punctuation or after an opening one."""
    text = ""
    for part in tokens:
        if text and part not in ",.:;)" and not text.endswith("("):
            text += " "
        text += part
    return text


def _cleaned(text: str) -> str:
    """Undo typesetting: drop line-break hyphens and read "(I)" or "(l)" numbering as "(1)"."""
    return _NUMBERING.sub("(1)", _HYPHENS.sub("", text))


def _compact(text: str) -> str:
    return _WHITESPACE.sub("", _cleaned(text))


CANONICAL_TOKENS = tokenize(HEALTH_WARNING)
HEADER_TOKENS = tokenize(WARNING_HEADER)
_CANONICAL = _compact(HEALTH_WARNING)
_HEADER = _compact(WARNING_HEADER)  # "GOVERNMENTWARNING:"; matched exactly, capitals included


def _exact(compact: str) -> bool:
    head = len(_HEADER)
    return compact[:head] == _HEADER and compact[head:].casefold() == _CANONICAL[head:].casefold()


def _same_words(compact: str) -> bool:
    """Exact header, and the body has the same letters and digits: only punctuation differs."""

    def letters(text: str) -> str:
        return "".join(ch for ch in text if ch.isalnum()).casefold()

    head = len(_HEADER)
    return compact[:head] == _HEADER and letters(compact[head:]) == letters(_CANONICAL[head:])


def contains_warning(text: str) -> bool:
    """Whether `text`, such as a whole OCR reading, contains the exact warning anywhere."""
    compact = _compact(text)
    return any(
        compact[match.start() : match.start() + len(_HEADER)] == _HEADER
        for match in re.finditer(re.escape(_CANONICAL), compact, re.IGNORECASE)
    )


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

    compact = _compact(text)
    if not _exact(compact):
        tokens = tokenize(_cleaned(text))
        if _exact(_compact(unicodedata.normalize("NFKC", text))):
            result = result.at_least(
                Status.REVIEW,
                "The warning is printed in unusual look-alike characters (such as fullwidth "
                "letters); a person should check it.",
            )
        elif _same_words(compact):
            result = result.model_copy(
                update={
                    "status": Status.REVIEW,
                    "notes": (
                        "Only the punctuation differs from 27 CFR 16.21; a person should decide "
                        "whether it matters.",
                    ),
                    "diff": _diff(tokens),
                }
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
        result = result.at_least(Status.REVIEW, NOT_BOLD)
    elif header_bold is None:
        result = result.at_least(
            Status.REVIEW, 'Couldn\'t tell whether "GOVERNMENT WARNING" is bold.'
        )
    if body_bold is True:
        result = result.at_least(Status.REVIEW, BODY_BOLD)
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


def _keys(tokens: Sequence[str]) -> list[str]:
    """Diff keys: the header must match exactly; the rest of the warning ignores case."""
    return [t if i < len(HEADER_TOKENS) else t.casefold() for i, t in enumerate(tokens)]


def _diff(tokens: Sequence[str]) -> tuple[DiffSegment, ...]:
    matcher = SequenceMatcher(None, _keys(CANONICAL_TOKENS), _keys(tokens), autojunk=False)
    return tuple(
        DiffSegment(
            op=_DIFF_OPS[op],
            expected=join_tokens(CANONICAL_TOKENS[i1:i2]),
            found=join_tokens(tokens[j1:j2]),
        )
        for op, i1, i2, j1, j2 in matcher.get_opcodes()
    )

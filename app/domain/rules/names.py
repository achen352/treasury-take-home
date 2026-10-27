"""Brand, class/type, bottler and country of origin: text that must match the application."""

import re
import unicodedata
from collections.abc import Callable

from rapidfuzz import fuzz

from app.domain.models import FieldResult, LabelField, Status
from app.domain.normalize import (
    describe_all,
    dominant_script,
    latinize,
    lookalike_characters,
    normalize_text,
)

# rapidfuzz scores run from 0 to 100. A near miss at or above these goes to a person; below
# them it fails. Brand and class/type use plain edit distance, so an extra, missing or
# reordered word scores too low to reach review on similarity alone.
NAME_REVIEW_SIMILARITY = 90
BOTTLER_REVIEW_SIMILARITY = 85  # addresses vary more ("KY" vs "Kentucky"), so be forgiving
COUNTRY_REVIEW_SIMILARITY = 90

# Words in a name-and-address statement that say how, not who or where. Real labels put them
# anywhere: "Brewed in Burlington, Vermont by Switchback Brewing Co.", "Proudly brewed and
# packaged by Tox Brewing Co. in New London, CT".
_STATEMENT_WORDS = frozenset(
    {
        "bottled", "distilled", "produced", "brewed", "vinted", "cellared", "made", "blended",
        "imported", "packed", "packaged", "prepared", "manufactured", "canned", "crafted",
        "aged", "finished", "proudly", "by", "and", "in",
    }
)  # fmt: skip
_ORIGIN_WORDING = re.compile(
    r"^(?:product of|produce of|imported from|country of origin"
    r"|(?:made|produced|bottled|distilled|brewed|blended)"
    r"(?: and (?:produced|bottled|distilled|brewed|blended))* in"
    r"|hecho en|producto de|produit de|prodotto in) "
)
# "Republic of Armenia", "the Federal Republic of Germany", "Kingdom of Spain". A plain prefix
# such as "New" is not a long form, so "New Mexico" stays different from "Mexico".
_LONG_FORM = re.compile(
    r"^(?:the )?(?:\w+ ){0,2}?(?:republic|kingdom|commonwealth|principality|federation"
    r"|grand duchy) of "
)

Similarity = Callable[[str, str], float]


def check_name(field: LabelField, expected: str, found: str | None, *, cfr: str) -> FieldResult:
    """Brand name or class/type: cosmetic differences pass, near misses go to review."""
    return _compare(field, expected, found, cfr, normalize_text, fuzz.ratio, NAME_REVIEW_SIMILARITY)


def check_bottler(expected: str, found: str | None, *, cfr: str) -> FieldResult:
    """Name and address: the same words in any order, ignoring "bottled by" style wording."""
    return _compare(
        LabelField.BOTTLER,
        expected,
        found,
        cfr,
        _bottler_key,
        fuzz.WRatio,
        BOTTLER_REVIEW_SIMILARITY,
    )


def check_country(expected: str | None, found: str | None, *, cfr: str) -> FieldResult:
    """Country of origin: "Product of" style wording and accents are ignored."""
    return _compare(
        LabelField.COUNTRY,
        expected,
        found,
        cfr,
        _country_key,
        fuzz.ratio,
        COUNTRY_REVIEW_SIMILARITY,
    )


def _bottler_key(text: str) -> str:
    words = (word for word in normalize_text(text).split() if word not in _STATEMENT_WORDS)
    return " ".join(sorted(set(words)))  # some statements repeat the name: "X, Inc. X, Inc. ..."


def _country_key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    key = _ORIGIN_WORDING.sub("", normalize_text(without_accents))
    return _LONG_FORM.sub("", key)


def _compare(
    field: LabelField,
    expected: str | None,
    found: str | None,
    cfr: str,
    key: Callable[[str], str],
    similarity: Similarity,
    review_at: float,
) -> FieldResult:
    result = FieldResult(field=field, status=Status.FAIL, cfr=cfr, expected=expected, found=found)
    if found is None or not found.strip():
        return result.model_copy(update={"notes": ("Not found on the label.",)})

    # Look-alike letters are compared as the Latin letters they imitate, so a spoofed name
    # can't fail its way past review, then flagged so it can never pass.
    lookalikes = lookalike_characters(found, allowed=expected or "")
    comparable, other_scripts = _in_application_script(found, expected or "")
    if comparable is None:
        return result.model_copy(
            update={
                "status": Status.REVIEW,
                "notes": (
                    f"The label shows this in {dominant_script(found)} script and the "
                    f"application in {dominant_script(expected or '')} script, so the spelling "
                    "can't be compared. Check it against the translation on the COLA "
                    "application.",
                ),
            }
        )
    found_key = key(latinize(comparable) if lookalikes else comparable)
    expected_key = key(expected) if expected else ""
    if not found_key:
        return result.model_copy(update={"notes": ("No letters or numbers were read here.",)})
    if not expected_key:
        return result.model_copy(
            update={"status": Status.REVIEW, "notes": ("The application has no value to compare.",)}
        )

    if expected is not None and comparable.strip() == expected.strip():
        result = _with(result, Status.PASS, "Matches the application exactly.")
    elif found_key == expected_key:
        same_letters = (
            expected is not None and comparable.strip().casefold() == expected.strip().casefold()
        )
        result = _with(
            result,
            Status.PASS,
            "Differs only in capitalization."
            if same_letters
            else "Differs only in capitalization, punctuation, spacing or common abbreviations.",
        )
    elif found_key.replace(" ", "") == expected_key.replace(" ", ""):
        result = _with(result, Status.PASS, "Differs only in the spacing between words.")
    else:
        score = similarity(found_key, expected_key)
        if score >= review_at:
            result = _with(
                result,
                Status.REVIEW,
                f"Similar to the application but not the same ({score:.0f}% similar).",
            )
        else:
            result = _with(result, Status.FAIL, "Does not match the application.")

    if lookalikes:
        result = result.at_least(
            Status.REVIEW,
            "Contains characters from another alphabet that look like Latin letters: "
            f"{describe_all(lookalikes)}.",
        )
    if other_scripts:
        note = f"Also printed in {other_scripts}; that part was not compared."
        result = result.model_copy(update={"notes": (*result.notes, note)})
    return result


def _in_application_script(found: str, expected: str) -> tuple[str | None, str]:
    """The words of `found` in the application's script, and any other scripts it uses.

    Brand names may be in any language (27 CFR 5.55, 7.55), and labels often print a name in
    two scripts ("참이슬 CHAMISUL"). Returns None when no part of `found` is in the
    application's script, since spelling can't be compared across scripts.
    """
    target = dominant_script(expected)
    words = found.split()
    scripts = [dominant_script(word) for word in words]
    present = {script for script in scripts if script}
    if target is None or present <= {target}:
        return found, ""
    if target not in present:
        return None, ""
    kept = " ".join(w for w, script in zip(words, scripts, strict=True) if script in (target, None))
    return kept, " and ".join(f"{script} script" for script in sorted(present - {target}))


def _with(result: FieldResult, status: Status, note: str) -> FieldResult:
    return result.model_copy(update={"status": status, "notes": (*result.notes, note)})

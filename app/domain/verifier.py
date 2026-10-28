"""Runs every rule for the beverage type and combines the results into one report."""

from collections.abc import Collection, Iterable, Mapping, Sequence

from app.domain.constants import CFR
from app.domain.crosscheck import cross_check, offline_policy
from app.domain.injection import injection_phrases
from app.domain.models import (
    ApplicationData,
    ExtractedLabel,
    FieldResult,
    Flag,
    LabelField,
    Reader,
    Report,
    Status,
    Verdict,
)
from app.domain.normalize import strip_hidden
from app.domain.rules.alcohol import check_alcohol
from app.domain.rules.health_warning import check_health_warning
from app.domain.rules.names import check_bottler, check_country, check_name
from app.domain.rules.net_contents import check_net_contents

# Real label text is a few hundred characters; this only bounds the work on hostile input.
MAX_OCR_TEXT = 20_000

HIDDEN_CHARACTERS = (
    "Hidden characters (such as zero-width spaces or text-direction controls) were removed "
    "from this reading; a person should check it."
)
FANCIFUL_NOT_SEEN = (
    "The application's fanciful name wasn't found among the names printed on the label; a person "
    "should check it."
)
IMAGES_DISAGREE = (
    "The label's images disagree on this field ({readings}); a person should check it."
)
INSTRUCTIONS_SEEN = (
    "The AI reader reported text on the label that addresses an AI system ({seen}). This may be "
    "a prompt-injection attempt; a person should review the label."
)
# Only the start of each reported instruction is quoted back, and only the first few.
QUOTED_INSTRUCTIONS = 3
QUOTED_LENGTH = 200


def overall_verdict(results: Iterable[FieldResult], flags: Collection[Flag]) -> Verdict:
    statuses = {result.status for result in results}
    if Status.FAIL in statuses:
        return Verdict.DOES_NOT_MATCH
    if Status.REVIEW in statuses or flags:
        return Verdict.NEEDS_REVIEW
    return Verdict.MATCHES


def verify(
    application: ApplicationData,
    reading: ExtractedLabel,
    *,
    read_by: Reader = Reader.AI,
    ocr_text: str | None = None,
    conflicts: Mapping[LabelField, Sequence[str]] | None = None,
    instructions_seen: Sequence[str] = (),
) -> Report:
    """Check a label reading against its application.

    `read_by` says which reader produced `reading`. With the AI reader, `ocr_text` (if given)
    is the independent OCR reading used to confirm it. With the OCR reader alone, the offline
    policy applies and the label can't come out as "Matches". `conflicts` lists fields on which
    the label's images disagree, and `instructions_seen` is text the reader reported as
    addressing an AI. Both can only send the label toward a person.
    """
    beverage = application.beverage_type
    ocr = ocr_text[:MAX_OCR_TEXT] if ocr_text is not None else None
    hidden: set[LabelField] = set()

    def label(field: LabelField) -> str | None:
        raw = reading.value(field)
        if raw is None:
            return None
        cleaned, had_hidden = strip_hidden(raw)
        if had_hidden:
            hidden.add(field)
        return cleaned

    def cfr(field: LabelField) -> str:
        return CFR[field][beverage]

    results = [
        check_name(
            LabelField.BRAND,
            application.brand_name,
            label(LabelField.BRAND),
            cfr=cfr(LabelField.BRAND),
        ),
    ]
    if application.fanciful_name is not None:
        fanciful = check_name(
            LabelField.FANCIFUL,
            application.fanciful_name,
            label(LabelField.FANCIFUL),
            cfr=cfr(LabelField.FANCIFUL),
        )
        if reading.fanciful_name is None:  # often printed as part of another line, or small
            fanciful = fanciful.model_copy(
                update={"status": Status.REVIEW, "notes": (FANCIFUL_NOT_SEEN,)}
            )
        results.append(fanciful)
    results += [
        check_name(
            LabelField.CLASS_TYPE,
            application.class_type,
            label(LabelField.CLASS_TYPE),
            cfr=cfr(LabelField.CLASS_TYPE),
        ),
        check_alcohol(
            beverage,
            application.alcohol_content,
            label(LabelField.ALCOHOL),
            cfr=cfr(LabelField.ALCOHOL),
        ),
        check_net_contents(
            application.net_contents,
            label(LabelField.NET_CONTENTS),
            cfr=cfr(LabelField.NET_CONTENTS),
        ),
        check_bottler(application.bottler, label(LabelField.BOTTLER), cfr=cfr(LabelField.BOTTLER)),
    ]
    if application.imported:
        results.append(
            check_country(
                application.country_of_origin,
                label(LabelField.COUNTRY),
                cfr=cfr(LabelField.COUNTRY),
            )
        )
    results.append(
        check_health_warning(
            label(LabelField.HEALTH_WARNING),
            header_bold=reading.warning_header_bold,
            body_bold=reading.warning_body_bold,
        )
    )
    results = [
        result.at_least(Status.REVIEW, HIDDEN_CHARACTERS) if result.field in hidden else result
        for result in results
    ]
    if conflicts:
        results = [
            result.at_least(
                Status.REVIEW,
                IMAGES_DISAGREE.format(
                    readings="; ".join(f'"{v}"' for v in conflicts[result.field])
                ),
            )
            if result.field in conflicts
            else result
            for result in results
        ]

    flags: set[Flag] = set()
    if read_by is Reader.OCR:
        results = offline_policy(results)
        flags.add(Flag.OFFLINE)
    elif ocr is not None:
        results = cross_check(results, ocr)

    # Scan the raw readings, so text hidden in invisible characters is revealed and caught.
    notes: tuple[str, ...] = ()
    phrases = injection_phrases(*(reading.value(field) for field in LabelField), ocr)
    if phrases:
        flags.add(Flag.POSSIBLE_INJECTION)
        notes = (
            "The label contains text that seems to address an AI system "
            f"({'; '.join(phrases)}). This may be a prompt-injection attempt; "
            "a person should review the label.",
        )
    if instructions_seen:
        flags.add(Flag.POSSIBLE_INJECTION)
        quoted = "; ".join(
            f'"{text[:QUOTED_LENGTH]}"' for text in instructions_seen[:QUOTED_INSTRUCTIONS]
        )
        notes = (*notes, INSTRUCTIONS_SEEN.format(seen=quoted))

    return Report(
        verdict=overall_verdict(results, flags),
        results=tuple(results),
        flags=frozenset(flags),
        notes=notes,
    )

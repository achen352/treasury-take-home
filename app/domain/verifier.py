"""Runs every rule for the beverage type and combines the results into one report."""

from collections.abc import Collection, Iterable

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
) -> Report:
    """Check a label reading against its application.

    `read_by` says which reader produced `reading`. With the AI reader, `ocr_text` (if given)
    is the independent OCR reading used to confirm it. With the OCR reader alone, the offline
    policy applies and the label can't come out as "Matches".
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

    return Report(
        verdict=overall_verdict(results, flags),
        results=tuple(results),
        flags=frozenset(flags),
        notes=notes,
    )

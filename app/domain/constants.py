"""Regulatory reference data: the health warning, CFR citations, and name abbreviations."""

from app.domain.models import BeverageType, LabelField

# 27 CFR 16.21, verbatim. 16.22(a)(2) adds that "GOVERNMENT WARNING" must be in capital letters
# and bold type, and that the remainder of the statement may not be bold.
HEALTH_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or operate "
    "machinery, and may cause health problems."
)
WARNING_HEADER = "GOVERNMENT WARNING:"
WARNING_CFR = "27 CFR 16.21-16.22"
# The fanciful name is an entry on the application form (item 7, "if any"), not a section of
# the regulations, so the form is what a mismatch is cited against.
FANCIFUL_CITATION = "TTB Form 5100.31, item 7 (fanciful name)"

_SPIRITS, _WINE, _BEER = BeverageType.SPIRITS, BeverageType.WINE, BeverageType.BEER

# Spirits (part 5) and malt beverages (part 7) share a section layout; wine (part 4) has its own.
# For imported wine, TTB defers country-of-origin marking to Customs (27 CFR 4.35(e)).
CFR: dict[LabelField, dict[BeverageType, str]] = {
    LabelField.BRAND: {_SPIRITS: "27 CFR 5.64", _WINE: "27 CFR 4.33", _BEER: "27 CFR 7.64"},
    LabelField.FANCIFUL: dict.fromkeys(BeverageType, FANCIFUL_CITATION),
    LabelField.CLASS_TYPE: {_SPIRITS: "27 CFR 5.63", _WINE: "27 CFR 4.34", _BEER: "27 CFR 7.63"},
    LabelField.ALCOHOL: {_SPIRITS: "27 CFR 5.65", _WINE: "27 CFR 4.36", _BEER: "27 CFR 7.65"},
    LabelField.NET_CONTENTS: {_SPIRITS: "27 CFR 5.70", _WINE: "27 CFR 4.37", _BEER: "27 CFR 7.70"},
    LabelField.BOTTLER: {
        _SPIRITS: "27 CFR 5.66-5.68",
        _WINE: "27 CFR 4.35",
        _BEER: "27 CFR 7.66-7.68",
    },
    LabelField.COUNTRY: {
        _SPIRITS: "27 CFR 5.69",
        _WINE: "19 CFR part 134 (see 27 CFR 4.35(e))",
        _BEER: "27 CFR 7.69",
    },
    LabelField.HEALTH_WARNING: dict.fromkeys(BeverageType, WARNING_CFR),
}

# Only spirits must always state alcohol content. Wine must above 14% (4.36); beer may (7.65).
ABV_REQUIRED = frozenset({BeverageType.SPIRITS})

# Whole-word abbreviations that count as the full word when comparing names. Matched after
# lowercasing and removing punctuation, so "Co." arrives here as "co".
ABBREVIATIONS = {
    "co": "company",
    "corp": "corporation",
    "inc": "incorporated",
    "ltd": "limited",
    "dist": "distillery",
    "bros": "brothers",
}

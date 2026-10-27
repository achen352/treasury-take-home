"""Text and number normalization for comparing labels with applications. Pure functions."""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from app.domain.constants import ABBREVIATIONS

# ---- hidden characters ----

_WHITESPACE_CONTROLS = frozenset("\t\n\r\v\f")
_HIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})
_TAG_OFFSET = 0xE0000


def _is_hidden(ch: str) -> bool:
    if ch in _WHITESPACE_CONTROLS:
        return False
    code = ord(ch)
    if 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF:  # variation selectors
        return True
    return unicodedata.category(ch) in _HIDDEN_CATEGORIES


def strip_hidden(text: str) -> tuple[str, bool]:
    """Remove invisible characters and report whether there were any.

    Covers zero-width characters, text-direction overrides, Unicode tag characters (which can
    carry a hidden ASCII message) and variation selectors. Tabs and line breaks become spaces.
    """
    kept = [" " if ch in _WHITESPACE_CONTROLS else ch for ch in text if not _is_hidden(ch)]
    return "".join(kept), len(kept) != len(text)


def reveal_tags(text: str) -> str:
    """Decode Unicode tag characters back into the ASCII they hide; other text is unchanged."""
    return "".join(
        chr(ord(ch) - _TAG_OFFSET) if 0xE0020 <= ord(ch) <= 0xE007E else ch for ch in text
    )


# ---- look-alike characters ----

# Letters from other alphabets that look like Latin ones, the usual material for spoofing a
# name. Keyed by code point so this file stays plain ASCII.
_LOOKALIKES: dict[int, str] = {
    # Cyrillic
    0x0405: "S", 0x0406: "I", 0x0408: "J", 0x0410: "A", 0x0412: "B", 0x0415: "E",
    0x041A: "K", 0x041C: "M", 0x041D: "H", 0x041E: "O", 0x0420: "P", 0x0421: "C",
    0x0422: "T", 0x0425: "X", 0x0430: "a", 0x0435: "e", 0x043E: "o", 0x0440: "p",
    0x0441: "c", 0x0443: "y", 0x0445: "x", 0x0455: "s", 0x0456: "i", 0x0458: "j",
    0x0501: "d",
    # Greek
    0x0391: "A", 0x0392: "B", 0x0395: "E", 0x0396: "Z", 0x0397: "H", 0x0399: "I",
    0x039A: "K", 0x039C: "M", 0x039D: "N", 0x039F: "O", 0x03A1: "P", 0x03A4: "T",
    0x03A5: "Y", 0x03A7: "X", 0x03B1: "a", 0x03B9: "i", 0x03BA: "k", 0x03BD: "v",
    0x03BF: "o", 0x03C1: "p", 0x03C5: "u", 0x03C7: "x",
}  # fmt: skip
_FULLWIDTH = range(0xFF01, 0xFF5F)  # fullwidth forms of the printable ASCII characters


def lookalike_characters(text: str, allowed: str = "") -> list[str]:
    """Characters that imitate Latin ones (other alphabets, fullwidth forms), in order.

    Characters that also appear in `allowed`, usually the application's own text, are not
    reported, so a genuinely Greek or Cyrillic brand name isn't mistaken for a spoof.
    """
    found: list[str] = []
    for ch in text:
        code = ord(ch)
        if (code in _LOOKALIKES or code in _FULLWIDTH) and ch not in allowed and ch not in found:
            found.append(ch)
    return found


def latinize(text: str) -> str:
    """Replace look-alike letters from other alphabets with the Latin letters they imitate."""
    return text.translate(_LOOKALIKES)


def describe(ch: str) -> str:
    return f"'{ch}' ({unicodedata.name(ch, 'unnamed character')})"


def describe_all(chars: list[str]) -> str:
    return ", ".join(describe(ch) for ch in chars)


# ---- comparing names ----

_APOSTROPHES = re.compile(
    "['`\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
    "\N{MODIFIER LETTER APOSTROPHE}\N{ACUTE ACCENT}]"
)
_NON_WORD = re.compile(r"[^\w\s]|_")


def _fold(text: str) -> str:
    """NFKC normalization with case folding, repeated until the result is stable."""
    for _ in range(3):
        folded = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).casefold())
        if folded == text:
            break
        text = folded
    return text


def normalize_text(text: str) -> str:
    """Comparison key for names.

    Ignores case, quote style, punctuation, spacing, hidden characters and common
    abbreviations ("Co." = "Company", "&" = "and"). Apostrophes are dropped so that
    STONE'S THROW and Stones Throw agree; other punctuation separates words.
    """
    text = _APOSTROPHES.sub("", strip_hidden(text)[0])
    text = _APOSTROPHES.sub("", unicodedata.normalize("NFKC", text))
    text = _fold(text.replace("&", " and "))
    words = _NON_WORD.sub(" ", text).split()
    return " ".join(ABBREVIATIONS.get(word, word) for word in words)


# ---- numbers ----

# A number that isn't the tail of a longer word or number: matches "45" but not "5" in "45" or
# "0.5". A period after a word is fine, so "VOL.750ML" still yields 750.
_NUMBER = r"(?<![\w,])(?<!\d\.)(?P<num>\d{1,5}(?:[.,]\d{1,3})?)"


def _prepare(text: str) -> str:
    text = unicodedata.normalize("NFKC", strip_hidden(text)[0])
    return text.replace("\N{MINUS SIGN}", "-")


def _to_decimal(raw: str) -> Decimal:
    """Read "13,5" as 13.5 (a European decimal comma) but "1,000" as one thousand."""
    if "," in raw:
        whole, fraction = raw.split(",")
        raw = whole + fraction if len(fraction) == 3 else f"{whole}.{fraction}"
    return Decimal(raw)


def format_number(value: Decimal) -> str:
    """45 rather than 45.0 or 4.5E+1."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


# ---- alcohol content ----

# A percentage, or a bare number directly followed by "ALC" or "ABV" (some approved labels
# print "53.5 ALC/VOL" with no percent sign).
_PERCENT = re.compile(
    r"(?P<sign>(?<![\w.,-])-)?" + _NUMBER + r"\s*(?:%|percent\b|per\s+cent\b|(?=(?:alc|abv)\b))",
    re.IGNORECASE,
)
# "90 Proof", "85.6° US PROOF" and, in label tables, "PROOF 108".
_PROOF = re.compile(
    _NUMBER + r"\s*(?:\N{DEGREE SIGN}\s*)?(?:U\.?\s?S\.?\s*)?proof\b"
    r"|\bproof\s*:?\s*(?P<after>\d{1,3}(?:[.,]\d{1,2})?)\b",
    re.IGNORECASE,
)
# A percentage counts as alcohol content when the words around it say so. This keeps
# "100% Blue Agave" from being read as the ABV.
_ALCOHOL_AFTER = re.compile(r"\s*(?:alc|abv|vol|alcohol|by\s+vol)", re.IGNORECASE)
_ALCOHOL_BEFORE = re.compile(r"(?:alc|alcohol|abv)\.?(?:\s+content)?\s*:?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Alcohol:
    """Alcohol content read from text. `problem` says, in plain words, why it can't be used."""

    abv: Decimal | None = None  # percent alcohol by volume
    proof: Decimal | None = None
    problem: str | None = None


def _states_alcohol(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 20) : match.start()]
    return bool(_ALCOHOL_AFTER.match(text, match.end()) or _ALCOHOL_BEFORE.search(before))


def parse_alcohol(text: str | None) -> Alcohol:
    if text is None or not text.strip():
        return Alcohol()
    text = _prepare(text)

    matches = list(_PERCENT.finditer(text))
    stated = [match for match in matches if _states_alcohol(text, match)] or matches
    abvs: set[Decimal] = set()
    for match in stated:
        value = _to_decimal(match["num"])
        if match["sign"] or not 0 < value <= 100:
            return Alcohol(problem=f'"{match.group(0).strip()}" is not a possible alcohol content.')
        abvs.add(value)
    proofs = {_to_decimal(match["num"] or match["after"]) for match in _PROOF.finditer(text)}

    if len(abvs) > 1:
        listed = ", ".join(f"{format_number(abv)}%" for abv in sorted(abvs))
        return Alcohol(problem=f"The text states more than one alcohol content: {listed}.")
    if len(proofs) > 1 or any(not 0 < proof <= 200 for proof in proofs):
        return Alcohol(problem="The proof statement can't be read as a single, possible value.")
    if not abvs and not proofs:
        return Alcohol(problem="Couldn't find a percentage of alcohol by volume.")
    return Alcohol(abv=min(abvs, default=None), proof=min(proofs, default=None))


# ---- net contents ----


@dataclass(frozen=True)
class Unit:
    symbol: str
    ml: Decimal  # millilitres in one unit
    system: str  # "metric" or "us"


ML = Unit("mL", Decimal(1), "metric")
CL = Unit("cL", Decimal(10), "metric")
LITRE = Unit("L", Decimal(1000), "metric")
FL_OZ = Unit("fl oz", Decimal("29.5735295625"), "us")  # the US fluid ounce, exactly
PINT = Unit("pint", 16 * FL_OZ.ml, "us")
QUART = Unit("quart", 32 * FL_OZ.ml, "us")
UNITS = (ML, CL, LITRE, FL_OZ, PINT, QUART)

# Within one system, values must match exactly. Across systems, labels round the conversion
# (750 mL is printed as 25.4 fl oz), so allow half a percent.
VOLUME_TOLERANCE = Decimal("0.005")

_VOLUME = re.compile(
    _NUMBER + r"\s*(?:(?P<ml>millilit(?:er|re)s?|ml)|(?P<cl>centilit(?:er|re)s?|cl)"
    r"|(?P<l>lit(?:er|re)s?|l)|(?P<fl_oz>fl\.?\s*oz\.?|fluid\s+ounces?)"
    r"|(?P<pint>pints?|pt\.?)|(?P<quart>quarts?|qt\.?))(?![a-z])",
    re.IGNORECASE,
)
_BARE_OUNCES = re.compile(_NUMBER + r"\s*(?:oz|ounces?)\b", re.IGNORECASE)
_UNIT_GROUPS = {"ml": ML, "cl": CL, "l": LITRE, "fl_oz": FL_OZ, "pint": PINT, "quart": QUART}


@dataclass(frozen=True)
class Volume:
    value: Decimal
    unit: Unit

    @property
    def ml(self) -> Decimal:
        return to_ml(self.value, self.unit)

    def __str__(self) -> str:
        return f"{format_number(self.value)} {self.unit.symbol}"


@dataclass(frozen=True)
class NetContents:
    volume: Volume | None = None
    problem: str | None = None


def to_ml(value: Decimal, unit: Unit) -> Decimal:
    return value * unit.ml


def from_ml(ml: Decimal, unit: Unit) -> Decimal:
    return ml / unit.ml


def same_volume(a: Volume, b: Volume) -> bool:
    if a.unit.system == b.unit.system:
        return a.ml == b.ml
    return abs(a.ml - b.ml) <= VOLUME_TOLERANCE * max(a.ml, b.ml)


def parse_net_contents(text: str | None) -> NetContents:
    if text is None or not text.strip():
        return NetContents()
    text = _prepare(text)

    volumes: list[Volume] = []
    previous_end = 0
    for match in _VOLUME.finditer(text):
        volume = Volume(_to_decimal(match["num"]), _UNIT_GROUPS[str(match.lastgroup)])
        last = volumes[-1] if volumes else None
        if (
            last is not None
            and last.unit in (PINT, QUART)
            and volume.unit == FL_OZ
            and not text[previous_end : match.start()].strip()
        ):
            # "1 PINT 0.9 FL OZ" is a single volume: 16.9 fl oz.
            volumes[-1] = Volume(from_ml(last.ml, FL_OZ) + volume.value, FL_OZ)
        else:
            volumes.append(volume)
        previous_end = match.end()
    if not volumes:
        if _BARE_OUNCES.search(text):
            return NetContents(
                problem='"oz" could mean weight or volume; net contents must be in fluid ounces '
                '("fl oz") or metric units.'
            )
        return NetContents(problem="Couldn't read a volume with a unit (mL, cL, L or fl oz).")
    if any(volume.value <= 0 for volume in volumes):
        return NetContents(problem="A volume of zero is not possible.")
    first = volumes[0]
    if any(not same_volume(first, other) for other in volumes[1:]):
        listed = ", ".join(str(volume) for volume in volumes)
        return NetContents(problem=f"The text states different volumes: {listed}.")
    return NetContents(volume=first)

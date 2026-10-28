"""Filling the application form from pasted text.

Agents copy application details from COLAs Online, a printout or an email, so the text is
usually labeled lines ("Brand Name: OLD TOM DISTILLERY") in whatever wording that source uses.
A value may continue on the following lines, as an address does. JSON works too. Only what is
recognised is filled in; everything is still checked and shown to the agent before use.
"""

import json
import re
from dataclasses import dataclass, field

from app.web.forms import FIELDS, beverage_from, yes_no

MAX_PASTE_CHARS = 20_000

# Label wordings, after lowercasing and keeping only letters, digits and single spaces.
ALIASES: dict[str, tuple[str, ...]] = {
    "beverage_type": (
        "type of product", "product type", "beverage type", "type", "class of product",
    ),
    "imported": ("imported", "import", "source of product", "source"),
    "brand_name": ("brand name", "brand"),
    "fanciful_name": ("fanciful name", "fanciful"),
    "class_type": (
        "class type", "class and type", "class type designation", "class", "type designation",
    ),
    "alcohol_content": ("alcohol content", "alcohol", "abv", "alc vol", "alcohol by volume"),
    "net_contents": ("net contents", "net content", "contents", "net volume", "volume"),
    "bottler": (
        "name and address", "name and address of applicant", "applicant name and address",
        "name address", "bottler", "bottled by", "bottler or importer", "importer", "producer",
        "applicant",
    ),
    "country_of_origin": ("country of origin", "country", "origin"),
}  # fmt: skip
_BY_ALIAS = {alias: name for name, aliases in ALIASES.items() for alias in aliases}
for _name in FIELDS:
    _BY_ALIAS.setdefault(_name.replace("_", " "), _name)

_LABELED = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 /&().'-]{0,60}?)\s*(?::|=|\s-\s|\s\N{EN DASH}\s)\s*(.*)$"
)


class PasteTooLong(ValueError):
    """The pasted text is longer than any application."""


@dataclass(frozen=True)
class ParsedApplication:
    values: dict[str, str]  # form field -> value, only for what was recognised
    filled: list[str] = field(default_factory=list)  # form fields filled, in order
    missing: list[str] = field(default_factory=list)  # form fields the text didn't give
    unrecognised: list[str] = field(default_factory=list)  # labels that matched no field


def parse_application_text(text: str) -> ParsedApplication:
    if len(text) > MAX_PASTE_CHARS:
        raise PasteTooLong(
            "That's longer than any application; paste just the application details."
        )
    raw = _from_json(text)
    unrecognised: list[str] = []
    if raw is None:
        raw, unrecognised = _from_lines(text)

    values: dict[str, str] = {}
    for name, value in raw.items():
        cleaned = _normalise(name, value)
        if cleaned is not None:
            values[name] = cleaned
    filled = [name for name in FIELDS if name in values]
    missing = [name for name in FIELDS if name not in values and name != "imported"]
    return ParsedApplication(values, filled, missing, unrecognised)


def header_field(label: str) -> str | None:
    """The form field a label or column header means, in any of its common wordings."""
    return _BY_ALIAS.get(_key(label))


def _key(label: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", label.casefold()).split())


def _from_json(text: str) -> dict[str, str] | None:
    if not text.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    found: dict[str, str] = {}
    for label, value in data.items():
        name = _BY_ALIAS.get(_key(str(label)))
        if name is None or value is None or isinstance(value, dict | list):
            continue
        found.setdefault(name, "yes" if value is True else "no" if value is False else str(value))
    return found


def _from_lines(text: str) -> tuple[dict[str, str], list[str]]:
    found: dict[str, list[str]] = {}
    unrecognised: list[str] = []
    current: str | None = None  # the field a label with no value is waiting to collect
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _LABELED.match(line)
        name = _BY_ALIAS.get(_key(match.group(1))) if match else None
        if match and name is not None:
            value = match.group(2).strip()
            current = None if value else name
            if name not in found:
                found[name] = [value] if value else []
        elif match and not _continues(line):
            unrecognised.append(match.group(1).strip())
            current = None
        elif current is not None:
            found[current].append(line.strip())
    return {name: ", ".join(parts) for name, parts in found.items() if parts}, unrecognised


def _continues(line: str) -> bool:
    """A line that reads as part of a value (an address line), though it has a colon or dash."""
    return bool(re.match(r"^\s*\d", line))


def _normalise(name: str, value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if name == "beverage_type":
        return beverage_from(value)
    if name == "imported":
        answer = yes_no(value)
        return None if answer is None else ("on" if answer else "")
    return value

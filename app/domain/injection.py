"""Tripwire for label text that addresses an AI system instead of a person.

Real labels have no reason to talk to an AI, so text like "ignore previous instructions" is a
strong sign of a prompt-injection attempt. Matching runs on a squashed copy of the text: hidden
tag characters are decoded, look-alike letters are mapped to Latin, and only letters and digits
are kept. Spacing, punctuation, case and invisible characters therefore can't disguise a phrase.

This is an alarm, not a wall. Paraphrases and other languages get past it, so nothing else in
the design depends on it: the reader only transcribes, and code makes every decision.
"""

import re
import unicodedata

from app.domain.normalize import latinize, reveal_tags

_ACTOR = r"(?:mark|report|treat|classify|flag)"
_TARGET = r"(?:this|the|it)"
_OBJECT = r"(?:label|product|bottle|application)"

# Bounded repetition only, so no input can make these backtrack for long.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore previous instructions",
        re.compile(
            r"(?:ignore|disregard|override|bypass)(?:all|any|the|your|of|my){0,3}"
            r"(?:previous|prior|above|earlier|preceding|existing|other){0,2}"
            r"(?:instructions?|prompts?|directions)"
        ),
    ),
    ("ignore the above", re.compile(r"(?:ignore|disregard)(?:all|everything)?(?:the)?above")),
    ("system prompt", re.compile(r"systemprompt")),
    ("new instructions", re.compile(r"newinstructions")),
    (
        "you are an AI",
        re.compile(r"youare(?:now)?(?:an|a)?(?:ai|assistant|chatbot|languagemodel|llm)"),
    ),
    (
        "mark this label as compliant",
        re.compile(
            rf"{_ACTOR}{_TARGET}?{_OBJECT}?as(?:compliant|approved|passing|passed|pass|matching|valid)"
            rf"|{_ACTOR}{_TARGET}{_OBJECT}?(?:compliant|approved|passing)"
        ),
    ),
    (
        "this label is compliant",
        re.compile(r"(?:this|the)label(?:is|has)(?:been)?(?:compliant|approved|verified)"),
    ),
    ("verdict: pass", re.compile(r"verdict(?:is|to|as)?(?:pass|matches|compliant|approved)")),
    ("do not report this", re.compile(r"donot(?:report|mention|flag|transcribe|read)")),
)


def _squash(text: str) -> str:
    text = latinize(unicodedata.normalize("NFKC", reveal_tags(text))).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def injection_phrases(*texts: str | None) -> list[str]:
    """Names of the tripwire phrases found in any of `texts`, each listed once."""
    squashed = [_squash(text) for text in texts if text]
    return [name for name, pattern in _PATTERNS if any(pattern.search(s) for s in squashed)]

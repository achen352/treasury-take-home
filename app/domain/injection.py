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
    # The same ideas in other languages seen on imported labels. Still not exhaustive.
    (
        "ignore the instructions (Spanish)",
        re.compile(
            r"(?:ignora|ignorar|ignore|omite|omitir)(?:todas)?(?:las)?(?:instrucciones|indicaciones)"
        ),
    ),
    (
        "mark as approved (Spanish)",
        re.compile(
            r"(?:marca|marcar|reporta|reportar|considera)(?:esta|la)?(?:etiqueta)?como"
            r"(?:conforme|aprobada|aprobado|v[aá]lida|correcta)"
        ),
    ),
    (
        "ignore the instructions (Chinese)",
        re.compile(
            r"(?:忽略|忽視|忽视|无视|無視)(?:之前|以前|以上|上述|前面|先前)?的?(?:所有|全部)?的?"
            r"(?:指令|指示|说明|說明|提示)"
        ),
    ),
    ("system prompt (Chinese)", re.compile(r"(?:系统|系統)提示")),
    (
        "mark as compliant (Chinese)",
        re.compile(r"(?:标记|標記|报告|報告|视为|視為)(?:为|為)?(?:合规|合規|已批准|通过|通過)"),
    ),
    (
        "ignore the instructions (Korean)",
        re.compile(
            r"(?:이전|모든|위의|앞의)?(?:지시|지침|명령|안내)(?:사항)?(?:을|를|은|는)?(?:모두|전부)?무시"
        ),
    ),
    ("system prompt (Korean)", re.compile(r"시스템프롬프트")),
    (
        "ignore the instructions (Japanese)",
        re.compile(
            r"(?:以前|前|上記|これまで|すべて)?の?(?:指示|命令|指令)(?:を|は)?(?:すべて)?無視"
        ),
    ),
    ("system prompt (Japanese)", re.compile(r"システムプロンプト")),
)


def _squash(text: str) -> str:
    text = latinize(unicodedata.normalize("NFKC", reveal_tags(text))).casefold()
    return "".join(ch for ch in text if ch.isalnum())


def injection_phrases(*texts: str | None) -> list[str]:
    """Names of the tripwire phrases found in any of `texts`, each listed once."""
    squashed = [_squash(text) for text in texts if text]
    return [name for name, pattern in _PATTERNS if any(pattern.search(s) for s in squashed)]

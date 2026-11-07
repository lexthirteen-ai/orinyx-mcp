"""The identifiable-patient screen, run by `orinyx observe` before anything is sent.

A copy of the Orinyx API's list (the API's identifier screen is the source of truth; its
version is SCREEN_PATTERNS_SHA256, and `patterns_for` checks it against the API's):
identifier-shaped tokens that must not reach the API, which keeps claim text in its audit
record. A hit refuses the request and names the pattern, never the text it matched. This is
a pre-flight refusal, not verdict logic: nothing here decides a result.
"""

import logging
import re
from collections.abc import Iterable

logger = logging.getLogger("orinyx_mcp.contract")

Patterns = tuple[tuple[str, re.Pattern[str]], ...]

SCREEN_PATTERNS: Patterns = (
    # Widened on 2026-10-21 to formats the screen missed, and narrowed the same night:
    # (555) 123-4567; a dashed date with a real day and month
    # and a FOUR-digit year ("03-04-1962"; "10-15-20 units" and "30-20-10 mg" are stepped
    # doses); a dotted date with a real day and month, its two-digit year only when no dose
    # unit follows ("3.4.62" yes, "12.5.25 mg" no); and MR#/MRN# in capitals ("Mr #2" is a
    # title). A spaced SSN was dropped: "CBC 140 40 1000" is a lab line. Measured with zero hits
    # over 35,416 strings of the repo's data and the KB's label text. Pinned by the MCP contract.
    ("phone", re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b|\(\d{3}\)\s?\d{3}[-. ]\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "date",
        re.compile(
            r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
            r"|(?<![\d.])(?:0?[1-9]|[12]\d|3[01])-(?:0?[1-9]|[12]\d|3[01])-\d{4}(?![\d.-])"
            r"|(?<![\d.])(?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|[12]\d|3[01])\."
            r"(?:\d{4}(?![\d.-])|\d{2}(?![\d.-])(?![ \t]*(?:units?|iu|mg|mcg|g|ml|meq|mmol)\b))",
            re.I,
        ),
    ),
    ("long_number", re.compile(r"\b\d{7,}\b")),
    ("mrn", re.compile(r"\bMRN\b|(?-i:\bMRN?[ \t]?#)", re.I)),
)


def pattern_spec(patterns: Patterns = SCREEN_PATTERNS) -> list[list]:
    """A pattern list as data: [name, regex source, int(flags)] in screening order."""
    return [[name, pattern.pattern, int(pattern.flags)] for name, pattern in patterns]


# contract.digest(pattern_spec()): the version of this copy. Editing SCREEN_PATTERNS means
# updating this too (a test holds the two together).
SCREEN_PATTERNS_SHA256 = "6e1a521df99b554a9822b772286cacafa7ee9a7d4a5e6873d2cf411bd530a0e9"


def screen_strings(texts: Iterable[str | None], patterns: Patterns = SCREEN_PATTERNS) -> str | None:
    """None when every string passes; otherwise the name of the first pattern that hit."""
    for text in texts:
        if not text:
            continue
        for name, pattern in patterns:
            if pattern.search(text):
                return name
    return None


# The dose exemption, mirrored from the engine's identifier refusal: a 7+ digit number
# followed on the same line by a COUNT unit is a dose ("penicillin G 5000000 units IM",
# "interferon 3000000 international units"), not a record number; mass and volume units never
# exempt. Only the long-number rule relents; every other pattern reads the whole order. Not part
# of the pinned contract (the engine's copy lives outside SCREEN_PATTERNS too).
_COUNT_UNIT = r"(?:international[ \t]+units?|usp[ \t]+units?|million[ \t]+units?|units?|iu|miu|mu)"
_LONG_NUMBER_NOT_A_DOSE = re.compile(rf"\b\d{{7,}}\b(?![ \t]?{_COUNT_UNIT}(?![A-Za-z]))", re.I)


def screen_orders(orders: Iterable[str | None], patterns: Patterns = SCREEN_PATTERNS) -> str | None:
    """`screen_strings` for order text, with the long-number dose exemption."""
    for text in orders:
        if not text:
            continue
        for name, pattern in patterns:
            if name == "long_number":
                if _LONG_NUMBER_NOT_A_DOSE.search(text):
                    return name
            elif pattern.search(text):
                return name
    return None


class StaleScreenError(ValueError):
    """The API's screen is not this copy, and the API did not say what it is instead."""


_ALLOWED_FLAGS = int(re.IGNORECASE | re.MULTILINE | re.DOTALL | re.VERBOSE | re.UNICODE | re.ASCII)
_NAME_RE = re.compile(r"[a-z0-9_]{1,40}")


def _served(document: dict) -> Patterns | None:
    from orinyx_mcp.contract import _MAX_PATTERN_CHARS, _MAX_PATTERNS

    items = document.get("patterns")
    if not isinstance(items, list) or not 0 < len(items) <= _MAX_PATTERNS:
        return None
    patterns = []
    try:
        for item in items:
            name, source, flags = item["name"], item["pattern"], item.get("flags", 0)
            if not (
                isinstance(name, str)
                and _NAME_RE.fullmatch(name)
                and isinstance(source, str)
                and 0 < len(source) <= _MAX_PATTERN_CHARS
                and isinstance(flags, int)
                and not isinstance(flags, bool)
                and flags & ~_ALLOWED_FLAGS == 0
            ):
                return None
            patterns.append((name, re.compile(source, flags)))
    except (KeyError, TypeError, re.error):
        return None
    return tuple(patterns)


def patterns_for(client) -> Patterns:
    """The patterns to screen with: this copy when it is the API's (or when the API cannot
    say: offline, or no such endpoint, logged), the API's own list when it serves one this
    copy differs from. Raises StaleScreenError when the API's screen is known to differ but
    was not served, rather than screen with a list known to be stale."""
    from orinyx_mcp import contract

    cache = getattr(client, "_contract_cache", None)
    if cache is not None and "screen_patterns" in cache:
        return cache["screen_patterns"]
    status, document = contract.fetch(client, contract.SCREEN_PATTERNS_PATH)
    patterns, settled = SCREEN_PATTERNS, status == "absent"
    if status == "served":
        served = _served(document)
        served_sha = contract._served_sha256(document)
        if served is not None:
            settled = True
            if pattern_spec(served) != pattern_spec():
                logger.warning(
                    "identifier screen drifted: this package's copy (%s) differs from the "
                    "API's (%s); screening with the API's patterns. Update orinyx-mcp.",
                    SCREEN_PATTERNS_SHA256[:12],
                    contract.digest(pattern_spec(served))[:12],
                )
                patterns = served
        elif served_sha is not None:
            settled = True
            if served_sha != SCREEN_PATTERNS_SHA256:
                logger.warning(
                    "identifier screen drifted: this package's copy (%s) is not the API's "
                    "(%s). Update orinyx-mcp.",
                    SCREEN_PATTERNS_SHA256[:12],
                    served_sha[:12],
                )
                raise StaleScreenError(
                    "this orinyx-mcp's identifier screen is older than the API's. Nothing "
                    "was sent. Update orinyx-mcp."
                )
        else:
            logger.warning(
                "the API's %s answer has an unexpected shape; screening with this package's "
                "copy, unverified",
                contract.SCREEN_PATTERNS_PATH,
            )
    if settled and cache is not None:
        cache["screen_patterns"] = patterns
    return patterns

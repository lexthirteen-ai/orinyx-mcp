"""The identifiable-patient screen, run by `orinyx observe` before anything is sent.

A copy of the Orinyx API's list (the API's identifier screen is the source of truth):
identifier-shaped tokens that must not reach the API, which keeps claim text in its audit
record. A hit refuses the request and names the pattern, never the text it matched. This is
a pre-flight refusal, not verdict logic: nothing here decides a result.
"""

import re
from collections.abc import Iterable

SCREEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
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


def screen_strings(texts: Iterable[str | None]) -> str | None:
    """None when every string passes; otherwise the name of the first pattern that hit."""
    for text in texts:
        if not text:
            continue
        for name, pattern in SCREEN_PATTERNS:
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


def screen_orders(orders: Iterable[str | None]) -> str | None:
    """`screen_strings` for order text, with the long-number dose exemption."""
    for text in orders:
        if not text:
            continue
        for name, pattern in SCREEN_PATTERNS:
            if name == "long_number":
                if _LONG_NUMBER_NOT_A_DOSE.search(text):
                    return name
            elif pattern.search(text):
                return name
    return None

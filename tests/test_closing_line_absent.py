"""The reassuring closing line must be ABSENT whenever a run holds an abstain or an unreadable row
(2026-10-18: the line prints only when zero abstain AND zero unreadable rows). The finding
behind it was exactly an abstention arriving beside no-issue language.

The negative tests are the permanent guard now that the closing-line change has landed.
The control test (a run of supported rows only keeps the line in both forms) holds as well.

Fixtures are built here, not imported, so the file reads the same wherever it lands."""

import pytest
from orinyx_mcp.text import render_run_table, render_run_text

CLOSING_LINE_TABLE = "No claim was found to contradict its label."
CLOSING_LINE_PLAIN = "FLAGS (0): no claim was found to contradict its label."

CITATION = {
    "source": "openFDA",
    "section": "Dosage and Administration (§2)",
    "sourceId": "abc-123",
    "citation": "Coumadin prescribing information",
    "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123",
}
SUPPORTED = {
    "rawText": "warfarin 5 mg daily",
    "drug": "warfarin",
    "claimType": "dose_range",
    "verdict": "supported",
    "severity": "none",
    "explanation": "Dose 5.0 mg falls within the labeled range 2.0–10.0 mg.",
    "citation": CITATION,
}
ABSTAIN = {
    "rawText": "Acetaminophen 1500 mg by mouth every 4 hours",
    "drug": "Acetaminophen",
    "claimType": "dose_range",
    "verdict": "abstain",
    "severity": "none",
    "explanation": (
        "Dose 1500.0 mg is not within any extracted labeled range and no explicitly stated "
        "maximum is exceeded; abstaining (range extraction is not exhaustive)."
    ),
    "citation": None,
}
UNREADABLE = {
    "rawText": "wafarin 5 mb by intramuscular injection",
    "drug": "wafarin",
    "claimType": "dose_range",
    "verdict": "unreadable",
    "severity": "none",
    "explanation": "The order cannot be read as written: 'mb' is not a recognised dose unit. ...",
    "citation": None,
    "unreadableFacets": [
        {"facet": "unit", "value": "mb", "reason": "'mb' is not a recognised dose unit"}
    ],
}
# The pre-2026-10-06 abstain wording the renderer still classifies as unreadable
# (`_legacy_unreadable`): a marker string inside an `abstain` row.
LEGACY_UNREADABLE = {
    "rawText": "Warfarin 5 md by mouth daily",
    "drug": "Warfarin",
    "claimType": "dose_range",
    "verdict": "abstain",
    "severity": "none",
    "explanation": (
        "'md' is not a recognised dose unit; the claim cannot be checked as written. Abstaining."
    ),
    "citation": None,
}


def _run(*rows: dict) -> dict:
    """A run whose aggregate counts the rows as the engine would (no flags in any case here)."""
    return {
        "runId": "7a1c0e55-0000-4000-8000-00000000014b",
        "aggregate": {
            "total": len(rows),
            "supported": sum(r["verdict"] == "supported" for r in rows),
            "contradicted": 0,
            "abstain": sum(r["verdict"] == "abstain" for r in rows),
            "unreadable": sum(r["verdict"] == "unreadable" for r in rows),
        },
        "verdicts": list(rows),
    }


UNCHECKED_RUNS = [
    pytest.param(_run(SUPPORTED, ABSTAIN), id="supported+abstain"),
    pytest.param(_run(UNREADABLE, SUPPORTED), id="unreadable+supported"),
    pytest.param(_run(LEGACY_UNREADABLE, SUPPORTED), id="legacy-unreadable+supported"),
]


@pytest.mark.parametrize("run", UNCHECKED_RUNS)
def test_the_table_form_never_says_no_claim_contradicted_when_a_row_was_not_checked(run):
    assert CLOSING_LINE_TABLE not in render_run_table(run)


@pytest.mark.parametrize("run", UNCHECKED_RUNS)
def test_the_plain_form_never_says_no_claim_contradicted_when_a_row_was_not_checked(run):
    assert CLOSING_LINE_PLAIN not in render_run_text(run)


def test_a_run_of_supported_rows_only_keeps_the_closing_line_in_both_forms():
    """The positive pin: zero abstain and zero unreadable → the line still prints (both before
    and after the closing-line change)."""
    run = _run(SUPPORTED)
    assert CLOSING_LINE_TABLE in render_run_table(run)
    assert CLOSING_LINE_PLAIN in render_run_text(run)

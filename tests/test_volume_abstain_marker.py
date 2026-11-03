"""MCP marker check: the engine's new
abstain sentence for a volume dose without a concentration must not trip the MCP's
`_UNREADABLE_MARKERS`, or every MCP client would re-label the row "UNREADABLE - do not act on
it". Test only; no MCP source change."""

from orinyx_mcp.text import (
    UNREADABLE_LABEL,
    _legacy_unreadable,
    _sorted,
    _unreadable,
    render_run_table,
    render_run_text,
)

from tests.test_text import RUN

# verify.py, the `unit_norm == "mL"` arm, rendered for `Lisinopril 10 mL by mouth once daily`.
VOLUME_SENTENCE = (
    "The order gives a volume (10.0 mL); a volume in mL can be compared with the label's dose "
    "rules only with the product's concentration in milligrams per millilitre, and the order "
    "states none; abstaining."
)
MARKERS = ("cannot be checked as written", "is not a recognised dose unit")
ROW = {
    "rawText": "Lisinopril 10 mL by mouth once daily",
    "drug": "Lisinopril",
    "claimType": "dose_range",
    "verdict": "abstain",
    "severity": "none",
    "explanation": VOLUME_SENTENCE,
    "citation": None,
}
VOLUME_RUN = {
    **RUN,
    "verdicts": [*RUN["verdicts"], ROW],
    "aggregate": {"total": 4, "supported": 1, "contradicted": 1, "abstain": 2},
}


def test_the_sentence_contains_neither_marker():
    assert not any(marker in VOLUME_SENTENCE for marker in MARKERS)
    assert "mL" in VOLUME_SENTENCE and "concentration" in VOLUME_SENTENCE
    assert "mg" not in VOLUME_SENTENCE


def test_legacy_unreadable_is_false_for_the_volume_row():
    assert _legacy_unreadable(ROW) is False
    assert _unreadable(ROW) is False


def test_the_row_renders_among_the_abstained_rows_not_under_the_unreadable_label():
    text = render_run_table(VOLUME_RUN)
    row = next(line for line in text.splitlines() if "Lisinopril 10 mL" in line)
    assert "NOT VERIFIED (abstain)" in row and UNREADABLE_LABEL not in row
    assert "do not act" not in text.lower()
    assert "Checked 4 claims: 1 flagged, 1 supported, 2 abstained." in text
    plain = render_run_text(VOLUME_RUN)
    assert "UNREADABLE AS WRITTEN" not in plain and "ABSTAINED (2)" in plain
    assert "Why not: " + VOLUME_SENTENCE in plain


def test_the_legacy_count_is_unchanged():
    head, unreadable, flags, supported, abstained = _sorted(VOLUME_RUN)
    assert unreadable == [] and len(abstained) == 2
    assert sum(1 for v in unreadable if v.get("verdict") == "abstain") == 0  # `legacy`
    assert "unreadable as written" not in head[1]

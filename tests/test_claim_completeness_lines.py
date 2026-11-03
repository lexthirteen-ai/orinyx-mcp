"""Claim completeness, MCP half: `render_run_table` appends the engine's `orders[].unparsed`/
`notes` and the knowledge-coverage line as NEW lines after the footer. Every line rendered before
this change is produced unchanged, in the same order: the pre-change rendering is an exact PREFIX
of the post-change rendering (the readable-text rule: readable text stays byte-identical), and a
run with nothing to add renders byte for byte.

LANDING ORDER (2026-10-18): the closing-line change landed FIRST (pre-launch), the text change
after it. The committed strings below are the pre-change rendering of THAT base: orinyx-mcp
91bf1f7 + the closing-line change, before the text change (rendered through orinyx_mcp.text in
a fresh clone, 2026-10-18). This file is evidence only in that order. Against 91bf1f7 + the
text change alone it FAILS, by design: `NOT_VERIFIED_LEAD` does not exist there, and the three
fixtures with no flag and an unchecked row carry the lead, not the old closing line. The
compute-at-test-time checks at the end depend on no committed string at all."""

import pytest
from orinyx_mcp.text import (
    FOOTER,
    NOT_VERIFIED_LEAD,
    _legacy_unreadable,
    _sorted,
    render_run_table,
    render_run_text,
)

from tests.test_client import RUN_JSON
from tests.test_text import ACCURACY, RUN, UNREADABLE_RUN

SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE = {
    "client.RUN_JSON/table": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.0)\n"
        "Checked 1 claims: 1 flagged, 0 supported, 0 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | warfarin 20 mg daily | dose | FLAGGED | MODERATE | too much | INCOMPLETE "
        "- do not rely on this verdict |\n"
        "\n"
        "Why each severity:\n"
        "Row 1 (MODERATE): Rated Moderate because ...\n"
        "\n"
        "FLAGGED: the cited label says otherwise, at the severity shown.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "client.RUN_JSON/text": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.0)\n"
        "Checked 1 claims: 1 flagged, 0 supported, 0 abstained.\n"
        "\n"
        "FLAGS (1)\n"
        "1. [MODERATE] warfarin 20 mg daily (dose)\n"
        "   Why: too much\n"
        "   Severity: Rated Moderate because ...\n"
        "   Citation: INCOMPLETE - do not rely on this verdict\n"
        "\n"
        "SUPPORTED (0)\n"
        "\n"
        "ABSTAINED (0)\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.RUN/table": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 3 claims: 1 flagged, 1 supported, 1 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | warfarin 20 mg daily | dose | FLAGGED | MODERATE | Dose 20 mg exceeds the "
        "explicitly stated maximum of 10 mg. | [1] |\n"
        "| 2 | warfarin 5 mg daily | dose | SUPPORTED | - | Within the labelled range. | "
        "INCOMPLETE - do not rely on this verdict |\n"
        "| 3 | warfarin for migraine | indication | NOT VERIFIED (abstain) | - | The "
        "label does not address this indication. | - |\n"
        "\n"
        "Citations:\n"
        "[1] openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin prescribing "
        "information - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123\n"
        "\n"
        "Why each severity:\n"
        "Row 1 (MODERATE): Rated Moderate because a dose above the label's stated "
        "maximum is Moderate under Orinyx's fixed rule for dose claims.\n"
        "\n"
        "FLAGGED: the cited label says otherwise, at the severity shown.\n"
        "SUPPORTED: consistent with the cited label text; not a judgment that the order "
        "suits a patient.\n"
        "NOT VERIFIED: Orinyx could not check these, which does not mean they are "
        "correct.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.RUN/table+ACCURACY": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 3 claims: 1 flagged, 1 supported, 1 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | warfarin 20 mg daily | dose | FLAGGED | MODERATE | Dose 20 mg exceeds the "
        "explicitly stated maximum of 10 mg. | [1] |\n"
        "| 2 | warfarin 5 mg daily | dose | SUPPORTED | - | Within the labelled range. | "
        "INCOMPLETE - do not rely on this verdict |\n"
        "| 3 | warfarin for migraine | indication | NOT VERIFIED (abstain) | - | The "
        "label does not address this indication. | - |\n"
        "\n"
        "Citations:\n"
        "[1] openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin prescribing "
        "information - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123\n"
        "\n"
        "Why each severity:\n"
        "Row 1 (MODERATE): Rated Moderate because a dose above the label's stated "
        "maximum is Moderate under Orinyx's fixed rule for dose claims.\n"
        "\n"
        "FLAGGED: the cited label says otherwise, at the severity shown.\n"
        "SUPPORTED: consistent with the cited label text; not a judgment that the order "
        "suits a patient.\n"
        "NOT VERIFIED: Orinyx could not check these, which does not mean they are "
        "correct.\n"
        "\n"
        "ACCURACY (physician review)\n"
        "  False-flag rate 0.0% (0 of 1 flags; 0 of 1 carry a physician override, the "
        "rest stand)\n"
        "  Severity corrections 1 / Other overrides 0\n"
        "  Catch rate not estimated (miss review incomplete)\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.RUN/text": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 3 claims: 1 flagged, 1 supported, 1 abstained.\n"
        "\n"
        "FLAGS (1)\n"
        "1. [MODERATE] warfarin 20 mg daily (dose)\n"
        "   Why: Dose 20 mg exceeds the explicitly stated maximum of 10 mg.\n"
        "   Severity: Rated Moderate because a dose above the label's stated maximum is "
        "Moderate under Orinyx's fixed rule for dose claims.\n"
        "   Citation: openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin "
        "prescribing information - "
        "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123\n"
        "\n"
        "SUPPORTED (1) - consistent with the cited label text; not a judgment that the "
        "order suits a patient:\n"
        "1. warfarin 5 mg daily (dose)\n"
        "   Citation: INCOMPLETE - do not rely on this verdict\n"
        "\n"
        "ABSTAINED (1) - NOT VERIFIED; Orinyx could not check these, which does not mean "
        "they are correct:\n"
        "1. warfarin for migraine (indication)\n"
        "   Why not: The label does not address this indication.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.UNREADABLE_RUN/table": (
        "Orinyx verification - run 7a1c0e55\n"
        "Checked 2 claims: 0 flagged, 2 unreadable as written, 0 supported, 0 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | wafarin 5 mb by intramuscular injection | dose | UNREADABLE - do not act "
        "on it | - | 'wafarin' is not a drug name Orinyx recognises; 'mb' is not a "
        "recognised dose unit | - |\n"
        "| 2 | wafarin 5 mb by intramuscular injection | route | UNREADABLE - do not act "
        "on it | - | 'wafarin' is not a drug name Orinyx recognises | - |\n"
        "\n"
        "Possible intended (for the clinician to confirm; Orinyx did not check the order "
        "under any of these):\n"
        "Row 1, drug 'wafarin': warfarin\n"
        "Row 1, unit 'mb': mL or mg\n"
        "Row 2, drug 'wafarin': warfarin\n"
        "\n"
        "UNREADABLE: these orders cannot be read as written. Do not act on them until "
        "the clinician clarifies them; Orinyx did not check them against any label. "
        "Never assume a correction (a name or unit Orinyx cannot read is not a typo "
        "anyone may guess at).\n"
        "NOT VERIFIED: Orinyx could not check every claim in this run, so this is not a "
        "safety clearance.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.UNREADABLE_RUN/text": (
        "Orinyx verification - run 7a1c0e55\n"
        "Checked 2 claims: 0 flagged, 2 unreadable as written, 0 supported, 0 abstained.\n"
        "\n"
        "UNREADABLE AS WRITTEN (2) - do not act on these until the clinician clarifies "
        "them; Orinyx did not check them against any label, and a correction must never "
        "be assumed:\n"
        "1. wafarin 5 mb by intramuscular injection (dose)\n"
        "   Why: 'wafarin' is not a drug name Orinyx recognises; 'mb' is not a "
        "recognised dose unit\n"
        "2. wafarin 5 mb by intramuscular injection (route)\n"
        "   Why: 'wafarin' is not a drug name Orinyx recognises\n"
        "Possible intended (for the clinician to confirm; Orinyx did not check the order "
        "under any of these):\n"
        "   Unreadable 1, drug 'wafarin': warfarin\n"
        "   Unreadable 1, unit 'mb': mL or mg\n"
        "   Unreadable 2, drug 'wafarin': warfarin\n"
        "\n"
        "FLAGS (0) - NOT VERIFIED: Orinyx could not check every claim in this run, so "
        "this is not a safety clearance.\n"
        "\n"
        "SUPPORTED (0)\n"
        "\n"
        "ABSTAINED (0)\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.clean(1 supported,1 abstain)/text": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 2 claims: 0 flagged, 1 supported, 1 abstained.\n"
        "\n"
        "FLAGS (0) - NOT VERIFIED: Orinyx could not check every claim in this run, so "
        "this is not a safety clearance.\n"
        "\n"
        "SUPPORTED (1) - consistent with the cited label text; not a judgment that the "
        "order suits a patient:\n"
        "1. warfarin 5 mg daily (dose)\n"
        "   Citation: INCOMPLETE - do not rely on this verdict\n"
        "\n"
        "ABSTAINED (1) - NOT VERIFIED; Orinyx could not check these, which does not mean "
        "they are correct:\n"
        "1. warfarin for migraine (indication)\n"
        "   Why not: The label does not address this indication.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.clean(1 supported,1 abstain)/table": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 2 claims: 0 flagged, 1 supported, 1 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | warfarin 5 mg daily | dose | SUPPORTED | - | Within the labelled range. | "
        "INCOMPLETE - do not rely on this verdict |\n"
        "| 2 | warfarin for migraine | indication | NOT VERIFIED (abstain) | - | The "
        "label does not address this indication. | - |\n"
        "\n"
        "NOT VERIFIED: Orinyx could not check every claim in this run, so this is not a "
        "safety clearance.\n"
        "SUPPORTED: consistent with the cited label text; not a judgment that the order "
        "suits a patient.\n"
        "NOT VERIFIED: Orinyx could not check these, which does not mean they are "
        "correct.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
    "text.table_clean(1 supported)/table": (
        "Orinyx verification - run 0d8b1c6e (acme-scribe 1.4.2, "
        "2026-10-04T23:10:00+00:00)\n"
        "Checked 1 claims: 0 flagged, 1 supported, 0 abstained.\n"
        "\n"
        "| # | Claim | Part | Result | Severity | Why | Citation |\n"
        "|---|---|---|---|---|---|---|\n"
        "| 1 | warfarin 5 mg daily | dose | SUPPORTED | - | Within the labelled range. | "
        "INCOMPLETE - do not rely on this verdict |\n"
        "\n"
        "No claim was found to contradict its label. This is not a safety clearance; "
        "claims not verified were not checked.\n"
        "SUPPORTED: consistent with the cited label text; not a judgment that the order "
        "suits a patient.\n"
        "\n"
        "Orinyx flags; the clinician decides."
    ),
}

CLEAN_TEXT = {
    **RUN,
    "verdicts": RUN["verdicts"][1:],
    "aggregate": {"total": 2, "supported": 1, "contradicted": 0, "abstain": 1},
}
TABLE_CLEAN = dict(RUN, verdicts=[RUN["verdicts"][1]], aggregate={"total": 1, "supported": 1})
MARKERS = ("cannot be checked as written", "is not a recognised dose unit")

# Every committed fixture, one base (91bf1f7 + the closing-line patch): rendered byte for
# byte before and after the text patch, because none carries orders[] or knowledgeCoverage.
CASES = [
    ("client.RUN_JSON/table", render_run_table, RUN_JSON, None),
    ("client.RUN_JSON/text", render_run_text, RUN_JSON, None),
    ("text.RUN/table", render_run_table, RUN, None),
    ("text.RUN/table+ACCURACY", render_run_table, RUN, ACCURACY),
    ("text.RUN/text", render_run_text, RUN, None),
    ("text.UNREADABLE_RUN/table", render_run_table, UNREADABLE_RUN, None),
    ("text.UNREADABLE_RUN/text", render_run_text, UNREADABLE_RUN, None),
    ("text.clean(1 supported,1 abstain)/text", render_run_text, CLEAN_TEXT, None),
    ("text.clean(1 supported,1 abstain)/table", render_run_table, CLEAN_TEXT, None),
    ("text.table_clean(1 supported)/table", render_run_table, TABLE_CLEAN, None),
]
CASE_IDS = [c[0] for c in CASES]


def _render(render, run, accuracy):
    return render(run, accuracy) if accuracy is not None else render(run)


def test_the_committed_base_is_the_closing_line_patch_landed_first():
    """The base these snapshots were taken from already carries the closing-line change: the
    three fixtures with no flag and an unchecked row show the NOT VERIFIED lead and never the
    old closing line; the fully-checked fixture still shows the closing line (positive pin)."""
    for key in (
        "text.UNREADABLE_RUN/table",
        "text.clean(1 supported,1 abstain)/table",
    ):
        assert NOT_VERIFIED_LEAD in SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE[key]
        assert "No claim was found to contradict" not in SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE[key]
    for key in ("text.UNREADABLE_RUN/text", "text.clean(1 supported,1 abstain)/text"):
        assert f"FLAGS (0) - {NOT_VERIFIED_LEAD}" in SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE[key]
    assert (
        "No claim was found to contradict its label."
        in SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.table_clean(1 supported)/table"]
    )


@pytest.mark.parametrize(("key", "render", "run", "accuracy"), CASES, ids=CASE_IDS)
def test_the_pre_change_rendering_is_an_exact_prefix_of_the_post_change_rendering(
    key, render, run, accuracy
):
    old = SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE[key]
    new = _render(render, run, accuracy)
    assert new[: len(old)] == old


@pytest.mark.parametrize(("key", "render", "run", "accuracy"), CASES, ids=CASE_IDS)
def test_a_run_with_nothing_to_add_renders_byte_for_byte_as_before(key, render, run, accuracy):
    """The committed fixtures carry no orders[] and no coverage field: no empty section, no
    "none" line, not one byte more."""
    old = SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE[key]
    new = _render(render, run, accuracy)
    assert new == old


def test_empty_lists_and_an_all_covered_run_add_nothing():
    run = {
        **RUN,
        "orders": [
            {"index": 0, "text": "warfarin 5 mg daily", "unparsed": [], "notes": []},
            {"index": 1, "text": "x", "unparsed": None, "notes": None},
        ],
        "knowledgeCoverage": [
            {"drug": "warfarin", "rxcui": "11289", "numericDoseRule": True, "note": None}
        ],
    }
    assert render_run_table(run) == SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.RUN/table"]
    also_none = {**RUN, "orders": None, "knowledgeCoverage": None}
    assert render_run_table(also_none) == SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.RUN/table"]


ORDERS = [
    {
        "index": 0,
        "text": "Acetaminophen 2000 mg by mouth every 4 hours",
        "unparsed": ["hours"],
        "notes": [],
    },
    {
        "index": 1,
        "text": "warfarin 5-10 mg IV",
        "unparsed": [],
        "notes": ["dose not checked: range"],
    },
    {"index": 2, "text": "warfarin 5 mg daily", "unparsed": [], "notes": []},
]
COVERAGE = [
    {"drug": "warfarin", "rxcui": "11289", "numericDoseRule": True, "note": None},
    {
        "drug": "Metformin",
        "rxcui": "6809",
        "numericDoseRule": False,
        "note": "No numeric dose-range rule covers this drug; abstaining.",
    },
]
APPENDED = (
    "\n"
    "\n"
    "Order 1: not placed: hours\n"
    "Order 2: note: dose not checked: range\n"
    "Knowledge base, Metformin: No numeric dose-range rule covers this drug; abstaining."
)
ORDERS_RUN = {**RUN, "orders": ORDERS, "knowledgeCoverage": COVERAGE}


def test_the_new_lines_follow_the_footer_in_the_engines_own_words():
    text = render_run_table(ORDERS_RUN)
    old = SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.RUN/table"]
    assert text.startswith(old)
    assert text[len(old) :] == APPENDED
    assert old.rstrip().endswith(FOOTER)  # the footer line is still the last line of the old text


def test_case_b_on_main_shows_hours_as_not_placed():
    """Reproduction (MCP half): the engine's pre-remediation JSON for case B carried
    `orders[0].unparsed == ["hours"]`, and no rendered line mentioned "hours"; now one does."""
    before = {**RUN, "orders": None}
    assert "hours" not in render_run_table(before)
    assert "Order 1: not placed: hours" in render_run_table(ORDERS_RUN)


def test_input_1s_note_is_rendered_in_the_engines_words():
    """An order carrying a second amount (the trailing "maximum 3,000 mg/day") makes
    `parse_dose` see two amounts and emit NO dose claim, with the note `dose not checked:
    multiple amounts`; the exposure branch never sees it, and
    the MCP renders the note so the reader learns why only route and schedule were checked.
    The words are the engine's own output for that input (with the engine's qualifier placed)."""
    run = {
        **RUN,
        "orders": [
            {
                "index": 0,
                "text": "Acetaminophen 500 mg orally every 6 hours as needed, maximum 3,000 mg/day",
                "unparsed": ["500", "mg", "maximum", "3", "000", "mg", "day"],
                "notes": ["dose not checked: multiple amounts"],
            }
        ],
    }
    lines = render_run_table(run).splitlines()
    assert "Order 1: note: dose not checked: multiple amounts" in lines
    assert lines[-2:] == [
        "Order 1: not placed: 500, mg, maximum, 3, 000, mg, day",
        "Order 1: note: dose not checked: multiple amounts",
    ]


def test_several_unplaced_words_and_a_pipe_are_rendered_through_cell():
    run = {
        **RUN,
        "orders": [{"index": 0, "text": "x", "unparsed": ["three", "or", "a|b"], "notes": []}],
    }
    assert render_run_table(run).endswith("\n\nOrder 1: not placed: three, or, a\\|b")


def test_the_order_number_is_the_engines_own_index_plus_one():
    run = {**RUN, "orders": [{"index": 4, "text": "x", "unparsed": ["zz"], "notes": []}]}
    assert render_run_table(run).endswith("\n\nOrder 5: not placed: zz")
    positional = {**RUN, "orders": [{"text": "x", "unparsed": ["zz"], "notes": []}]}
    assert render_run_table(positional).endswith("\n\nOrder 1: not placed: zz")


def test_the_new_lines_carry_neither_unreadable_marker_and_change_no_counts():
    text = render_run_table(ORDERS_RUN)
    old = SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.RUN/table"]
    new_lines = text[len(old) :].splitlines()
    assert new_lines and not any(m in line for m in MARKERS for line in new_lines)
    assert _sorted(ORDERS_RUN) == _sorted(RUN)  # the rows and counts are untouched
    for row in ORDERS_RUN["verdicts"]:
        assert _legacy_unreadable(row) is False


def test_the_plain_text_form_is_unchanged():
    assert render_run_text(ORDERS_RUN) == SNAPSHOTS_91BF1F7_PLUS_CLOSING_LINE["text.RUN/text"]


# --- computed at test time: the base rendering is the SAME function on the same run with
# the two lists removed, so this holds against whatever base the patch is applied to, with no
# committed string involved.


def _without_additions(run):
    return {k: v for k, v in run.items() if k not in ("orders", "knowledgeCoverage")}


@pytest.mark.parametrize(
    ("render", "run", "accuracy"),
    [(render, run, accuracy) for _, render, run, accuracy in CASES],
    ids=CASE_IDS,
)
def test_the_base_rendering_computed_at_test_time_is_an_exact_prefix(render, run, accuracy):
    with_additions = {**run, "orders": ORDERS, "knowledgeCoverage": COVERAGE}
    base = _render(render, _without_additions(with_additions), accuracy)
    new = _render(render, with_additions, accuracy)
    assert new[: len(base)] == base
    if render is render_run_table:
        assert new[len(base) :] == APPENDED
    else:
        assert new == base  # the plain-text form appends nothing

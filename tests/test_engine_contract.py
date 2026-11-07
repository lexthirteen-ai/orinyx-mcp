"""The hand-copied engine contract, pinned to a fixture the engine exports.

This client never imports the engine (tests/test_client.py enforces it) and the engine is
not installed here, so the pin is `tests/fixtures/engine_contract.json`. Its values are a
copy of the contract fixture the Orinyx API exports, which the API's own tests re-derive from
its identifier screen, its verdict engine and its label sections. Its `_note` belongs to this
copy and was reworded for publication (2026-11-02). A change on either side fails that side's
test; the maintenance step, until a shared package exists, is: change the engine, re-export
its fixture, copy the VALUES here, keep this copy's `_note`, and recompute `sha256`
(and `LABEL_SECTIONS_SHA256` / `SCREEN_PATTERNS_SHA256`). At run time `orinyx_mcp.contract`
checks the copies against the API's own lists and logs drift (tests/test_contract_drift.py)."""

import hashlib
import json
from pathlib import Path

import pytest
from orinyx_mcp import screen, text
from orinyx_mcp.client import LABEL_SECTIONS
from orinyx_mcp.text import UNREADABLE_LABEL, render_run_table

from tests.test_client import RUN_JSON

FIXTURE = Path(__file__).with_name("fixtures") / "engine_contract.json"

# Identical to the corpus in the API's own contract test: the same
# strings must trip the same pattern NAMES on both sides, not merely share pattern source.
CORPUS: tuple[tuple[str, str | None], ...] = (
    ("call 555-123-4567 after the dose", "phone"),
    ("ssn 123-45-6789 on file", "ssn"),
    ("seen 10/12/2026 in clinic", "date"),
    ("seen 2026-10-12 in clinic", "date"),
    ("acct 12345678", "long_number"),
    ("MRN pending", "mrn"),
    ("mrn: none", "mrn"),
    ("Warfarin 5 md by mouth daily", None),
    ("Acetaminophen 2000 mg by mouth every 4 hours", None),
    ("Lisinopril 10 mL by mouth once daily", None),
    # 2026-10-21: the widened formats, and the shapes they must not catch.
    ("call (555) 123-4567 after the dose", "phone"),
    ("CBC 140 40 1000", None),
    ("sliding scale 10-15-20 units", None),
    ("taper 30-20-10 mg", None),
    ("q 12.5.25 mg", None),
    ("Mr #2 in the waiting room", None),
    ("seen 03-04-1962 in clinic", "date"),
    ("seen 3.4.1962 in clinic", "date"),
    ("MR# 4471 on the label", "mrn"),
    ("hydroxypropylbetadex 0.58-0.68 mg", None),
    ("penicillin G 5000000 units IM", "long_number"),
)


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _canonical_sha256(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_the_fixture_hash_matches_and_names_the_api_export():
    fixture = _load()
    assert fixture["sha256"] == _canonical_sha256(fixture)
    assert fixture["exported_from"]["repo"] == "orinyx-engine"


def test_screen_patterns_equal_the_engines_in_name_source_flags_and_order():
    fixture = _load()
    live = {name: pattern.pattern for name, pattern in screen.SCREEN_PATTERNS}
    assert live == fixture["screen_patterns"]
    assert list(live) == list(fixture["screen_patterns"])
    assert {name: int(p.flags) for name, p in screen.SCREEN_PATTERNS} == fixture[
        "screen_pattern_flags"
    ]


@pytest.mark.parametrize(("sample", "expected"), CORPUS)
def test_the_shared_corpus_trips_the_same_pattern_name_as_the_engine(sample, expected):
    assert screen.screen_strings([sample]) == expected


def test_label_sections_equal_the_engines_nine_names_in_order():
    assert list(LABEL_SECTIONS) == _load()["label_sections"]


def test_unreadable_markers_are_exactly_the_engines_two_substrings():
    assert set(text._UNREADABLE_MARKERS) == set(_load()["unreadable_markers"])
    assert len(text._UNREADABLE_MARKERS) == 2


def test_the_engines_own_wording_is_what_relabels_a_legacy_abstain_unreadable():
    """The fixture carries the exact reason strings the engine produces for 'Warfarin 5 md';
    both must make the table show the row as unreadable, so a rewording on the engine side
    breaks this test here, not silently in an agent's output."""
    witnesses = _load()["unreadable_marker_witnesses"]
    for explanation in witnesses.values():
        row = dict(RUN_JSON["verdicts"][0])
        row.update(
            rawText="Warfarin 5 md by mouth daily",
            verdict="abstain",
            severity="none",
            explanation=explanation,
            citation=None,
            matchedRuleId=None,
        )
        run = dict(RUN_JSON, verdicts=[row])
        run["aggregate"] = {"total": 1, "supported": 0, "contradicted": 0, "abstain": 1}
        rendered = render_run_table(run)
        if text._legacy_unreadable(row):
            assert UNREADABLE_LABEL in rendered, explanation
        else:
            # The readability facet reason alone has no 'cannot be checked' phrase but does
            # carry the unit marker; the engine test proves it is real output.
            assert any(m in explanation for m in text._UNREADABLE_MARKERS), explanation
            assert UNREADABLE_LABEL in rendered, explanation


def test_a_volume_abstain_is_never_relabelled_unreadable():
    """'Lisinopril 10 mL' abstains (2026-10-06); its wording must not match a marker or every
    client would tell the agent 'do not act on it'."""
    for explanation in (
        "No dose-range rule uses a unit comparable to 'mL'; abstaining.",
        "No numeric dose-range rule covers this drug; abstaining.",
    ):
        row = {"verdict": "abstain", "explanation": explanation}
        assert not text._legacy_unreadable(row), explanation


def test_the_observe_pre_check_allows_a_dose_unit_after_a_long_number():
    """The CLI agrees with the engine's identifier refusal on a dose after a long number. The pinned
    screen_strings still names long_number for the same text; the order pre-check does not."""
    from orinyx_mcp.screen import screen_orders

    assert screen_orders(["penicillin G 5000000 units IM"]) is None
    assert screen_orders(["heparin 10000000 IU"]) is None
    assert screen_orders(["id 5000000"]) == "long_number"
    assert screen_orders(["5000000 units, call 555-123-4567"]) == "phone"
    assert screen.screen_strings(["penicillin G 5000000 units IM"]) == "long_number"


def test_the_check_block_renders_every_name_the_engine_exports():
    """The fixture's `checks` block is the engine's. Each exported name renders on its
    own line with the engine's label; a name outside the list with no label renders raw. The
    client holds no copy of the names or labels: they reach the text only from the run."""
    block = _load()["checks"]
    assert block["checksVersion"] == 1
    names, labels = block["names"], block["labels"]
    assert set(labels) == set(names)
    rows = [
        dict(RUN_JSON["verdicts"][0], verdict="supported", check=name, relatedChecks=[])
        for name in [*names, "a_newer_check"]
    ]
    checks = [
        {
            "check": name,
            "label": labels[name],
            # Every exported status, "stable" included, renders "(beta)" in step 1.
            "status": block["statuses"][index % len(block["statuses"])],
            "rows": 1,
            "supported": 1,
            "contradicted": 0,
            "abstain": 0,
            "unreadable": 0,
        }
        for index, name in enumerate(names)
    ]
    checks.append(
        {
            "check": "a_newer_check",
            "status": "stable",
            "rows": 1,
            "supported": 1,
            "contradicted": 0,
            "abstain": 0,
            "unreadable": 0,
        }
    )
    run = dict(RUN_JSON, verdicts=rows, checks=checks, checksVersion=block["checksVersion"])
    run["aggregate"] = {"total": len(rows), "supported": len(rows), "contradicted": 0, "abstain": 0}
    lines = render_run_table(run).split("\n")
    at = lines.index(text.CHECKS_HEADING)
    expected = [
        f"{labels[name]} (beta): row {number} - 1 supported"
        for number, name in enumerate(names, start=1)
    ]
    expected.append(f"a_newer_check (beta): row {len(names) + 1} - 1 supported")
    assert lines[at + 1 :] == expected

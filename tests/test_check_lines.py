"""The "Checks (beta ...)" block.

When the engine sends a run's `checks` list, `render_run_table` and `render_run_text` end with
one block naming the beta check behind each row. It is built only from each row's `check` and
the run's `checks` entries: the name is the entry's `label` (else its raw `check`), the counts
are the entry's own, and the MCP holds no table of checks. Everything rendered before stays an
exact prefix, `Run id:` stays last in tool text, and a run without `checks` renders byte for
byte as in v0.1.1.

Evidence in fixtures, none of it typed by hand:
- `check_lines_before_v0_1_1.json`: five responses with the new fields, and what the v0.1.1
  package itself rendered for each with those fields removed (from the v0.1.1 tree).
- `check_lines_goldens.json`: the five approved wording samples (G1-G5), copied by a script,
  not by hand.
- `check_lines_g1_input.json`: the synthetic engine response that G1 and G2 render.
"""

import copy
import json
import re
import types
from pathlib import Path

import httpx
import pytest
from evals import mcp_local_check
from orinyx_mcp import cli, tools
from orinyx_mcp.client import OrinyxClient, VerificationResult
from orinyx_mcp.text import (
    CHECKS_HEADING,
    FOOTER,
    _cell,
    render_run_table,
    render_run_text,
)
from orinyx_mcp.verdicts import count_verdicts

from tests.test_client import RUN_JSON

FIXTURES = Path(__file__).with_name("fixtures")
BEFORE = json.loads((FIXTURES / "check_lines_before_v0_1_1.json").read_text(encoding="utf-8"))
CASES = BEFORE["cases"]
GOLDENS = json.loads((FIXTURES / "check_lines_goldens.json").read_text(encoding="utf-8"))
G1_INPUT = json.loads((FIXTURES / "check_lines_g1_input.json").read_text(encoding="utf-8"))[
    "response"
]
MC, SM, SE = "medication_claims", "semantic_mapping", "source_evidence"
TABLE_HEADER = "| # | Claim | Part | Result | Severity | Why | Citation |"

# The block each prefix case must end with: table form, then plain form (heading not repeated).
BLOCKS = {
    "after_2_2": (
        [
            "Medication Claims (beta): row 1 - 1 flagged",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): no rows in this run",
        ],
        [
            "Medication Claims (beta): Flags 1 - 1 flagged",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): no rows in this run",
        ],
    ),
    "completeness": (
        [
            "Medication Claims (beta): rows 1, 2 - 1 flagged, 1 supported",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): row 3 - 1 not verified",
        ],
        [
            "Medication Claims (beta): Flags 1; Supported 1 - 1 flagged, 1 supported",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): Abstained 1 - 1 not verified",
        ],
    ),
    "accuracy": (
        [
            "Medication Claims (beta): row 1 - 1 flagged",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): rows 2, 3 - 1 supported, 1 not verified",
        ],
        [
            "Medication Claims (beta): Flags 1 - 1 flagged",
            "Semantic Mapping (beta): no rows in this run",
            "Source Evidence (beta): Supported 1; Abstained 1 - 1 supported, 1 not verified",
        ],
    ),
    "unreadable": (
        [
            "Medication Claims (beta): no rows in this run",
            "Semantic Mapping (beta): rows 1, 2 - 2 unreadable",
            "Source Evidence (beta): no rows in this run",
        ],
        [
            "Medication Claims (beta): no rows in this run",
            "Semantic Mapping (beta): Unreadable 1, 2 - 2 unreadable",
            "Source Evidence (beta): no rows in this run",
        ],
    ),
}


def _golden_block(golden: str) -> list[str]:
    """The check block inside a golden: from its heading to the line before `Run id:`."""
    tail = golden[golden.index(CHECKS_HEADING) :]
    return tail.split("\n\nRun id: ")[0].split("\n")


BLOCKS["all_three"] = (_golden_block(GOLDENS["G1"])[1:], _golden_block(GOLDENS["G2"])[1:])


def _stripped(run: dict, *, keep_row_checks: bool = False) -> dict:
    run = {k: v for k, v in run.items() if k not in ("checks", "checksVersion")}
    if not keep_row_checks:
        run["verdicts"] = [
            {k: v for k, v in row.items() if k not in ("check", "relatedChecks")}
            for row in run["verdicts"]
        ]
    return run


def _entry(check, label=None, *, rows=0, supported=0, contradicted=0, abstain=0, unreadable=0):
    entry = {"check": check, "label": label, "status": "beta", "rows": rows}
    entry.update(
        supported=supported, contradicted=contradicted, abstain=abstain, unreadable=unreadable
    )
    if label is None:
        del entry["label"]
    return entry


def _row(raw, verdict, check, claim_type="dose_range", **extra):
    row = {"rawText": raw, "claimType": claim_type, "verdict": verdict, "check": check}
    if verdict == "contradicted":
        row.update(severity="moderate", explanation="over the maximum")
    if verdict in ("contradicted", "supported"):
        row["citation"] = {
            "source": "openFDA",
            "section": "Dosage and Administration (§2)",
            "sourceId": "set-1",
            "citation": "Synthetic label",
            "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=set-1",
        }
    if verdict == "unreadable":
        row["unreadableFacets"] = [{"facet": "drug", "reason": "'zzz' is not a drug name"}]
    row.update(extra)
    return row


def _run(verdicts, checks, run_id="11111111-2222-4333-8444-555555555555"):
    counts = {"supported": 0, "contradicted": 0, "abstain": 0, "unreadable": 0}
    for row in verdicts:
        key = row["verdict"] if row["verdict"] in counts else "abstain"
        counts[key] += 1
    return {
        "runId": run_id,
        "toolName": "synthetic-scribe",
        "toolVersion": "1.0",
        "aggregate": {"total": len(verdicts), **counts},
        "verdicts": verdicts,
        "checksVersion": 1,
        "checks": checks,
    }


def _block(rendered: str) -> list[str]:
    assert rendered.count(CHECKS_HEADING) == 1
    return rendered[rendered.index(CHECKS_HEADING) :].split("\n")


class _Stub:
    """Hands the response back as the client would, without its wire validation: the tool
    reads only `result.raw` (the G1 input omits fields the v0.1.1 model requires)."""

    def __init__(self, run, accuracy=None):
        self.run, self._accuracy = run, accuracy

    def verify(self, claims, **kwargs):
        return types.SimpleNamespace(raw=self.run)

    def verify_orders(self, orders, **kwargs):
        return types.SimpleNamespace(raw=self.run)

    def get_run(self, run_id):
        return types.SimpleNamespace(raw=self.run)

    def accuracy(self, run_id):
        return self._accuracy


def _tool_texts(run, accuracy=None) -> dict[str, str]:
    stub = _Stub(run, accuracy)
    return {
        "verify_medications": tools.verify_medications(stub, claims=[]),
        "verify_order_text": tools.verify_order_text(stub, orders=["x"]),
        "get_verification": tools.get_verification(stub, run_id=run["runId"]),
    }


# --- no change without checks; exact prefix; suffix only -----------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
def test_a_run_without_checks_renders_byte_for_byte_as_in_v0_1_1(name):
    case = CASES[name]
    plain = _stripped(case["run"])
    assert render_run_table(plain, case["accuracy"]) == case["table"]
    assert render_run_text(plain, case["accuracy"]) == case["text"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_rows_that_carry_check_but_no_checks_list_render_as_in_v0_1_1(name):
    case = CASES[name]
    run = _stripped(case["run"], keep_row_checks=True)
    assert any("check" in row for row in run["verdicts"])
    assert render_run_table(run, case["accuracy"]) == case["table"]
    assert render_run_text(run, case["accuracy"]) == case["text"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_v0_1_1_rendering_is_an_exact_prefix_and_only_the_block_follows(name):
    case = CASES[name]
    table_lines, text_lines = BLOCKS[name]
    for before, now, lines in (
        (case["table"], render_run_table(case["run"], case["accuracy"]), table_lines),
        (case["text"], render_run_text(case["run"], case["accuracy"]), text_lines),
    ):
        assert now.startswith(before)
        assert now[len(before) :] == "\n\n" + "\n".join([CHECKS_HEADING, *lines])


def test_the_prefix_cases_cover_the_required_shapes():
    assert BEFORE["base"] == "v0.1.1"
    assert "Order 1: not placed" in CASES["completeness"]["table"]
    assert "ACCURACY (physician review)" in CASES["accuracy"]["table"]
    assert "UNREADABLE - do not act on it" in CASES["unreadable"]["table"]
    owners = {row["check"] for row in CASES["all_three"]["run"]["verdicts"]}
    assert owners == {MC, SM, SE}
    assert any(row["verdict"] == "unreadable" for row in CASES["all_three"]["run"]["verdicts"])


# --- Run id last ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("with_checks", [True, False])
def test_run_id_is_the_last_line_of_every_tool_text(name, with_checks):
    case = CASES[name]
    run = case["run"] if with_checks else _stripped(case["run"])
    for tool, text in _tool_texts(run, case["accuracy"]).items():
        lines = text.split("\n")
        assert lines[-1] == f"Run id: {run['runId']}", tool
        assert lines[-2] == "", tool
        if with_checks:
            assert lines[-3] == BLOCKS[name][0][-1], tool
        found = mcp_local_check._RUN_ID.search(text)
        assert found and found.group(1) == run["runId"], tool


def test_the_cli_prints_no_run_id_line_and_ends_with_the_block():
    text = render_run_text(G1_INPUT)
    assert "Run id:" not in text
    assert text.split("\n")[-1] == _golden_block(GOLDENS["G2"])[-1]


# --- block content and grammar -------------------------------------------------------------------


def test_the_2_2_after_response_renders_the_four_block_lines():
    after = CASES["after_2_2"]["run"]
    assert _block(render_run_table(after)) == [
        "Checks (beta release candidates; Orinyx names the check behind each row):",
        "Medication Claims (beta): row 1 - 1 flagged",
        "Semantic Mapping (beta): no rows in this run",
        "Source Evidence (beta): no rows in this run",
    ]


def test_an_entry_with_no_rows_says_so():
    run = _run([_row("a 1 mg", "supported", MC)], [_entry(MC, "Medication Claims", rows=0)])
    for rendered in (render_run_table(run), render_run_text(run)):
        assert _block(rendered)[1] == "Medication Claims (beta): no rows in this run"


def test_counts_come_from_the_entry_never_from_the_rows():
    rows = [_row("a 1 mg", "supported", MC), _row("b 2 mg", "supported", MC)]
    run = _run(rows, [_entry(MC, "Medication Claims", rows=2, contradicted=2, abstain=5)])
    assert (
        _block(render_run_table(run))[1]
        == "Medication Claims (beta): rows 1, 2 - 2 flagged, 5 not verified"
    )
    assert _block(render_run_text(run))[1] == (
        "Medication Claims (beta): Supported 1, 2 - 2 flagged, 5 not verified"
    )


def test_unreadable_is_counted_as_unreadable_never_as_flagged():
    rows = [
        _row("a 1 mg", "contradicted", MC),
        _row("zzz 1 mg", "unreadable", MC),
        _row("c 1 mg", "abstain", MC, explanation="no rule"),
    ]
    run = _run(
        rows, [_entry(MC, "Medication Claims", rows=3, contradicted=1, unreadable=1, abstain=1)]
    )
    for rendered in (render_run_table(run), render_run_text(run)):
        line = _block(rendered)[1]
        assert line.split(" - ", 1)[1] == "1 flagged, 1 unreadable, 1 not verified"
    # count_verdicts, the summary line and the exit code still count unreadable with flagged.
    counts = count_verdicts(rows)
    assert (counts.flagged, counts.supported, counts.not_verified) == (2, 0, 1)
    assert "Checked 3 claims: 1 flagged, 1 unreadable as written, 0 supported, 1 abstained." in (
        render_run_table(run)
    )


def test_g1_semantic_mapping_line_reads_unreadable_not_flagged():
    line = [x for x in _block(render_run_table(G1_INPUT)) if x.startswith("Semantic Mapping")]
    assert line == ["Semantic Mapping (beta): rows 1, 6 - 1 unreadable, 1 not verified"]
    assert "2 flagged" not in render_run_table(G1_INPUT)


def test_one_line_per_entry_in_the_engines_order_after_the_heading():
    rows = [_row("a 1 mg", "supported", MC), _row("b for x", "supported", SE, "indication")]
    checks = [
        _entry(SE, "Source Evidence", rows=1, supported=1),
        _entry(SM, "Semantic Mapping"),
        _entry(MC, "Medication Claims", rows=1, supported=1),
    ]
    for rendered in (render_run_table(_run(rows, checks)), render_run_text(_run(rows, checks))):
        block = _block(rendered)
        assert (
            block[0] == "Checks (beta release candidates; Orinyx names the check behind each row):"
        )
        assert len(block) == 4
        assert [line.split(" (beta):")[0] for line in block[1:]] == [
            "Source Evidence",
            "Semantic Mapping",
            "Medication Claims",
        ]


def test_table_refs_list_every_row_and_never_a_range():
    rows = [_row(f"d{i} 1 mg", "supported", MC) for i in range(3)]
    run = _run(rows, [_entry(MC, "Medication Claims", rows=3, supported=3)])
    line = _block(render_run_table(run))[1]
    assert line == "Medication Claims (beta): rows 1, 2, 3 - 3 supported"
    assert "1-3" not in line


def test_table_refs_are_the_tables_display_numbers_not_the_engines_order():
    rows = [
        _row("s 1 mg", "supported", SE),
        _row("c 1 mg", "contradicted", MC),
        _row("zzz 1 mg", "unreadable", SM),
    ]
    checks = [
        _entry(MC, "Medication Claims", rows=1, contradicted=1),
        _entry(SM, "Semantic Mapping", rows=1, unreadable=1),
        _entry(SE, "Source Evidence", rows=1, supported=1),
    ]
    rendered = render_run_table(_run(rows, checks))
    assert "| 1 | zzz 1 mg |" in rendered
    assert "| 2 | c 1 mg |" in rendered
    assert "| 3 | s 1 mg |" in rendered
    assert _block(rendered)[1:] == [
        "Medication Claims (beta): row 2 - 1 flagged",
        "Semantic Mapping (beta): row 1 - 1 unreadable",
        "Source Evidence (beta): row 3 - 1 supported",
    ]


def test_plain_refs_name_each_section_and_its_numbers_in_print_order():
    rows = [
        _row("s1 1 mg", "supported", MC),
        _row("a1 1 mg", "abstain", MC, explanation="no rule"),
        _row("c1 1 mg", "contradicted", MC),
        _row("s2 1 mg", "supported", MC),
        _row("zzz 1 mg", "unreadable", MC),
    ]
    entry = _entry(MC, "Medication Claims", rows=5, contradicted=1, unreadable=1, supported=2)
    entry["abstain"] = 1
    line = _block(render_run_text(_run(rows, [entry])))[1]
    refs, counts = line.split(": ", 1)[1].split(" - ")
    assert refs == "Unreadable 1; Flags 1; Supported 1, 2; Abstained 1"
    assert counts == "1 flagged, 1 unreadable, 2 supported, 1 not verified"


def test_an_unknown_verdict_is_named_in_the_abstained_section():
    rows = [_row("f 1 mg", "future_verdict", MC, explanation="new"), _row("g 1 mg", "abstain", MC)]
    run = _run(rows, [_entry(MC, "Medication Claims", rows=2, abstain=2)])
    text = render_run_text(run)
    assert "Unknown verdict 'future_verdict'; NOT VERIFIED." in text
    assert _block(text)[1] == "Medication Claims (beta): Abstained 1, 2 - 2 not verified"


# --- blank lines ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["after_2_2", "completeness"])
def test_one_blank_line_before_the_heading_and_none_inside_the_block(name):
    case = CASES[name]
    table = render_run_table(case["run"])
    lines = table.split("\n")
    at = lines.index(CHECKS_HEADING)
    assert lines[at - 1] == "" and lines[at - 2] != ""
    assert "" not in lines[at:]
    assert lines[-1] == BLOCKS[name][0][-1]  # the block is the last part of the table form
    if name == "completeness":
        assert lines[at - 2] == "Orinyx checking time: 12 ms"
    else:
        assert lines[at - 2] == FOOTER
    text_lines = render_run_text(case["run"]).split("\n")
    at = text_lines.index(CHECKS_HEADING)
    assert text_lines[at - 2 : at] == [FOOTER, ""]
    assert "" not in text_lines[at:]
    assert text_lines[-1] == BLOCKS[name][1][-1]


# --- goldens (copied verbatim from the approved wording samples) ---------------------------------


def test_golden_g1_mixed_run_verify_medications_tool_text():
    text = tools.verify_medications(_Stub(G1_INPUT), claims=[])
    assert text == GOLDENS["G1"]
    assert text.startswith("Orinyx verification - run 5c2e7a10 (sample-scribe 2.1)\n")
    assert text.endswith("\nRun id: 5c2e7a10-8d4b-4f61-a3c9-2b7e0d9f4c18")


def test_golden_g2_mixed_run_plain_cli():
    text = render_run_text(G1_INPUT)
    assert text == GOLDENS["G2"]
    assert text.endswith(
        "\nSource Evidence (beta): Supported 2; Abstained 1 - 1 supported, 1 not verified"
    )


SUPPORTED_NOTE = G1_INPUT["aggregate"]["supportedNote"]


def _g3_input() -> dict:
    rows = [
        _row("lisinopril 10 mg once daily", "supported", MC, explanation="Within range."),
        _row("lisinopril by mouth", "supported", MC, "route", explanation="Route on label."),
        _row("lisinopril for hypertension", "supported", SE, "indication", explanation="Listed."),
    ]
    run = _run(
        rows,
        [
            _entry(MC, "Medication Claims", rows=2, supported=2),
            _entry(SM, "Semantic Mapping"),
            _entry(SE, "Source Evidence", rows=1, supported=1),
        ],
        run_id="a91f03d7-6e25-4c8b-b0d4-71c5e2a8f936",
    )
    run["aggregate"]["supportedNote"] = SUPPORTED_NOTE
    run["durationMs"] = 21
    return run


def _g4_input() -> dict:
    rows = [
        _row("warfarin 20 mg", "contradicted", MC, severityReason="Rated Moderate."),
        _row("warfarin by mouth", "supported", MC, "route", explanation="Route on label."),
        _row("warfarin daily", "supported", MC, "frequency", explanation="Frequency on label."),
    ]
    run = _run(
        rows,
        [
            _entry(MC, "Medication Claims", rows=3, contradicted=1, supported=2),
            _entry(SM, "Semantic Mapping"),
            _entry(SE, "Source Evidence"),
        ],
        run_id="3e6b9c42-0f17-4d8a-9e53-c8a2b14d7f05",
    )
    run["aggregate"]["supportedNote"] = SUPPORTED_NOTE
    run["durationMs"] = 17
    return run


def _from_line(text: str, first_line: str) -> str:
    lines = text.split("\n")
    return "\n".join(lines[lines.index(first_line) :])


def test_golden_g3_clean_all_supported_run():
    text = tools.verify_medications(_Stub(_g3_input()), claims=[])
    first = GOLDENS["G3"].split("\n")[0]
    assert first == (
        "No claim was found to contradict its label. This is not a safety clearance; claims not "
        "verified were not checked."
    )
    assert _from_line(text, first) == GOLDENS["G3"]


def test_golden_g4_one_check_has_rows_verify_order_text():
    text = tools.verify_order_text(_Stub(_g4_input()), orders=["warfarin 20 mg by mouth daily"])
    first = GOLDENS["G4"].split("\n")[0]
    assert first == "FLAGGED: the cited label says otherwise, at the severity shown."
    assert _from_line(text, first) == GOLDENS["G4"]
    assert "Medication Claims (beta): rows 1, 2, 3 - 1 flagged, 2 supported" in text
    assert text.count("(beta): no rows in this run") == 2


def _g5_input(*, label: bool = True) -> dict:
    run = copy.deepcopy(G1_INPUT)
    run["verdicts"][1]["check"] = "duplicate_orders"
    run["checks"][0] = _entry(MC, "Medication Claims", rows=1, supported=1)
    fourth = _entry("duplicate_orders", "Duplicate Orders", rows=1, contradicted=1)
    if not label:
        del fourth["label"]
    run["checks"].append(fourth)
    return run


def test_golden_g5_unknown_check_with_and_without_a_label():
    golden = GOLDENS["G5"].split("\n")
    assert len(golden) == 6
    assert _block(render_run_table(_g5_input())) == golden[:5]
    assert _block(render_run_table(_g5_input(label=False)))[4] == golden[5]
    assert golden[5] == "duplicate_orders (beta): row 2 - 1 flagged"


# --- loose ends ----------------------------------------------------------------------------------


def test_an_entry_with_rows_but_no_matching_table_row_shows_counts_only():
    run = _run(
        [_row("a 1 mg", "supported", MC)],
        [
            _entry(MC, "Medication Claims", rows=1, supported=1),
            _entry(SE, "Source Evidence", rows=1, supported=1),
        ],
    )
    for rendered in (render_run_table(run), render_run_text(run)):
        assert _block(rendered)[2] == "Source Evidence (beta): 1 supported"


def test_a_row_whose_check_matches_no_entry_is_on_no_line():
    rows = [
        _row("a 1 mg", "supported", MC),
        _row("b 1 mg", "supported", "not_an_entry"),
        _row("c 1 mg", "supported", MC),
    ]
    checks = [
        _entry(MC, "Medication Claims", rows=2, supported=2),
        _entry(SM, "Semantic Mapping"),
        _entry(SE, "Source Evidence"),
    ]
    run = _run(rows, checks)
    table = render_run_table(run)
    block = _block(table)
    assert len(block) == 1 + len(checks)
    assert block[1] == "Medication Claims (beta): rows 1, 3 - 2 supported"
    for line in block[1:]:
        body = line.split(" (beta): ", 1)[1]
        refs = body.split(" - ")[0] if body.startswith("row") else ""
        assert "2" not in re.findall(r"\d+", refs), line
    assert "not_an_entry" not in "\n".join(block)
    before = render_run_table(_stripped(run))
    assert "| 2 | b 1 mg | dose | SUPPORTED | - |" in before
    assert table.startswith(before)
    text_block = _block(render_run_text(run))
    assert len(text_block) == 1 + len(checks)
    assert text_block[1] == "Medication Claims (beta): Supported 1, 3 - 2 supported"
    assert all("Supported 2" not in line for line in text_block)


def test_placement_comes_from_the_rows_check_only():
    run = _run(
        [_row("a 1 mg", "supported", SE, "dose_range")],
        [_entry(MC, "Medication Claims"), _entry(SE, "Source Evidence", rows=1, supported=1)],
    )
    block = _block(render_run_table(run))
    assert block[2] == "Source Evidence (beta): row 1 - 1 supported"
    assert block[1] == "Medication Claims (beta): no rows in this run"


def test_the_mcp_package_holds_no_check_table():
    """No claim-type-to-check mapping, and no check value of its own, anywhere in the package."""
    package = Path(__file__).resolve().parents[1] / "orinyx_mcp"
    for path in package.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for value in (MC, SM, SE):
            assert value not in source, (path.name, value)


# --- forward compatibility; relatedChecks; no column --------------------------------------------


def test_an_unknown_status_renders_beta():
    entry = _entry(MC, "Medication Claims", rows=1, supported=1)
    entry["status"] = "gamma"
    run = _run([_row("a 1 mg", "supported", MC)], [entry])
    assert _block(render_run_table(run))[1] == "Medication Claims (beta): row 1 - 1 supported"
    assert "gamma" not in render_run_table(run)


def test_names_come_from_the_label_else_the_raw_check_through_cell():
    odd_label = "Dose | Check\nwith `ticks`"
    odd_check = "dup|orders"
    run = _run(
        [_row("a 1 mg", "supported", MC), _row("b 1 mg", "supported", odd_check)],
        [
            _entry(MC, odd_label, rows=1, supported=1),
            _entry(odd_check, rows=1, supported=1),
            _entry(SE, "", rows=0),
        ],
    )
    for rendered in (render_run_table(run), render_run_text(run)):
        block = _block(rendered)
        assert block[1].startswith(f"{_cell(odd_label)} (beta): ")
        assert block[1].startswith("Dose \\| Check with `ticks` (beta): ")
        assert block[2].startswith(f"{_cell(odd_check)} (beta): ")
        assert block[2].startswith("dup\\|orders (beta): ")
        assert block[3] == "source_evidence (beta): no rows in this run"


def test_the_mcp_never_supplies_a_name_of_its_own():
    run = _run([_row("a 1 mg", "supported", MC)], [_entry(MC, "Renamed", rows=1, supported=1)])
    assert _block(render_run_table(run))[1].startswith("Renamed (beta):")
    assert "Medication Claims" not in render_run_table(run)


def test_related_checks_appear_nowhere_in_readable_text():
    assert G1_INPUT["verdicts"][1]["relatedChecks"] == [SE]
    assert G1_INPUT["verdicts"][2]["relatedChecks"] == [SE]
    for rendered in (render_run_table(G1_INPUT), render_run_text(G1_INPUT)):
        assert "relatedChecks" not in rendered and "related" not in rendered.lower()
    se_line = [x for x in _block(render_run_table(G1_INPUT)) if x.startswith("Source Evidence")]
    assert se_line == ["Source Evidence (beta): rows 4, 5 - 1 supported, 1 not verified"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_column_is_added(name):
    case = CASES[name]
    before = [x for x in case["table"].split("\n") if x.startswith("|")]
    now = [
        x for x in render_run_table(case["run"], case["accuracy"]).split("\n") if x.startswith("|")
    ]
    assert now == before
    assert now[0] == TABLE_HEADER
    for row in now:
        assert row.replace("\\|", "").count("|") == TABLE_HEADER.count("|")


# --- surfaces unchanged --------------------------------------------------------------------------


def _cli(args, data, monkeypatch):
    def respond(request):
        if request.url.path.endswith("/accuracy"):
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "none"}})
        return httpx.Response(200, json=data)

    monkeypatch.setenv("ORINYX_API_URL", "https://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "synthetic-check-lines-key")
    return cli.main(
        args,
        client_factory=lambda url, key: OrinyxClient(
            url, key, transport=httpx.MockTransport(respond)
        ),
    )


@pytest.mark.parametrize("name", ["after_2_2", "accuracy", "unreadable", "completeness"])
def test_counts_and_exit_code_are_equal_with_and_without_checks(name, monkeypatch, capsys):
    run = CASES[name]["run"]
    plain = _stripped(run)
    assert count_verdicts(run["verdicts"]) == count_verdicts(plain["verdicts"])
    with_checks = _cli(["get", run["runId"]], run, monkeypatch)
    capsys.readouterr()
    without = _cli(["get", run["runId"]], plain, monkeypatch)
    capsys.readouterr()
    assert with_checks == without
    assert with_checks in (cli.EXIT_CLEAN, cli.EXIT_FLAGGED, cli.EXIT_NOT_VERIFIED)


def test_get_json_prints_the_engine_response_unchanged(monkeypatch, capsys):
    run = CASES["after_2_2"]["run"]
    code = _cli(["get", run["runId"], "--json"], run, monkeypatch)
    out = capsys.readouterr().out
    assert code == cli.EXIT_FLAGGED
    assert json.loads(out) == run
    for key in ('"check"', '"relatedChecks"', '"checksVersion"', '"checks"'):
        assert key in out
    assert CHECKS_HEADING not in out


def test_verify_json_prints_the_engine_response_unchanged(monkeypatch, capsys, tmp_path):
    run = CASES["after_2_2"]["run"]
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps([{"rawText": "warfarin 20 mg daily"}]))
    code = _cli(["verify", "--file", str(claims), "--json"], run, monkeypatch)
    out = capsys.readouterr().out
    assert code == cli.EXIT_FLAGGED
    assert json.loads(out) == run
    assert CHECKS_HEADING not in out


def test_the_v0_1_1_client_parses_the_after_response():
    """client.py is unchanged since the v0.1.1 release; extra='ignore' drops the
    new keys from the model, and `raw` keeps them for rendering."""
    after = CASES["after_2_2"]["run"]
    result = VerificationResult.from_json(after)
    before = VerificationResult.from_json(RUN_JSON)
    assert result.raw == after
    assert count_verdicts(result.verdicts) == count_verdicts(before.verdicts)
    assert result.flagged == before.flagged

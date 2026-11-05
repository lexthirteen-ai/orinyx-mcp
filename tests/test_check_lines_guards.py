"""QA guards beside `test_check_lines.py`.

Three properties of the change had no test of their own, or only partial coverage:
- the tool names and input schemas are unchanged (a scratch sha comparison only);
- `observe --json` passes the engine response through unchanged, and `observe`'s own text
  counts and exit code do not move with `checks` ("every other --json output");
- no claim-type-to-check table, and no name of the MCP's own even for the three known checks
  (placement and names were tested on one row and one rename).

`check_lines_tool_surface_v0_1_1.json` was rendered by the v0.1.1 package itself (the v0.1.1
tree, imported first on the path), not typed by hand.
"""

import json
from pathlib import Path

import pytest
from orinyx_mcp import cli
from orinyx_mcp.text import CHECKS_HEADING, render_run_table, render_run_text

from tests.test_check_lines import CASES, MC, SE, SM, _block, _cli, _entry, _row, _run, _stripped

FIXTURES = Path(__file__).with_name("fixtures")
SURFACE = json.loads(
    (FIXTURES / "check_lines_tool_surface_v0_1_1.json").read_text(encoding="utf-8")
)
KNOWN_LABELS = ("Medication Claims", "Semantic Mapping", "Source Evidence")


# --- surfaces unchanged: tool names and input schemas --------------------------------------------


def _surface() -> dict:
    from orinyx_mcp.server import build_server

    tools = build_server(lambda: None)._tool_manager.list_tools()
    return {tool.name: json.loads(json.dumps(tool.parameters)) for tool in tools}


def test_tool_names_and_input_schemas_are_as_in_v0_1_1(monkeypatch):
    pytest.importorskip("mcp")
    assert SURFACE["base"] == "v0.1.1"
    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    monkeypatch.delenv("ORINYX_ARENA_URL", raising=False)
    assert _surface() == SURFACE["default"]
    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    monkeypatch.setenv("ORINYX_ARENA_URL", "https://arena.orinyx.example")
    assert _surface() == SURFACE["arena"]
    run_tools = ("verify_medications", "verify_order_text", "get_verification")
    assert all(name in SURFACE["default"] for name in run_tools)


# --- --json raw, and observe's own lines, with and without checks --------------------------------


def _observe(tmp_path, run, monkeypatch, capsys, *extra):
    path = tmp_path / "turn.txt"
    path.write_text("warfarin 20 mg by mouth daily\n")
    code = _cli(["observe", str(path), *extra], run, monkeypatch)
    return code, capsys.readouterr().out


def test_observe_json_prints_the_engine_response_unchanged(tmp_path, monkeypatch, capsys):
    run = CASES["after_2_2"]["run"]
    code, out = _observe(tmp_path, run, monkeypatch, capsys, "--json")
    assert code == cli.EXIT_FLAGGED
    body = json.loads(out)
    assert [entry["raw"] for entry in body["runs"]] == [run]
    for key in ('"check"', '"relatedChecks"', '"checksVersion"', '"checks"'):
        assert key in out
    assert CHECKS_HEADING not in out


@pytest.mark.parametrize("name", ["after_2_2", "accuracy", "unreadable", "completeness"])
def test_observe_text_and_exit_code_do_not_move_with_checks(name, tmp_path, monkeypatch, capsys):
    run = CASES[name]["run"]
    with_checks = _observe(tmp_path, run, monkeypatch, capsys)
    without = _observe(tmp_path, _stripped(run), monkeypatch, capsys)
    assert with_checks == without
    assert CHECKS_HEADING not in with_checks[1]


# --- no table in the MCP: placement from `check` only, names from the engine only ----------------

CLAIM_TYPES = ("dose_range", "route", "frequency", "indication", "interaction")


def _rotated_run(*, labels: bool) -> tuple[dict, dict[str, list[int]]]:
    """Every claim type appears once under each check, so no claim-type table can place them."""
    owners = (MC, SM, SE)
    rows, owned = [], {check: [] for check in owners}
    for kind_index, kind in enumerate(CLAIM_TYPES):
        for shift in range(len(owners)):
            check = owners[(kind_index + shift) % len(owners)]
            rows.append(_row(f"drug{len(rows) + 1} {kind}", "supported", check, kind))
            owned[check].append(len(rows))
    checks = [
        _entry(check, label if labels else None, rows=len(owned[check]), supported=5)
        for check, label in zip(owners, KNOWN_LABELS, strict=True)
    ]
    return _run(rows, checks), owned


@pytest.mark.parametrize("labels", [True, False])
def test_each_row_is_placed_by_its_check_whatever_its_claim_type(labels):
    run, owned = _rotated_run(labels=labels)
    table, text = _block(render_run_table(run))[1:], _block(render_run_text(run))[1:]
    for index, check in enumerate((MC, SM, SE)):
        name = KNOWN_LABELS[index] if labels else check
        numbers = ", ".join(str(n) for n in owned[check])
        assert table[index] == f"{name} (beta): rows {numbers} - 5 supported"
        assert text[index] == f"{name} (beta): Supported {numbers} - 5 supported"


def test_without_labels_the_block_names_no_known_check_of_its_own():
    run, _ = _rotated_run(labels=False)
    for rendered in (render_run_table(run), render_run_text(run)):
        block = "\n".join(_block(rendered))
        for label in KNOWN_LABELS:
            assert label not in block, label
        assert [line.split(" (beta):")[0] for line in _block(rendered)[1:]] == [MC, SM, SE]

"""The public hardening checklist keeps the promises its first paragraph makes.

`docs/HARDENING_CHECKLIST.md` says that it lists closed rows only: a check that passed at the
sweep, or a finding fixed with a test that fails if it comes back. This test holds that to the
rows themselves. Every row is closed (`pass` or `fixed`, with the date and nothing else, so no
local commit id that a squash would remove), every fixed row names a test, and every test a row
names exists in this checkout. A row is never listed twice.

The checklist is not in the source distribution. Outside a git checkout there is no checklist to
read, and the check is skipped.
"""

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKLIST = "docs/HARDENING_CHECKLIST.md"
NO_TEST = chr(0x2014)  # the em dash the checklist writes in a row with no test
ROW_ID = re.compile(r"H-orinyx-mcp-[0-9]{3}")
CLOSED = re.compile(r"(pass|fixed) [0-9]{4}-[0-9]{2}-[0-9]{2}")
DIMENSIONS = {"secrets", "access", "injection", "boundary", "rot", "deploy"}
# A pipe inside a cell is written as backslash-pipe, as in a shell command with a pipe in it.
CELL_BREAK = re.compile(r"(?<!\\)\|")
PROMISE = (
    "This file lists closed rows only: a check that passed at the sweep, or a finding that was "
    "fixed with a test that fails if it comes back."
)


def tracked_files() -> set[str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout.decode()
    except (OSError, subprocess.SubprocessError):
        listed = ""
    names = {name for name in listed.split("\0") if name}
    if not names:
        pytest.skip("not a git checkout: the checklist is not in a source distribution")
    return names


def rows(text: str) -> list[list[str]]:
    """The cells of every row of every table, one list per row, header rows left out."""
    found = []
    for line in text.split("\n"):
        if not line.startswith("| H-"):
            continue
        cells = [cell.strip() for cell in CELL_BREAK.split(line.strip())[1:-1]]
        found.append(cells)
    return found


def problems(text: str, tracked: set[str], read) -> list[str]:
    """Every way the checklist text breaks its own rules. Empty when it keeps them all.
    `read(path)` returns the text of a tracked file."""
    found = []
    if PROMISE not in " ".join(text.split()):
        found.append("the closed-rows paragraph is missing")
    seen = set()
    for cells in rows(text):
        if len(cells) != 5:
            found.append(f"{cells[0]}: {len(cells)} cells, not 5")
            continue
        row, dimension, _where, status, tests = cells
        if not ROW_ID.fullmatch(row):
            found.append(f"{row}: not a row id")
        if row in seen:
            found.append(f"{row}: listed twice")
        seen.add(row)
        if dimension not in DIMENSIONS:
            found.append(f"{row}: unknown dimension {dimension!r}")
        if not CLOSED.fullmatch(status):
            found.append(f"{row}: status {status!r} is not a closed row with its date")
        if status.startswith("fixed") and tests == NO_TEST:
            found.append(f"{row}: fixed with no test named")
        if tests == NO_TEST:
            continue
        for named in (part.strip() for part in tests.split(";")):
            path, _, function = named.partition("::")
            if path not in tracked or not path.startswith("tests/"):
                found.append(f"{row}: {path} is not a tracked test file")
                continue
            if function:
                defined = {
                    node.name
                    for node in ast.walk(ast.parse(read(path)))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                if function not in defined:
                    found.append(f"{row}: {path} defines no {function}")
    if not seen:
        found.append("no row was read")
    return found


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_checklist_keeps_its_own_rules():
    tracked = tracked_files()
    assert CHECKLIST in tracked, f"{CHECKLIST} is not tracked"
    assert problems(_read(CHECKLIST), tracked, _read) == []


# --- the check itself, on made-up text -------------------------------------------------------

GOOD = (
    "This file lists closed rows only: a check that passed at the sweep, or a finding\n"
    "that was fixed with a test that fails if it comes back.\n\n"
    "| Row | Dimension | File:line or command | Status | Test |\n"
    "|---|---|---|---|---|\n"
    "| H-orinyx-mcp-001 | access | a.py:1 | fixed 2026-11-13 | tests/test_a.py |\n"
    "| H-orinyx-mcp-002 | deploy | `ls \\| grep x` | pass 2026-11-13 | " + NO_TEST + " |\n"
    "| H-orinyx-mcp-003 | rot | b.py:2 | pass 2026-11-13 | tests/test_a.py::test_one |\n"
)
TRACKED = {"tests/test_a.py", "a.py", "b.py"}


def _fake_read(rel: str) -> str:
    return "def test_one():\n    pass\n"


def test_a_checklist_that_keeps_its_rules_has_nothing_to_report():
    assert problems(GOOD, TRACKED, _fake_read) == []


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("fixed 2026-11-13", "fixed@0123abc 2026-11-13", "is not a closed row"),
        ("pass 2026-11-13 | " + NO_TEST, "not-run | " + NO_TEST, "is not a closed row"),
        ("pass 2026-11-13 | " + NO_TEST, "fail 2026-11-13 | " + NO_TEST, "is not a closed row"),
        ("fixed 2026-11-13 | tests/test_a.py", "fixed 2026-11-13 | " + NO_TEST, "no test named"),
        ("tests/test_a.py |", "tests/test_gone.py |", "is not a tracked test file"),
        ("test_a.py::test_one", "test_a.py::test_two", "defines no test_two"),
        ("H-orinyx-mcp-003", "H-orinyx-mcp-001", "listed twice"),
        ("| rot |", "| misc |", "unknown dimension"),
        ("closed rows only", "rows", "paragraph is missing"),
    ],
)
def test_each_broken_rule_is_named(old, new, problem):
    assert old in GOOD
    found = problems(GOOD.replace(old, new, 1), TRACKED, _fake_read)
    assert any(problem in line for line in found), found


def test_a_text_with_no_rows_is_not_a_pass():
    assert problems(GOOD.split("| Row")[0], TRACKED, _fake_read) == ["no row was read"]

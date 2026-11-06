"""What the README and the Unreleased CHANGELOG entry say about the five FDA reference lookups.

Developer accounts may use the five lookups; product (vendor) accounts are still refused, and a
label's version history and diff, a monograph's version history and orders and a regulatory
document's content stay staff-only. These checks fail if a later edit puts a staff-only or
developer-refused sentence about the five lookups back. They read sentences and clauses, not
lines, because the README wraps at 100 columns and the old wording ran across a line break
("The FDA label and OTC monograph lookups and / the dashboard are for staff accounts.")."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LOOKUP_TOOLS = (
    "find_fda_label",
    "read_fda_label_section",
    "find_otc_monographs",
    "get_otc_monograph",
    "read_otc_monograph_section",
)
LOOKUP_WORDS = ("lookup", "label", "monograph", *LOOKUP_TOOLS)
_NEW_UNIT = ("- ", "|", "#", "```", "> ", "**")


def _units(text: str) -> list[str]:
    """Paragraphs, bullets, table rows and headings, each joined onto one line."""
    units, current = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if (not stripped or stripped.startswith(_NEW_UNIT)) and current:
            units.append(" ".join(current))
            current = []
        if stripped:
            current.append(stripped)
    if current:
        units.append(" ".join(current))
    return units


def _clauses(text: str) -> list[str]:
    return [
        clause for unit in _units(text) for clause in re.split(r"(?<=[.;:!?])\s+", unit) if clause
    ]


# Routes that really are staff-only; a sentence about them may say "staff" next to "label".
STAFF_ONLY_ROUTES = ("version history", "regulatory document")


def _names_a_lookup(clause: str) -> bool:
    lowered = clause.lower()
    if any(route in lowered for route in STAFF_ONLY_ROUTES):
        return False
    return any(word in lowered for word in LOOKUP_WORDS)


@pytest.fixture(scope="module")
def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def changelog_unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[0\.1\.4\][^\n]*\n(.*?)(?=^## \[)", text, re.M | re.S)
    assert match, "CHANGELOG.md has no [0.1.4] section"
    return match.group(1)


def test_no_readme_sentence_calls_the_lookups_staff_only(readme):
    wrong = [c for c in _clauses(readme) if "staff" in c.lower() and _names_a_lookup(c)]
    assert wrong == []


def test_no_readme_sentence_says_a_developer_is_refused_the_lookups(readme):
    wrong = [
        clause
        for clause in _clauses(readme)
        if "developer" in clause.lower()
        and ("refused" in clause.lower() or "not available" in clause.lower())
        and _names_a_lookup(clause)
    ]
    assert wrong == []


def test_start_a_test_returns_no_longer_quotes_the_refusal_for_a_developer(readme):
    wrong = [
        unit
        for unit in _units(readme)
        if "developer" in unit.lower() and "Not available to this account" in unit
    ]
    assert wrong == []


@pytest.mark.parametrize("tool", LOOKUP_TOOLS)
def test_each_lookup_tool_section_reads_account_developer(readme, tool):
    match = re.search(rf"^### \d+\. `{tool}`\n+(.*)$", readme, re.M)
    assert match, tool
    assert match.group(1).startswith("Account: developer."), (tool, match.group(1))


def test_the_choose_a_tool_table_lists_the_lookups_for_developer_accounts(readme):
    rows = {}
    for line in readme.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 2:
            for tool in LOOKUP_TOOLS:
                if f"`{tool}`" in cells[0]:
                    rows[tool] = cells[1]
    assert rows == dict.fromkeys(LOOKUP_TOOLS, "developer")


def test_account_types_put_the_lookups_under_the_developer_account(readme):
    units = _units(readme)
    developer = next(u for u in units if u.startswith("- **Developer account**"))
    product = next(u for u in units if u.startswith("- **Product (vendor) account**"))
    for tool in LOOKUP_TOOLS:
        assert f"`{tool}`" in developer, tool
    assert "a product account calling a lookup tool is refused" in product


def test_no_not_recommended_for_heading_is_left_empty(readme):
    lines = readme.splitlines()
    for number, line in enumerate(lines):
        if line.strip() == "**Not recommended for:**":
            following = next((later for later in lines[number + 1 :] if later.strip()), "")
            assert following.startswith("- "), (number + 1, following)


def test_the_dashboard_line_and_the_cli_gap_stay(readme):
    flat = " ".join(_units(readme))
    assert "The dashboard is for staff accounts." in flat
    assert "version history and diff" in flat and "are staff-only too" in flat
    assert "No monograph lookups (MCP tools only)" in flat


def test_the_unreleased_entry_states_what_opened_and_what_did_not(changelog_unreleased):
    flat = " ".join(changelog_unreleased.split())
    for tool in LOOKUP_TOOLS:
        assert f"`{tool}`" in flat, tool
    assert "Developer accounts can use the five FDA reference lookups" in flat
    assert "Product (vendor) accounts are still refused every lookup" in flat
    assert "not charged against the monthly checks of the free plan" in flat
    assert "Still staff-only" in flat
    for staff_only in ("version history and diff", "orders", "regulatory document's content"):
        assert staff_only in flat, staff_only


def test_the_unreleased_entry_never_calls_the_lookups_staff_only(changelog_unreleased):
    wrong = [
        c for c in _clauses(changelog_unreleased) if "staff" in c.lower() and _names_a_lookup(c)
    ]
    assert wrong == []

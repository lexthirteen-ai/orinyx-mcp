"""Gate B17: SECURITY.md and the release notes name both feedback channels on the
public release repository: private vulnerability reporting for vulnerabilities, Issues with the
"Report a problem" template for everything else. A later edit fails here if it drops either
channel, moves one into another section or bullet, or drops the synthetic-data rule. It also fails
if any paragraph or list item (`-`, `*`, `+` or numbered) of either file that mentions a
vulnerability, in its own text or its section heading, names a public issue, discussion or pull
request, other than the sentence that forbids one. The anything-else channel, where Issues belong
(SECURITY.md's "Reporting anything else" section and the release notes' "Anything else" bullet),
is exempt from that check, but fails if it mentions a vulnerability at all once the phrase "that is
not a vulnerability" is set aside."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTES = "docs/RELEASE_NOTES_2026-11-02.md"
RELEASE_REPO = "lexthirteen-ai/orinyx-mcp-release"
ADVISORIES_URL = f"https://github.com/{RELEASE_REPO}/security/advisories/new"
SECURITY_PROHIBITION = (
    "Please do not open a public issue, discussion or pull request for a vulnerability."
)
NOTES_PROHIBITION = "Never open a public issue for a vulnerability."
# The synthetic-data rule, stated for vulnerability reports and for everything else.
VULNERABILITY_DATA_RULE = (
    "Use synthetic data only in a vulnerability report too: never include real patient data, "
    "credentials or keys, and replace any key with a placeholder."
)
OTHER_DATA_RULE = "**Never include real patient data, credentials or keys in a report.**"
# The only mention of a vulnerability the anything-else channel may make.
OTHER_CHANNEL_DISCLAIMER = "that is not a vulnerability"
LIST_ITEM = re.compile(r"(?:[-*+]|\d+\.) ")


def _collapse(text: str) -> str:
    # Collapse the Markdown line wrapping so a phrase can be matched across a line break.
    return " ".join(text.split())


def _read(rel: str) -> str:
    return _collapse((ROOT / rel).read_text(encoding="utf-8"))


def _section(rel: str, heading: str) -> str:
    """The text under one `## ` heading, up to the next one, so a channel moved to another
    section is not counted where it no longer is."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    marker = f"\n## {heading}\n"
    assert marker in text, f"{rel} has no '## {heading}' section"
    return text.split(marker, 1)[1].split("\n## ", 1)[0]


def _offers_public_route(text: str) -> bool:
    """True if the text names a public issue, discussion or pull request anywhere outside the
    sentences that forbid one for a vulnerability."""
    rest = _collapse(text)
    for prohibition in (SECURITY_PROHIBITION, NOTES_PROHIBITION):
        rest = rest.replace(prohibition, "")
    return any(word in rest.lower() for word in ("issue", "discussion", "pull request"))


def _blocks(rel: str) -> list[tuple[str, str]]:
    """Every paragraph and top-level list item (`-`, `*`, `+` or numbered) of a file, each with
    the heading it sits under. A list item keeps its continuation lines (indented, or unindented
    with no blank line before them) and its indented paragraphs, as Markdown renders them."""
    blocks: list[tuple[str, str]] = []
    heading, lines, blank_before, in_fence = "", [], False, False

    def flush():
        if lines:
            blocks.append((heading, "\n".join(lines)))
        lines.clear()

    for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if in_fence or line.startswith("```"):
            lines.append(line)
        elif line.startswith("#"):
            flush()
            heading = line
        elif LIST_ITEM.match(line):
            flush()
            lines.append(line)
        elif not line.strip():
            if lines and not LIST_ITEM.match(lines[0]):
                flush()
            blank_before = True
            continue
        else:
            if lines and LIST_ITEM.match(lines[0]) and blank_before and not line[0].isspace():
                flush()
            lines.append(line)
        blank_before = False
    flush()
    return blocks


def _is_other_channel(heading: str, block: str) -> bool:
    return heading == "## Reporting anything else" or block.startswith("- **Anything else**")


def test_security_md_names_both_channels():
    vulnerabilities = _collapse(_section("SECURITY.md", "Reporting a vulnerability"))
    other = _collapse(_section("SECURITY.md", "Reporting anything else"))
    assert RELEASE_REPO in vulnerabilities and RELEASE_REPO in other
    assert ADVISORIES_URL in vulnerabilities
    assert "private vulnerability reporting" in vulnerabilities
    assert SECURITY_PROHIBITION in vulnerabilities
    assert "what an attacker could do with it" in vulnerabilities
    assert "**Issues**" in other and '"Report a problem" template' in other


@pytest.mark.parametrize("rel", ["SECURITY.md", NOTES])
def test_no_part_of_either_file_offers_a_public_route_for_a_vulnerability(rel):
    offending = []
    for heading, block in _blocks(rel):
        text = _collapse(heading + " " + block)
        if _is_other_channel(heading, block):
            # Issues belong here, so this channel may not take a vulnerability at all.
            if "vulnerab" in text.lower().replace(OTHER_CHANNEL_DISCLAIMER, ""):
                offending.append(text)
        elif "vulnerab" in text.lower() and _offers_public_route(text):
            offending.append(text)
    assert not offending


def test_security_md_keeps_real_data_and_keys_out_of_every_report():
    vulnerabilities = _collapse(_section("SECURITY.md", "Reporting a vulnerability"))
    other = _collapse(_section("SECURITY.md", "Reporting anything else"))
    assert VULNERABILITY_DATA_RULE in vulnerabilities
    assert OTHER_DATA_RULE in other


def _bullets(rel: str, heading: str) -> dict[str, str]:
    """Each top-level bullet of a section, keyed by its bold lead (`A vulnerability:`)."""
    bullets: dict[str, str] = {}
    for item in ("\n" + _section(rel, heading)).split("\n- ")[1:]:
        lead = item.split("**", 2)[1] if item.startswith("**") else ""
        bullets[lead] = _collapse(item.split("\n\n", 1)[0])
    return bullets


def test_release_notes_name_both_channels():
    section = _collapse(_section(NOTES, "Reporting a problem"))
    assert RELEASE_REPO in section
    assert "Never include real patient data" in section


def test_release_notes_route_each_channel_in_its_own_bullet():
    bullets = _bullets(NOTES, "Reporting a problem")
    vulnerability, other = bullets["A vulnerability:"], bullets["Anything else"]
    assert ADVISORIES_URL in vulnerability
    assert "private vulnerability reporting" in vulnerability
    assert NOTES_PROHIBITION in vulnerability
    assert not _offers_public_route(vulnerability)
    assert "Report a problem" not in vulnerability
    assert "**Issue**" in other and '"Report a problem" template' in other
    assert ADVISORIES_URL not in other
    assert "private vulnerability reporting" not in other


def test_issue_template_tells_cli_testers_how_to_get_the_run_id():
    text = _read(".github/ISSUE_TEMPLATE/bug_report.md")
    assert "`--json` and copy `runId`" in text

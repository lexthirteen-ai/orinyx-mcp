"""The approved 0.1.5 public wording does not regress.

Each test fails if an older sentence comes back: CLI login said it waited on an engine update
that has shipped; the network server was said to hold no service credential, when it holds the
hop secret; the Docker example left the hop secret out, so the server it showed would not start;
the changelog linked a README anchor that does not exist; and internal gate ids, which mean
nothing to a reader, sat in files the package ships.
"""

import json
import re

import pytest
from orinyx_mcp import __version__

from tests.test_install_docs import ROOT, _collapse, _doc_files, _read, _section

DOCS = sorted({*_doc_files(), "CONTRIBUTING.md"})
SOURCES = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "orinyx_mcp").rglob("*.py"))
MANIFEST = ROOT / "release" / "manifests" / f"{__version__}.json"

HOP_SECRET_SENTENCES = (
    "The network server holds no database and no API key of its own. It holds one service "
    "secret, `ORINYX_HOP_SECRET`, shared with the API, which marks its requests as coming from "
    "the hosted connector. That secret never stands in for a caller's credential."
)
DOCKER_NOTE = (
    "`ORINYX_HOP_SECRET` is required, and the server refuses to start without it; "
    "`-e ORINYX_HOP_SECRET` passes the value from your shell, so it stays out of the command."
)
# The old anchor alone: `#installation` and `#install-from-pypi` are real README anchors.
OLD_INSTALL_LINK = re.compile(r"README\.md#install(?![\w-])")
GATE_ID = re.compile(r"\b[Gg]ate B\d+")
# Assembled, so that this packaged file holds no internal lane id of its own.
OLD_LOGIN_WAIT = "L" + "9 engine"


@pytest.mark.parametrize("rel", DOCS)
def test_cli_login_no_longer_waits_on_an_engine_update(rel):
    assert OLD_LOGIN_WAIT not in _collapse(_read(rel))


def test_the_readme_says_cli_login_is_new_in_this_release():
    assert "New in 0.1.5." in _section(_read("README.md"), "### CLI login")


@pytest.mark.parametrize("rel", DOCS + SOURCES)
def test_nothing_says_the_network_server_holds_no_service_credential(rel):
    assert "no service credential" not in _collapse(_read(rel))


@pytest.mark.parametrize("rel", ("SECURITY.md", "docs/DEPLOY.md", "orinyx_mcp/http.py"))
def test_the_network_server_names_its_one_service_secret(rel):
    assert HOP_SECRET_SENTENCES in _collapse(_read(rel))


def test_the_docker_example_passes_the_hop_secret_from_the_shell():
    docker = _section(_read("README.md"), "### Docker")
    fences = re.findall(r"```bash\n(.*?)```", docker, re.S)
    runs = [fence for fence in fences if "docker run" in fence]
    assert len(runs) == 1, runs
    lines = [line.strip() for line in runs[0].splitlines()]
    # The bare name, so docker reads the value from the shell and it never sits in the command.
    assert "-e ORINYX_HOP_SECRET \\" in lines
    assert not any(line.startswith("-e ORINYX_HOP_SECRET=") for line in lines)
    after = _collapse(docker.split(runs[0], 1)[1])
    assert after.startswith("``` " + DOCKER_NOTE)


def test_the_network_server_settings_are_one_table():
    network = _section(_read("README.md"), "### Network server")
    rows = [line for line in network.splitlines() if line.startswith("| `")]
    table = "\n".join(rows)
    assert "| `ORINYX_HOP_SECRET` |" in table and "| `PORT` |" in table
    assert table in network, "a blank line splits the network-server settings table"


@pytest.mark.parametrize("rel", DOCS)
def test_no_link_points_at_the_old_install_anchor(rel):
    assert not OLD_INSTALL_LINK.search(_read(rel))


def packaged_text_files() -> list[str]:
    """Every file the source distribution lists that is here as UTF-8 text. `PKG-INFO` is
    written by the build, and an image is not text; neither is read."""
    listed = json.loads(MANIFEST.read_text(encoding="utf-8"))["sdist"]
    found = []
    for rel in listed:
        try:
            (ROOT / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found.append(rel)
    return found


def test_the_packaged_files_are_read():
    files = packaged_text_files()
    assert {"README.md", "CHANGELOG.md", "orinyx_mcp/server.py"} <= set(files)
    assert "tests/test_public_wording_does_not_regress.py" in files


@pytest.mark.parametrize("rel", packaged_text_files())
def test_no_packaged_file_holds_an_internal_gate_id(rel):
    found = [
        f"{number}: {match.group(0)}"
        for number, line in enumerate(_read(rel).split("\n"), start=1)
        for match in GATE_ID.finditer(line)
    ]
    assert found == []


@pytest.mark.parametrize(
    "text",
    # Assembled, so that this packaged file holds no gate id of its own.
    ["(" + "g" + "ate B15).", "G" + "ate B17: SECURITY.md", "release " + "g" + "ate B8"],
)
def test_the_gate_id_pattern_finds_either_spelling(text):
    assert GATE_ID.search(text)


@pytest.mark.parametrize(
    "text",
    # The row string is assembled for the same reason.
    ["a gate before the release", "the " + "B" + "15 row", "Gateway B2"],
)
def test_the_gate_id_pattern_leaves_ordinary_text_alone(text):
    assert not GATE_ID.search(text)


def test_the_methodology_page_makes_no_performance_or_certification_claim():
    text = _read("docs/METHODOLOGY.md")
    lowered = text.lower()
    for word in ("certified", "validated", "physician-reviewed", "clinically proven"):
        assert word not in lowered, word
    assert not re.search(r"\d+(\.\d+)?\s*%", text)
    assert "## 7. Proposed, not built" in text
    assert "Nothing in this section is" in text
    for internal in ("app/", "orinyx-engine", "CHA-", "rule-"):
        assert internal not in text, internal


CLINICAL_SUITE_DOCS = sorted((ROOT / "docs" / "clinical-suite").rglob("*.*"))
PRIVATE_DETAIL = [
    r"localhost:\d+",
    r"\bbuild/\d{4}-",
    r"`app/",
    r"\bdata/[a-z_]+\.json",
    r"ingest_quarantine",
    r"dose_ceiling_held",
    r"\bLex\b",
    r"owner decision",
    r"CLAUDE\.md",
    r"development database",
]


def test_the_clinical_suite_docs_are_found():
    names = {p.name for p in CLINICAL_SUITE_DOCS}
    assert {"CAPABILITY_MAP.md", "README.md", "results.md", "results.json"} <= names


@pytest.mark.parametrize("path", CLINICAL_SUITE_DOCS, ids=lambda p: p.name)
def test_the_clinical_suite_docs_hold_no_private_engine_detail_or_ruling_names(path):
    text = path.read_text(encoding="utf-8")
    found = [p for p in PRIVATE_DETAIL if re.search(p, text)]
    assert found == []


# The clinical fixtures ship in the source distribution, so they meet the same bar.
SHIPPED_CLINICAL_FIXTURES = [
    ROOT / "tests" / "fixtures" / "clinical" / "uti-001.json",
    ROOT / "tests" / "fixtures" / "check_lines_goldens.json",
]


@pytest.mark.parametrize("path", SHIPPED_CLINICAL_FIXTURES, ids=lambda p: p.name)
def test_the_shipped_fixtures_hold_no_private_engine_detail_or_ruling_names(path):
    text = path.read_text(encoding="utf-8")
    found = [p for p in PRIVATE_DETAIL if re.search(p, text)]
    assert found == []


def test_the_uti_001_evidence_summaries_point_to_the_source_and_give_no_regimen():
    """Each evidence summary says what the source is cited for. The dose, duration, pregnancy
    and renal statements stay in the cited source, not in this file."""
    doc = json.loads(SHIPPED_CLINICAL_FIXTURES[0].read_text(encoding="utf-8"))
    regimen = re.compile(
        r"\d\s*(?:mg|g)\b|\btwice daily\b|\bthree times daily\b|\bx\s*\d+\s*days?\b"
        r"|\bavoid\b|\bfirst-line\b|\bCrCl\b|\btrimester\b|\bat term\b"
    )
    for entry in doc["evidence"].values():
        for field in ("summary", "full_citation"):
            assert regimen.search(entry[field]) is None, (entry["id"], field)

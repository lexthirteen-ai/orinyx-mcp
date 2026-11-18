"""No file the source distribution ships holds a short internal id.

The archive on PyPI is kept for good. A short internal id, a capital L and a number with an
optional letter, or a tracker key and a number, means nothing to a reader of the package and
stays in every copy of the release once it is uploaded. This test reads every UTF-8 file the
release manifest lists for the source distribution and names each such id by file and line. A
test that needs one as an example builds it from pieces, as this file does.
"""

import json
import re

import pytest
from orinyx_mcp import __version__

from tests.test_install_docs import ROOT

MANIFEST = ROOT / "release" / "manifests" / f"{__version__}.json"
INTERNAL_ID = re.compile(r"\bL[0-9]+[a-z]?\b|\bCHA-[0-9]+\b")
INTERNAL_RULING = re.compile(
    r"\b(?:ingest[_]quarantine|dose[_]ceiling[_]held)\b"
    r"|\b(?:ruling|owner\s+decision)\s+\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:approved\s+by|ruling\s+by)\s+[L]ex\b",
    re.IGNORECASE,
)


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


def internal_ids(text: str) -> list[str]:
    """Each internal id in `text`, as `line: id`, in order."""
    return [
        f"{number}: {match.group(0)}"
        for number, line in enumerate(text.split("\n"), start=1)
        for match in INTERNAL_ID.finditer(line)
    ]


def test_the_packaged_files_are_read():
    files = packaged_text_files()
    assert {
        "README.md",
        "CHANGELOG.md",
        "orinyx_mcp/server.py",
        "tests/fixtures/check_lines_goldens.json",
        "tests/fixtures/clinical/uti-001.json",
    } <= set(files)
    assert "tests/test_packaged_files_hold_no_internal_ids.py" in files


@pytest.mark.parametrize("rel", packaged_text_files())
def test_no_packaged_file_holds_an_internal_id(rel):
    assert internal_ids((ROOT / rel).read_bytes().decode("utf-8")) == []


@pytest.mark.parametrize("rel", packaged_text_files())
def test_no_packaged_file_holds_an_internal_ruling_note(rel):
    contents = (ROOT / rel).read_text(encoding="utf-8")
    found = [
        f"{number}: {match.group(0)}"
        for number, line in enumerate(contents.splitlines(), start=1)
        for match in INTERNAL_RULING.finditer(line)
    ]
    assert found == []


@pytest.mark.parametrize(
    "note",
    [
        "dose_ceiling" + "_held",
        "ingest" + "_quarantine",
        "Lex ruling " + "2026-10-21",
        "owner decision " + "2026-09-29",
        "approved by " + "Lex",
    ],
)
def test_the_pattern_finds_internal_ruling_notes(note):
    assert INTERNAL_RULING.search(note)


@pytest.mark.parametrize(
    "text",
    # Assembled, so that this packaged file holds no internal id of its own.
    ["waits on the " + "L" + "9 engine update", "(" + "L" + "5b)", "see " + "L" + "12."],
)
def test_the_pattern_finds_an_internal_id(text):
    assert internal_ids(text) != []


@pytest.mark.parametrize(
    "text",
    ["HTML5 and CSS3", "level 9", "L-arginine 500 mg", "5 mL every 8 hours", "Lisinopril 10 mg"],
)
def test_the_pattern_leaves_ordinary_text_alone(text):
    assert internal_ids(text) == []

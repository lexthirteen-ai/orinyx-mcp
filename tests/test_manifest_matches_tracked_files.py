"""The release manifest lists exactly the files a release would hold.

`release/manifests/<version>.json` is the reviewed list of the files in the source distribution
and in the wheel. The release workflow compares the built archives with it, so a packaged file
with no line there stops a release on the day of the tag. This test makes the comparison on
every push, and builds nothing: the files git tracks (a new file counts from the moment it is
staged), selected the way `pyproject.toml` selects them, against the manifest of the version in
`orinyx_mcp/__init__.py`.

- Source distribution: every tracked file under `orinyx_mcp/` and `tests/`, the four top-level
  files, `.gitignore` (the build backend always copies it) and `PKG-INFO` (the build writes it).
- Wheel: every tracked file under `orinyx_mcp/`. Its `dist-info` entries are written by the
  build and are not compared here.

Both directions are checked: a packaged file with no line, and a line with no file. Outside a
git checkout (an unpacked source distribution, for example) there is no list of tracked files,
and the comparison is skipped.
"""

import json
import subprocess
from pathlib import Path

import pytest
from orinyx_mcp import __version__

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "release" / "manifests" / f"{__version__}.json"
TOP_LEVEL = {"README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml"}
PACKAGED = ("orinyx_mcp/", "tests/")
ADDED_BY_THE_BUILD = {"PKG-INFO", ".gitignore"}


def compare(tracked: set[str], manifest: dict) -> dict[str, list[str]]:
    """Every disagreement between the tracked files and a manifest, by kind. Empty when the
    manifest lists exactly what a release built from these files would hold."""
    package = {name for name in tracked if name.startswith("orinyx_mcp/")}
    wheel = {name for name in manifest["wheel"] if name.startswith("orinyx_mcp/")}
    found = {
        "in the package, but not in the wheel list": package - wheel,
        "in the wheel list, but not a tracked file": wheel - package,
    }
    if "sdist" in manifest:  # a wheel-only release has no source distribution list
        packaged = {name for name in tracked if name in TOP_LEVEL or name.startswith(PACKAGED)}
        expected = packaged | ADDED_BY_THE_BUILD
        found["packaged, but not in the sdist list"] = expected - set(manifest["sdist"])
        found["in the sdist list, but not a tracked file"] = set(manifest["sdist"]) - expected
    return {kind: sorted(names) for kind, names in found.items() if names}


def tracked_files() -> set[str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout.decode()
    except (OSError, subprocess.SubprocessError):
        listed = ""
    names = {name for name in listed.split("\0") if name}
    if not names:
        pytest.skip("not a git checkout: there is no list of tracked files to compare with")
    return names


def test_the_manifest_of_this_version_lists_exactly_the_tracked_files_a_release_holds():
    tracked = tracked_files()
    assert MANIFEST.is_file(), f"release/manifests/{__version__}.json is missing"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["version"] == __version__
    assert compare(tracked, manifest) == {}


# --- the comparison itself, on made-up lists -----------------------------------------------

TRACKED = {
    ".gitignore",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "pyproject.toml",
    "orinyx_mcp/__init__.py",
    "orinyx_mcp/assets/icon.svg",
    "tests/test_example.py",
    # Tracked, and never packaged: no line is expected for any of these.
    "SECURITY.md",
    "docs/QUICKSTART.md",
    "docs/orinyx_mcp/notes.md",
    "scripts/check_dist.py",
    "release/manifests/9.9.9.json",
    ".github/workflows/ci.yml",
}
LISTED = {
    "version": "9.9.9",
    "sdist": [
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "PKG-INFO",
        "README.md",
        "orinyx_mcp/__init__.py",
        "orinyx_mcp/assets/icon.svg",
        "pyproject.toml",
        "tests/test_example.py",
    ],
    "wheel": [
        "orinyx_mcp-9.9.9.dist-info/METADATA",
        "orinyx_mcp-9.9.9.dist-info/RECORD",
        "orinyx_mcp/__init__.py",
        "orinyx_mcp/assets/icon.svg",
    ],
}


def test_a_complete_manifest_has_nothing_to_report():
    assert compare(TRACKED, LISTED) == {}


def test_a_new_test_file_with_no_line_is_named():
    assert compare(TRACKED | {"tests/test_new.py"}, LISTED) == {
        "packaged, but not in the sdist list": ["tests/test_new.py"]
    }


def test_a_new_package_file_with_no_line_is_named_for_both_archives():
    assert compare(TRACKED | {"orinyx_mcp/new.py"}, LISTED) == {
        "in the package, but not in the wheel list": ["orinyx_mcp/new.py"],
        "packaged, but not in the sdist list": ["orinyx_mcp/new.py"],
    }


def test_a_line_left_behind_by_a_removed_or_renamed_file_is_named():
    assert compare(TRACKED - {"tests/test_example.py", "orinyx_mcp/assets/icon.svg"}, LISTED) == {
        "in the wheel list, but not a tracked file": ["orinyx_mcp/assets/icon.svg"],
        "in the sdist list, but not a tracked file": [
            "orinyx_mcp/assets/icon.svg",
            "tests/test_example.py",
        ],
    }


def test_a_wheel_only_manifest_is_compared_on_the_wheel_alone():
    wheel_only = {"version": "9.9.9", "wheel_only": True, "wheel": LISTED["wheel"]}
    assert compare(TRACKED | {"tests/test_new.py"}, wheel_only) == {}
    assert compare(TRACKED | {"orinyx_mcp/new.py"}, wheel_only) == {
        "in the package, but not in the wheel list": ["orinyx_mcp/new.py"]
    }

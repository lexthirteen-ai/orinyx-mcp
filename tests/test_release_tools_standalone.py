"""The release tools as they are run in a release: a fresh interpreter, started on the file.

The other tests load the scripts into a process that has already imported much of the standard
library and the package, so an import the script forgot would go unnoticed there. These tests
start `python -I scripts/<name>.py` the way a workflow step does, and read the pinned
build-tool lock as text.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / name), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT.parent,
    )


@pytest.mark.parametrize("name", ["check_build_inputs.py", "check_dist.py", "e2e_install_check.py"])
def test_the_script_starts_in_a_fresh_isolated_interpreter(name):
    result = run_script(name, "--help")
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert "usage:" in result.stdout


def test_check_dist_exits_one_on_a_missing_directory_without_a_traceback(tmp_path):
    manifest = ROOT / "release" / "manifests" / "0.1.5.json"
    result = run_script("check_dist.py", str(tmp_path / "nowhere"), "--manifest", str(manifest))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "FAIL" in result.stdout + result.stderr


def test_check_dist_prints_the_shape_of_the_committed_manifest():
    manifest = ROOT / "release" / "manifests" / "0.1.5.json"
    result = run_script("check_dist.py", "--manifest", str(manifest), "--print-shape")
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout.strip()


LOCK = (ROOT / "requirements-release.lock").read_text()


def lock_requirements():
    """(name, version, hash count) for each pinned requirement in the lock."""
    found = []
    blocks = re.split(r"\n(?=[A-Za-z0-9][A-Za-z0-9._-]*==)", LOCK)
    for block in blocks:
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", block)
        if match:
            found.append(
                (match[1].lower(), match[2], len(re.findall(r"--hash=sha256:[0-9a-f]{64}", block)))
            )
    return found


def test_the_lock_pins_the_three_build_tools():
    names = {name for name, _, _ in lock_requirements()}
    assert {"build", "twine", "hatchling"} <= names


def test_every_pin_in_the_lock_carries_a_hash():
    pins = lock_requirements()
    assert len(pins) > 3
    assert all(count >= 1 for _, _, count in pins), [n for n, _, c in pins if c < 1]


def test_no_line_of_the_lock_is_an_unpinned_or_unhashed_requirement():
    for line in LOCK.splitlines():
        text = line.strip()
        if not text or text.startswith(("#", "--hash=")):
            continue
        assert re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*==\S+", text), line
        assert not re.search(r"(^|\s)(-e|--index-url|--extra-index-url|git\+|https?://)", text), (
            line
        )


def test_the_lock_pins_hatchling_at_or_above_the_floor():
    version = next(v for n, v, _ in lock_requirements() if n == "hatchling")
    major, minor = (int(part) for part in version.split(".")[:2])
    assert (major, minor) >= (1, 27)

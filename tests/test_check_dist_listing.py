"""The inline check the publish jobs run: `dist/` holds exactly the files SHA256SUMS lists.

The text under test is `LISTING_CHECK` in `scripts/lint_release_workflow.py`, which the lint
requires the workflow to hold verbatim. It is run here with bash, the way a workflow step runs.
"""

import hashlib
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "lint_release_workflow", ROOT / "scripts" / "lint_release_workflow.py"
)
lint_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_mod)

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")


def make_dist(base, files, listed=None, mark=" "):
    dist = base / "dist"
    dist.mkdir()
    for name in files:
        (dist / name).write_text(name)
    names = files if listed is None else listed
    lines = [f"{hashlib.sha256(n.encode()).hexdigest()} {mark}{n}\n" for n in names]
    (dist / "SHA256SUMS").write_text("".join(lines))
    return dist


def check(base):
    return subprocess.run(
        ["bash", "-eo", "pipefail", "-c", lint_mod.LISTING_CHECK],
        cwd=base,
        capture_output=True,
        text=True,
        timeout=60,
    )


FILES = ["orinyx_mcp-1.0-py3-none-any.whl", "orinyx_mcp-1.0.tar.gz"]


def test_equal_sets_pass(tmp_path):
    make_dist(tmp_path, FILES)
    assert check(tmp_path).returncode == 0


def test_a_binary_mode_listing_passes(tmp_path):
    make_dist(tmp_path, FILES, mark="*")
    assert check(tmp_path).returncode == 0


def test_the_order_of_the_listing_does_not_matter(tmp_path):
    make_dist(tmp_path, FILES, listed=list(reversed(FILES)))
    assert check(tmp_path).returncode == 0


def test_a_wheel_only_set_passes(tmp_path):
    make_dist(tmp_path, FILES[:1])
    assert check(tmp_path).returncode == 0


def test_an_extra_file_is_refused(tmp_path):
    make_dist(tmp_path, FILES + ["orinyx_mcp-9.9-evil.whl"], listed=FILES)
    result = check(tmp_path)
    assert result.returncode == 1
    assert "orinyx_mcp-9.9-evil.whl" in result.stdout
    assert "not exactly the files" in result.stdout


def test_a_missing_file_is_refused(tmp_path):
    dist = make_dist(tmp_path, FILES)
    (dist / FILES[1]).unlink()
    assert check(tmp_path).returncode == 1


def test_a_listed_name_with_no_file_is_refused(tmp_path):
    make_dist(tmp_path, FILES, listed=FILES + ["ghost.whl"])
    assert check(tmp_path).returncode == 1


def test_a_directory_in_dist_is_refused(tmp_path):
    dist = make_dist(tmp_path, FILES)
    (dist / "sub").mkdir()
    assert check(tmp_path).returncode == 1


def test_a_hidden_extra_file_is_refused(tmp_path):
    dist = make_dist(tmp_path, FILES)
    (dist / ".hidden.whl").write_text("x")
    assert check(tmp_path).returncode == 1


def test_a_duplicate_listing_is_refused(tmp_path):
    make_dist(tmp_path, FILES, listed=FILES + FILES[:1])
    assert check(tmp_path).returncode == 1


def test_a_listing_that_names_itself_is_refused(tmp_path):
    make_dist(tmp_path, FILES, listed=FILES + ["SHA256SUMS"])
    assert check(tmp_path).returncode == 1


def test_an_empty_listing_with_files_is_refused(tmp_path):
    make_dist(tmp_path, FILES, listed=[])
    assert check(tmp_path).returncode == 1

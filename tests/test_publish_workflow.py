"""Tag-only OIDC publishing keeps source execution out of the privileged job."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from orinyx_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/publish.yml").read_text()
SPEC = importlib.util.spec_from_file_location(
    "release_lint", ROOT / "scripts/lint_release_workflow.py"
)
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)
JOBS = lint.jobs(WORKFLOW.splitlines())


def test_only_version_tags_trigger_the_workflow():
    assert lint.triggers(WORKFLOW.splitlines()) == ["  push:", '    tags: ["v*"]']
    assert "\npermissions: {}\n" in WORKFLOW
    assert "group: publish-${{ github.ref_name }}" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW
    assert "secrets." not in WORKFLOW
    assert "password:" not in WORKFLOW
    for line in WORKFLOW.splitlines():
        if match := lint.USES.match(line):
            assert lint.PINNED.fullmatch(match.group(1))
            assert lint.TAG_COMMENT.match(match.group(2))
    for _, line in lint.run_blocks(WORKFLOW.splitlines()):
        assert not lint.python_without_isolation(line)
        assert "${{" not in line


def test_only_the_publish_job_has_oidc_and_it_never_executes_source():
    assert set(JOBS) == {"preflight", "build", "pypi"}
    build = "\n".join(JOBS["build"])
    publish = "\n".join(JOBS["pypi"])
    assert "contents: read" in build and "id-token:" not in build
    assert "persist-credentials: false" in build
    assert build.index("check_build_inputs.py") < build.index("python -I -m build")
    assert "python -I -m pytest -q" in build
    assert "python -I -m twine check --strict dist/*" in build
    assert "needs: [preflight, build]" in publish
    assert "if: ${{ needs.preflight.outputs.target == 'pypi' }}" in publish
    assert "name: pypi" in publish and "id-token: write" in publish
    assert "contents:" not in publish
    assert "actions/download-artifact@" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "actions/checkout" not in publish and "scripts/" not in publish
    assert "python -I" not in publish and "pip install" not in publish
    assert "sha256sum -c SHA256SUMS" in publish
    assert lint.listing_check_before_rm(JOBS["pypi"])
    assert "name: python-distributions" in build and "name: python-distributions" in publish


def test_tag_check_accepts_only_the_exact_package_version():
    step = WORKFLOW.split("- name: Require tag to match the package version", 1)[1]
    code = step.split("python -I - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
    code = "\n".join(line.removeprefix("          ") for line in code.splitlines())
    for tag, expected in [(f"v{__version__}", 0), ("v999.0.0", 1), (__version__, 1)]:
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            cwd=ROOT,
            env=os.environ | {"RELEASE_TAG": tag},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == expected, result.stderr


def test_workflow_satisfies_existing_release_policy_and_artifact_checks():
    assert lint.lint(WORKFLOW) == []
    build = "\n".join(JOBS["build"])
    assert "scripts/lint_release_workflow.py .github/workflows/publish.yml" in build
    assert "scripts/check_dist.py --manifest" in build and "--print-shape" in build
    assert 'scripts/check_dist.py dist --manifest "$manifest" --source . --require-marker' in build
    assert "sha256sum *.whl *.tar.gz > SHA256SUMS" in build


def test_preflight_selects_pypi_only_for_stable_version_tags(tmp_path):
    code = WORKFLOW.split("python -I - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
    code = "\n".join(line.removeprefix("          ") for line in code.splitlines())
    output = tmp_path / "outputs"
    for tag, expected in [(f"v{__version__}", 0), ("v0.1.5rc1", 1), ("main", 1), ("v../x", 1)]:
        output.write_text("")
        result = subprocess.run(
            [sys.executable, "-I", "-c", code],
            env=os.environ | {"RELEASE_TAG": tag, "GITHUB_OUTPUT": str(output)},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == expected, result.stderr
        assert output.read_text() == (f"target=pypi\nversion={tag[1:]}\n" if expected == 0 else "")


def test_owner_checklist_names_the_exact_trusted_publisher():
    docs = (ROOT / "CONTRIBUTING.md").read_text()
    for value in (
        "https://pypi.org/manage/account/publishing/",
        "PyPI project: `orinyx-mcp`",
        "GitHub owner: `lexthirteen-ai`",
        "Repository: `orinyx-mcp`",
        "Workflow filename: `publish.yml`",
        "Environment: `pypi`",
        "**tag** deployment rule",
        "retain the required owner review",
    ):
        assert value in docs

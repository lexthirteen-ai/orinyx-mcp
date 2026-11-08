"""Tag-only OIDC publishing keeps source execution out of the privileged job."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from orinyx_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text()
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


def test_build_is_unprivileged_and_the_legacy_publisher_is_removed():
    assert set(JOBS) == {"preflight", "build", "testpypi", "pypi"}
    assert not (ROOT / ".github/workflows/publish.yml").exists()
    assert "id-token:" not in "\n".join(JOBS["preflight"])
    build = "\n".join(JOBS["build"])
    assert "contents: read" in build and "id-token:" not in build
    assert "persist-credentials: false" in build
    assert build.index("check_build_inputs.py") < build.index("python -I -m build")
    assert "python -I -m pytest -q" in build
    assert "python -I -m twine check --strict dist/*" in build


@pytest.mark.parametrize("job", ["testpypi", "pypi"])
def test_only_publish_jobs_have_oidc_and_they_never_execute_source(job):
    build = "\n".join(JOBS["build"])
    publish = "\n".join(JOBS[job])
    assert f"environment: {job}" in publish and "id-token: write" in publish
    assert "contents:" not in publish
    assert "actions/download-artifact@" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "actions/checkout" not in publish and "scripts/" not in publish
    assert "python -I" not in publish and "pip install" not in publish
    assert "sha256sum -c SHA256SUMS" in publish
    assert lint.listing_check_before_rm(JOBS[job])
    assert "name: python-distributions" in build and "name: python-distributions" in publish


def test_testpypi_must_succeed_before_pypi_and_uses_the_same_allowlisted_action():
    staging = "\n".join(JOBS["testpypi"])
    production = "\n".join(JOBS["pypi"])
    assert "needs: build" in staging
    assert "needs: [build, testpypi]" in production
    for job in (staging, production):
        assert "\n    if:" not in job  # Default success() blocks publication on failure/skip.
    assert "repository-url: https://test.pypi.org/legacy/" in staging
    assert "repository-url:" not in production
    publishers = {
        match.group(1)
        for line in WORKFLOW.splitlines()
        if (match := lint.USES.match(line))
        and match.group(1).startswith("pypa/gh-action-pypi-publish@")
    }
    assert publishers == {"pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086"}
    assert f"# {next(iter(publishers))}\n" in WORKFLOW


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
    assert "scripts/lint_release_workflow.py .github/workflows/release.yml" in build
    assert "scripts/check_dist.py --manifest" in build and "--print-shape" in build
    assert 'scripts/check_dist.py dist --manifest "$manifest" --source . --require-marker' in build
    assert "sha256sum *.whl *.tar.gz > SHA256SUMS" in build


def test_preflight_accepts_only_stable_version_tags(tmp_path):
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
        assert output.read_text() == (f"version={tag[1:]}\n" if expected == 0 else "")


def test_owner_checklist_names_the_exact_trusted_publisher():
    docs = (ROOT / "CONTRIBUTING.md").read_text()
    for value in (
        "https://pypi.org/manage/account/publishing/",
        "https://test.pypi.org/manage/account/publishing/",
        "PyPI project: `orinyx-mcp`",
        "GitHub owner: `lexthirteen-ai`",
        "Repository: `orinyx-mcp`",
        "Workflow filename: `release.yml`",
        "Environment: `pypi`",
        "Environment: `testpypi`",
        "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086",
        "**tag** deployment rule",
        "retain the required owner review",
    ):
        assert value in docs

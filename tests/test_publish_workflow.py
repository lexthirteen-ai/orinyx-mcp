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
    assert set(JOBS) == {"build", "pypi"}
    build = "\n".join(JOBS["build"])
    publish = "\n".join(JOBS["pypi"])
    assert "contents: read" in build and "id-token:" not in build
    assert "persist-credentials: false" in build
    assert build.index("check_build_inputs.py") < build.index("python -I -m build")
    assert "python -I -m pytest -q" in build
    assert "python -I -m twine check --strict dist/*" in build
    assert "needs: build" in publish
    assert "if: startsWith(github.ref, 'refs/tags/v')" in publish
    assert "name: pypi" in publish and "id-token: write" in publish
    assert "contents:" not in publish
    assert "actions/download-artifact@" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "actions/checkout" not in publish and "run:" not in publish
    assert "name: python-distributions" in build and "name: python-distributions" in publish


def test_tag_check_accepts_only_the_exact_package_version():
    code = WORKFLOW.split("python -I - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
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

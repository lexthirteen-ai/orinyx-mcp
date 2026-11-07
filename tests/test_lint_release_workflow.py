"""`scripts/lint_release_workflow.py` refuses a release workflow that breaks the publishing rules.

The workflow file itself is not part of this repository; these tests use a small stand-in
with the same shape and change one thing at a time.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "lint_release_workflow", ROOT / "scripts" / "lint_release_workflow.py"
)
lint_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_mod)

SHA = "0123456789abcdef0123456789abcdef01234567"

LISTING = "\n".join(" " * 10 + line for line in lint_mod.LISTING_CHECK.splitlines())

GOOD = f"""\
name: release
on:
  push:
    tags: ["v*"]
permissions: {{}}
concurrency:
  group: release-${{{{ github.ref_name }}}}
  cancel-in-progress: false
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@{SHA} # v7.0.1
      - name: Inputs
        run: python -I workflow/scripts/check_build_inputs.py tag
      - name: Use the tag
        env:
          TAG: ${{{{ github.ref_name }}}}
        run: |
          echo "$TAG"
          (cd tag && python -I -m build --wheel)
          "$RUNNER_TEMP/venv/bin/python" -I -m pip --version
          python3 -I workflow/scripts/check_dist.py dist --manifest m.json --source tag
      - name: Shape
        run: |
          python -I workflow/scripts/check_dist.py --manifest m.json --print-shape >> "$OUT"
      # python -m build is only a comment
  testpypi:
    needs: build
    if: ${{{{ needs.preflight.outputs.target == 'testpypi' }}}}
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - name: Only the distributions go up
        run: |
          (cd dist && sha256sum -c SHA256SUMS)
{LISTING}
          rm -f dist/SHA256SUMS
      - uses: pypa/gh-action-pypi-publish@{SHA} # v1.14.3
  pypi:
    needs: build
    if: ${{{{ needs.preflight.outputs.target == 'pypi' }}}}
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - name: Only the distributions go up
        run: |
          (cd dist && sha256sum -c SHA256SUMS)
{LISTING}
          rm -f dist/SHA256SUMS
      - uses: pypa/gh-action-pypi-publish@{SHA} # v1.14.3
  draft-release:
    needs: pypi
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - run: echo done
      - name: Notes
        run: |
          echo "gh attestation verify f --repo r --signer-workflow r/.github/workflows/release.yml"
"""


def test_the_stand_in_is_clean():
    assert lint_mod.lint(GOOD) == []


def mutated(old: str, new: str) -> str:
    assert old in GOOD
    return GOOD.replace(old, new)


@pytest.mark.parametrize(
    "text, expected",
    [
        (mutated(f"actions/checkout@{SHA} # v7.0.1", "actions/checkout@v4"), "full sha"),
        (mutated(f"actions/checkout@{SHA} # v7.0.1", f"actions/checkout@{SHA}"), "full sha"),
        (mutated(f"actions/checkout@{SHA} # v7.0.1", "actions/checkout@<sha> # v7"), "full sha"),
        (mutated(f"@{SHA} # v1.14.3", "@release/v1"), "full sha"),
        (mutated(f"@{SHA} # v1.14.3", f"@{SHA[:39]} # v1"), "full sha"),
        (mutated("  push:", "  pull_request:\n  push:"), "triggers"),
        (mutated("  push:", "  workflow_run:\n  push:"), "triggers"),
        (mutated("  push:", "  workflow_dispatch:\n  push:"), "triggers"),
        (mutated('    tags: ["v*"]', '    tags: ["*"]'), "triggers"),
        (mutated('    tags: ["v*"]', '    tags: ["v*"]\n    branches: ["main"]'), "triggers"),
        (mutated("  push:", "  release:\n  push:"), "triggers"),
        (mutated("  push:", "  schedule:\n  push:"), "triggers"),
        (mutated("  push:", "  pull_request_target:\n  push:"), "triggers"),
        (mutated("permissions: {}\n", ""), "permissions: {}"),
        (mutated("cancel-in-progress: false", "cancel-in-progress: true"), "cancel-in-progress"),
        (mutated('echo "$TAG"', 'echo "${{ github.ref_name }}"'), "run block"),
        (mutated('echo "$TAG"', 'echo "${{ inputs.tag }}"'), "run block"),
        (mutated('echo "$TAG"', 'echo "${{ github.event.inputs.tag }}"'), "run block"),
        (mutated("- run: echo done", "- run: echo ${{ inputs.tag }}"), "run block"),
        (
            mutated(
                "    permissions:\n      contents: read", "    permissions:\n      id-token: write"
            ),
            "job 'build' holds id-token: write",
        ),
        (
            mutated(
                "    permissions:\n      contents: read", "    permissions:\n      contents: write"
            ),
            "job 'build' holds contents: write",
        ),
        (mutated("    permissions:\n      contents: read\n", ""), "sets no permissions"),
        (mutated("python -I -m build", "python -m build"), "lacks -I"),
        (mutated("python3 -I workflow", "python3 workflow"), "lacks -I"),
        (
            mutated('"$RUNNER_TEMP/venv/bin/python" -I', '"$RUNNER_TEMP/venv/bin/python"'),
            "lacks -I",
        ),
        (
            mutated("-m pip --version", "-m pip --version\n          python -c 'print(1)'"),
            "lacks -I",
        ),
        (mutated(" --print-shape >>", " >>"), "never read with --print-shape"),
        (
            mutated(
                "echo done", 'python -I -c \'import json; print("sdist" in json.load(open("m")))\''
            ),
            "tests for an sdist key itself",
        ),
        (
            mutated(f"@{SHA} # v1.14.3", f"@{SHA} # v1.14.3\n        with:\n          password: x"),
            "credential setting",
        ),
        (mutated("echo done", "echo ${{ secrets.X }}"), "secrets.*"),
        (
            mutated(f"@{SHA} # v7.0.1", f"@{SHA} # v7.0.1\n        with:\n          cache: pip"),
            "cache",
        ),
    ],
)
def test_each_violation_is_reported(text, expected):
    failures = lint_mod.lint(text)
    assert failures
    assert any(expected in failure for failure in failures)


CHECK_STEP = (
    "      - name: Inputs\n        run: python -I workflow/scripts/check_build_inputs.py tag\n"
)
LATE = GOOD.replace(CHECK_STEP, "").replace(
    "      # python -m build is only a comment",
    CHECK_STEP + "      # python -m build is only a comment",
)


@pytest.mark.parametrize(
    "text, expected",
    [
        (GOOD.replace(CHECK_STEP, ""), "does not run check_build_inputs.py"),
        (LATE, "does not run check_build_inputs.py"),
        (mutated(lint_mod.LISTING_CHECK.splitlines()[0].strip(), "true"), "dist listing check"),
        (mutated("          rm -f dist/SHA256SUMS", "          true"), "dist listing check"),
        (
            GOOD.replace(LISTING, "").replace(
                "          rm -f dist/SHA256SUMS",
                "          rm -f dist/SHA256SUMS\n" + LISTING,
            ),
            "dist listing check",
        ),
        (mutated("release-${{ github.ref_name }}", "release"), "github.ref_name"),
        (mutated("TAG: ${{ github.ref_name }}", "TAG: ${{ inputs.tag }}"), "reads inputs."),
        (mutated("target == 'pypi'", "target != 'testpypi'"), "only on target pypi"),
        (mutated("target == 'testpypi'", "target != 'pypi'"), "only on target testpypi"),
        (mutated("--signer-workflow r/.github/workflows/release.yml", ""), "--signer-workflow"),
    ],
)
def test_each_release_machinery_rule_is_enforced(text, expected):
    failures = lint_mod.lint(text)
    assert any(expected in failure for failure in failures), failures


def test_an_expression_in_env_or_with_is_allowed():
    assert (
        lint_mod.lint(
            GOOD.replace("echo done", "echo done\n        env:\n          A: ${{ github.sha }}")
        )
        == []
    )


def test_main_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.yml"
    good.write_text(GOOD)
    bad = tmp_path / "bad.yml"
    bad.write_text(GOOD.replace(f"@{SHA} # v7.0.1", "@v4"))
    assert lint_mod.main([str(good)]) == 0
    assert lint_mod.main([str(bad)]) == 1
    assert "FAIL: line" in capsys.readouterr().out
    assert lint_mod.main([]) == 1

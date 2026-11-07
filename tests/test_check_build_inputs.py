"""`scripts/check_build_inputs.py` refuses a tree whose build would run code the tree supplies."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_build_inputs", ROOT / "scripts" / "check_build_inputs.py"
)
cbi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cbi)

GOOD = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "x"
dynamic = ["version"]

[tool.hatch.version]
path = "x/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["x"]
"""
BACKEND_PATH = GOOD.replace(
    'build-backend = "hatchling.build"', 'build-backend = "hatchling.build"\nbackend-path = ["."]'
)


def tree(tmp_path, pyproject=GOOD):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "__init__.py").write_text('__version__ = "1"\n')
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_bytes(pyproject.encode("latin-1"))
    return tmp_path


def run(path):
    return subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "check_build_inputs.py"), str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT.parent,
    )


def test_this_repository_passes():
    assert cbi.check_tree(ROOT) == []
    result = run(ROOT)
    assert result.returncode == 0, result.stdout
    assert "check_build_inputs: ok" in result.stdout


def test_a_plain_hatchling_tree_passes(tmp_path):
    assert cbi.check_tree(tree(tmp_path)) == []


@pytest.mark.parametrize(
    "pyproject, expected",
    [
        (GOOD.replace('"hatchling.build"', '"setuptools.build_meta"'), "build-backend"),
        (GOOD.replace('build-backend = "hatchling.build"\n', ""), "build-backend"),
        (BACKEND_PATH, "backend-path"),
        (GOOD + '\n[tool.hatch.build.hooks.custom]\npath = "h.py"\n', "tool.hatch.build.hooks"),
        (GOOD + "\n[tool.hatch.metadata.hooks.custom]\n", "tool.hatch.metadata.hooks"),
        (GOOD + "\n[tool.hatch.build.targets.wheel.hooks.custom]\n", "wheel.hooks"),
        (GOOD.replace('path = "x/__init__.py"', 'source = "code"\npath = "v.py"'), "source"),
        (GOOD.replace("[build-system]", "[nothing]"), "build-system"),
        ("[build-system\nbroken", "does not parse"),
        ("\xff\xfe", "does not parse"),
    ],
)
def test_each_pyproject_problem_is_refused(tmp_path, pyproject, expected):
    path = tree(tmp_path, pyproject)
    failures = cbi.check_tree(path)
    assert any(expected in failure for failure in failures), failures
    result = run(path)
    assert result.returncode == 1
    assert "check_build_inputs: FAIL" in result.stdout


def test_a_missing_pyproject_is_refused(tmp_path):
    failures = cbi.check_tree(tree(tmp_path, None))
    assert any("no pyproject.toml" in failure for failure in failures)
    assert run(tmp_path).returncode == 1


def test_a_missing_directory_is_refused(tmp_path):
    result = run(tmp_path / "nowhere")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("name", ["hatch_build.py", "hatch_build_extra.py", "hatch_build"])
def test_a_custom_hook_file_at_the_top_is_refused(tmp_path, name):
    path = tree(tmp_path)
    (path / name).write_text("print('hook')\n")
    assert any("hatch_build" in failure for failure in cbi.check_tree(path))
    assert run(path).returncode == 1


def test_a_file_symlink_is_refused(tmp_path):
    path = tree(tmp_path)
    (path / "x" / "link.py").symlink_to("__init__.py")
    assert any("link.py is a symbolic link" in failure for failure in cbi.check_tree(path))
    assert run(path).returncode == 1


def test_a_directory_symlink_and_a_dangling_one_are_refused(tmp_path):
    path = tree(tmp_path)
    (path / "dirlink").symlink_to("x")
    (path / "dangling").symlink_to("nowhere")
    failures = cbi.check_tree(path)
    assert any("dirlink" in failure for failure in failures)
    assert any("dangling" in failure for failure in failures)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_symlink_in_the_git_index_is_refused_and_a_clean_checkout_passes(tmp_path):
    path = tree(tmp_path)

    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("add", "-A")
    assert cbi.check_tree(path) == []
    (path / "x" / "link.py").symlink_to("__init__.py")
    git("add", "-A")
    failures = cbi.check_tree(path)
    assert any("symbolic link in the git index" in failure for failure in failures), failures


HATCH_TOML_HOOK = '[build.hooks.custom]\npath = "anything.py"\n'
HATCH_TOML_VERSION = '[version]\nsource = "code"\npath = "version_source.py"\n'
HATCH_TOML_TARGET_HOOK = '[build.targets.wheel.hooks.custom]\npath = "anything.py"\n'


@pytest.mark.parametrize(
    "content",
    [HATCH_TOML_HOOK, HATCH_TOML_VERSION, HATCH_TOML_TARGET_HOOK, ""],
    ids=["build-hook", "version-source-code", "per-target-hook", "empty"],
)
def test_a_hatch_toml_beside_pyproject_is_refused(tmp_path, content):
    path = tree(tmp_path)
    (path / "hatch.toml").write_text(content)
    (path / "anything.py").write_text("print('code from the tree')\n")
    failures = cbi.check_tree(path)
    assert any("hatch.toml" in failure for failure in failures), failures
    result = run(path)
    assert result.returncode == 1
    assert "check_build_inputs: FAIL" in result.stdout


@pytest.mark.parametrize(
    "name",
    [
        "Hatch.toml",
        "HATCH.TOML",
        ".hatch.toml",
        "hatch.local.toml",
        ".Hatch.Local.TOML",
        "hatch-x.toml",
    ],
)
def test_every_spelling_of_a_hatch_toml_at_the_top_is_refused(tmp_path, name):
    path = tree(tmp_path)
    (path / name).write_text(HATCH_TOML_HOOK)
    failures = cbi.check_tree(path)
    assert any("hatch configuration" in failure for failure in failures), failures
    assert run(path).returncode == 1


def test_files_that_only_resemble_a_hatch_toml_pass(tmp_path):
    path = tree(tmp_path)
    (path / "hatch.md").write_text("notes\n")
    (path / "x" / "hatch.toml").write_text(
        ""
    )  # not beside pyproject.toml; hatchling reads only the top
    (path / "xhatch.toml").write_text("")
    assert cbi.check_tree(path) == []


@pytest.mark.parametrize(
    "hook_path", ["setup_the_wheel.py", "tools/build/anything.py", "x/hook.py"]
)
def test_a_pyproject_hook_is_refused_whatever_its_path_is_called(tmp_path, hook_path):
    path = tree(tmp_path, GOOD + f'\n[tool.hatch.build.hooks.custom]\npath = "{hook_path}"\n')
    (path / "setup_the_wheel.py").write_text("print('code from the tree')\n")
    failures = cbi.check_tree(path)
    assert any("tool.hatch.build.hooks" in failure for failure in failures), failures
    assert run(path).returncode == 1


def test_a_tree_without_any_hatch_toml_passes_under_the_script(tmp_path):
    path = tree(tmp_path)
    result = run(path)
    assert result.returncode == 0, result.stdout
    assert "check_build_inputs: ok" in result.stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_git_export_of_this_repository_passes(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "HEAD"], capture_output=True, timeout=60
    )
    if archive.returncode != 0:
        pytest.skip("not a git checkout")
    subprocess.run(["tar", "-x", "-C", str(export)], input=archive.stdout, check=True, timeout=60)
    assert cbi.check_tree(export) == []
    assert run(export).returncode == 0

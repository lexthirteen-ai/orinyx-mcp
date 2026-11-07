"""Imports the release tools forgot, caught on any Python.

A script that uses `email.message.Message` after only `import email` works wherever some other
module has already loaded the submodule, and fails with an AttributeError where none has (it
did on Python 3.11 to 3.13 and not on 3.14). Two checks here:

* a static one that does not depend on the interpreter running the tests: every `pkg.sub`
  reference to a standard-library submodule must have `import pkg.sub` in the same file;
* a run of each script, started as a fresh isolated process, under every other Python
  interpreter found on this machine (set ORINYX_EXTRA_PYTHONS to a path list to add more).
  A candidate that does not start at all is left out: `shutil.which` can return a pyenv shim
  for a Python that is not enabled, which exits 127 whatever it is asked to run.
"""

import ast
import os
import pkgutil
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "check_build_inputs.py",
    "check_dist.py",
    "e2e_install_check.py",
    "lint_release_workflow.py",
]


def submodule_references(tree):
    """Dotted names `pkg.sub` used in the file where `pkg` is a name imported with `import pkg`."""
    roots = set()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
                roots.add(alias.name.split(".")[0])
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = []
            inner = node
            while isinstance(inner, ast.Attribute):
                chain.append(inner.attr)
                inner = inner.value
            if isinstance(inner, ast.Name) and inner.id in roots:
                chain.append(inner.id)
                chain.reverse()
                used.add(tuple(chain))
    return used, imported


def is_stdlib_submodule(package, name):
    if package not in sys.stdlib_module_names:
        return False
    module = sys.modules.get(package)
    if module is None:
        try:
            module = __import__(package)
        except ImportError:
            return False
    path = getattr(module, "__path__", None)
    if not path:
        return False
    return any(info.name == name for info in pkgutil.iter_modules(path))


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_stdlib_submodule_a_script_uses_is_imported_by_it(name):
    tree = ast.parse((ROOT / "scripts" / name).read_text(), filename=name)
    used, imported = submodule_references(tree)
    missing = []
    for chain in used:
        for depth in range(1, len(chain)):
            if is_stdlib_submodule(chain[depth - 1], chain[depth]) and chain[depth - 1] == chain[0]:
                dotted = ".".join(chain[: depth + 1])
                if not any(i == dotted or i.startswith(dotted + ".") for i in imported):
                    missing.append(dotted)
    assert not missing, f"{name} uses {sorted(set(missing))} without importing them"


def interpreter_starts(path):
    """Does this interpreter start? It runs none of the tools, so it cannot hide their failures.

    It runs in the directory the scripts run in, because a pyenv shim picks its Python by directory.
    """
    try:
        result = subprocess.run(
            [path, "-I", "-c", "pass"], capture_output=True, timeout=30, cwd=ROOT.parent
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def other_pythons():
    found = {}
    candidates = [f"python3.{minor}" for minor in range(11, 15)]
    paths = [shutil.which(c) for c in candidates]
    paths += [p for p in os.environ.get("ORINYX_EXTRA_PYTHONS", "").split(os.pathsep) if p]
    for path in paths:
        if path and Path(path).exists() and interpreter_starts(path):
            found[str(Path(path).resolve())] = path
    return sorted(found.values())


def assert_script_starts(python, script, tmp_path):
    """The lint takes a file, not --help; an empty workflow makes it print FAIL lines and exit 1."""
    if script.name == "lint_release_workflow.py":
        empty = tmp_path / "empty.yml"
        empty.write_text("name: empty\n")
        args, expected = [str(empty)], 1
    else:
        args, expected = ["--help"], 0
    result = subprocess.run(
        [python, "-I", str(script), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT.parent,
    )
    assert result.returncode == expected, result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("python", other_pythons() or [pytest.param(None, marks=pytest.mark.skip)])
@pytest.mark.parametrize("name", SCRIPTS)
def test_each_script_starts_under_every_python_found(python, name, tmp_path):
    assert_script_starts(python, ROOT / "scripts" / name, tmp_path)


def fake_python(path, body):
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return str(path)


def only_these_candidates(monkeypatch, *paths):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("ORINYX_EXTRA_PYTHONS", os.pathsep.join(str(p) for p in paths))


def test_a_candidate_that_does_not_start_is_left_out(tmp_path, monkeypatch):
    shim = fake_python(tmp_path / "shim", "echo 'pyenv: command not found' >&2\nexit 127")
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("")
    only_these_candidates(monkeypatch, shim, not_executable, tmp_path / "gone", sys.executable)
    assert other_pythons() == [sys.executable]


def test_the_probe_only_starts_the_interpreter_where_the_scripts_run(tmp_path, monkeypatch):
    log = tmp_path / "log"
    recorder = fake_python(tmp_path / "recorder", f'pwd -P > "{log}"\necho "$@" >> "{log}"')
    only_these_candidates(monkeypatch, recorder)
    assert other_pythons() == [recorder]
    assert log.read_text().splitlines() == [str(ROOT.parent), "-I -c pass"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_a_broken_import_in_a_script_still_fails_under_a_python_that_starts(
    name, tmp_path, monkeypatch
):
    only_these_candidates(monkeypatch, sys.executable)
    [python] = other_pythons()
    text = (ROOT / "scripts" / name).read_text()
    script = tmp_path / name
    script.write_text(text)
    assert_script_starts(python, script, tmp_path)  # the same script, before it is broken
    script.write_text("import orinyx_no_such_module\n" + text)
    with pytest.raises(AssertionError):
        assert_script_starts(python, script, tmp_path)


@pytest.mark.parametrize("name", SCRIPTS)
def test_a_python_that_starts_but_fails_the_import_is_kept_and_still_fails(
    name, tmp_path, monkeypatch
):
    body = (
        'if [ "$2" = "-c" ]; then exit 0; fi\n'
        "echo 'Traceback (most recent call last):' >&2\n"
        "echo 'AttributeError: module email has no attribute message' >&2\n"
        "exit 1"
    )
    broken = fake_python(tmp_path / "broken", body)
    only_these_candidates(monkeypatch, broken)
    assert other_pythons() == [broken]
    with pytest.raises(AssertionError):
        assert_script_starts(broken, ROOT / "scripts" / name, tmp_path)

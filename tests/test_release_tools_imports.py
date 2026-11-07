"""Imports the release tools forgot, caught on any Python.

A script that uses `email.message.Message` after only `import email` works wherever some other
module has already loaded the submodule, and fails with an AttributeError where none has (it
did on Python 3.11 to 3.13 and not on 3.14). Two checks here:

* a static one that does not depend on the interpreter running the tests: every `pkg.sub`
  reference to a standard-library submodule must have `import pkg.sub` in the same file;
* a run of each script, started as a fresh isolated process, under every other Python
  interpreter found on this machine (set ORINYX_EXTRA_PYTHONS to a path list to add more).
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


def other_pythons():
    found = {}
    candidates = [f"python3.{minor}" for minor in range(11, 15)]
    paths = [shutil.which(c) for c in candidates]
    paths += [p for p in os.environ.get("ORINYX_EXTRA_PYTHONS", "").split(os.pathsep) if p]
    for path in paths:
        if path and Path(path).exists():
            found[str(Path(path).resolve())] = path
    return sorted(found.values())


@pytest.mark.parametrize("python", other_pythons() or [pytest.param(None, marks=pytest.mark.skip)])
@pytest.mark.parametrize("name", SCRIPTS)
def test_each_script_starts_under_every_python_found(python, name, tmp_path):
    """The lint takes a file, not --help; an empty workflow makes it print FAIL lines and exit 1."""
    if name == "lint_release_workflow.py":
        empty = tmp_path / "empty.yml"
        empty.write_text("name: empty\n")
        args, expected = [str(empty)], 1
    else:
        args, expected = ["--help"], 0
    result = subprocess.run(
        [python, "-I", str(ROOT / "scripts" / name), *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT.parent,
    )
    assert result.returncode == expected, result.stderr
    assert "Traceback" not in result.stderr

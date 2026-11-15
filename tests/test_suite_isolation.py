"""The tests never open the OS keychain and never reach another machine.

A developer who has run `orinyx login` holds a saved sign-in in the OS keychain. A command run
without ORINYX_API_KEY looks for that sign-in. A test that runs such a command would otherwise
find the developer's own sign-in, refresh it and send the test's synthetic claims to the API as
that developer. tests/conftest.py prevents this, and these tests fail if it stops holding:

1. In the test process, every keyring module the package imports is blocked for the whole
   session. The list is read from the package's source, so a backend added there is caught.
2. A child process cannot import keyring: each helper that builds a child's environment, and
   the environment a child inherits, puts tests/no_keychain first on the import path.
3. A name lookup or a connection that is not loopback is refused, and fails the test.

Nothing here opens a keychain or leaves this machine, whether a check passes or fails. Each
test first reads source text, sys.modules or an environment variable, and stops there unless
the protection it is about to exercise is already in place.
"""

import ast
import importlib
import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests import test_stdio_entry, test_stdio_entry_guards, test_usage_errors

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "orinyx_mcp"
NO_KEYCHAIN = Path(__file__).resolve().parent / "no_keychain"
# What a child is asked: where would keyring be loaded from? It finds the file and stops.
PROBE = "import importlib.util as u; s = u.find_spec('keyring'); print(s.origin if s else '')"


def keyring_modules_the_package_imports() -> set[str]:
    names: set[str] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module)
    return {name for name in names if name.split(".")[0] == "keyring"}


def test_no_keychain_backend_can_be_imported_in_the_test_session():
    backends = keyring_modules_the_package_imports()
    assert backends, "the package no longer imports keyring, so this test checks nothing"
    importable = sorted(name for name in backends if sys.modules.get(name, "absent") is not None)
    # Checked before anything is imported: without it the lines below would load a real backend.
    assert importable == [], f"the tests can load a keychain backend: {importable}"
    for name in sorted(backends):
        with pytest.raises(ImportError):
            importlib.import_module(name)


def _from_run_module(tmp_path: Path) -> dict[str, str]:
    """The environment `_run_module` gives a child, read without starting that child."""
    seen: dict[str, str] = {}

    def record(command, **kwargs):
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, b"", b"")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(subprocess, "run", record)
        test_usage_errors._run_module("unused", [], {})
    return seen


CHILD_ENVIRONMENTS = {
    "tests/test_usage_errors.py::_run_module": _from_run_module,
    "tests/test_stdio_entry.py::_clean_env": lambda tmp_path: test_stdio_entry._clean_env({}),
    "tests/test_stdio_entry_guards.py::_env": lambda tmp_path: test_stdio_entry_guards._env(
        {}, tmp_path / "report.txt"
    ),
    "the environment a child inherits": lambda tmp_path: dict(os.environ),
}


@pytest.mark.parametrize("source", list(CHILD_ENVIRONMENTS))
def test_a_child_process_cannot_import_keyring(source, tmp_path):
    env = CHILD_ENVIRONMENTS[source](tmp_path)
    first = env.get("PYTHONPATH", "").split(os.pathsep)[0]
    # Checked before any child starts: without it a child could import the real keyring.
    assert first == str(NO_KEYCHAIN), f"{source}: tests/no_keychain is not first on PYTHONPATH"
    with pytest.raises(ImportError, match="never opens the OS keychain"):
        runpy.run_path(str(NO_KEYCHAIN / "keyring.py"))
    done = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert (done.returncode, done.stdout.strip()) == (0, str(NO_KEYCHAIN / "keyring.py")), (
        done.stderr
    )


def test_a_test_cannot_reach_another_machine(request):
    # Checked first: without the guard the lines below would send a real name lookup.
    guard = Path(socket.getaddrinfo.__code__.co_filename).name
    assert guard == "conftest.py", "name lookups are not guarded"
    refused = request.getfixturevalue("_loopback_only")
    with socket.create_server(("127.0.0.1", 0)) as listener:
        socket.create_connection(listener.getsockname(), timeout=5).close()  # loopback is open
    assert refused == []
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("another-machine.invalid", 443)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        with pytest.raises(ConnectionRefusedError):
            sock.connect(("192.0.2.1", 9))  # a documentation address: no machine has it
        with pytest.raises(ConnectionRefusedError):
            sock.connect(("another-machine.invalid", 443))  # a name here is looked up too
    assert refused == [
        "lookup of another-machine.invalid",
        "connection to 192.0.2.1",
        "connection to another-machine.invalid",
    ]
    refused.clear()  # asked for here; in any other test a refusal fails that test

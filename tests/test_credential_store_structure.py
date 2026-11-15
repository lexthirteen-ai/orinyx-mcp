"""What `orinyx_mcp/credentials.py` may import, and which files it may touch.

The package-wide guard in `test_config_safety.py` (no config-file reader, no home directory)
leaves this one module out, because it has to reach the OS keychain and keep a lock file under
the home directory. Left out entirely, the module could grow a plaintext credentials reader and
that guard would still pass. This file is the guard for the module the other one skips. It pins
three things, read from the source without running it:

1. every module it imports;
2. its one use of the home directory, which is the lock folder;
3. its file calls and what it asks of `os`: one lock file is opened, and nothing is read.

A change to any of them fails here and is then a decision, not an accident. The last test
shows the pins are not hollow: each kind of plaintext reader trips at least one.
"""

import ast
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parent.parent / "orinyx_mcp" / "credentials.py").read_text(
    encoding="utf-8"
)

# The keychain is reached through the two native backends only, never through `import keyring`,
# whose loader reads a configuration file and can select a plaintext backend.
IMPORTS = {
    "contextlib",
    "fcntl",
    "hashlib",
    "httpx",
    "keyring.backends.SecretService",
    "keyring.backends.macOS",
    "mcp.shared.auth",
    "orinyx_mcp.login",
    "os",
    "pathlib",
    "pydantic",
    "stat",
    "sys",
    "time",
    "urllib.parse",
}
HOME_USES = ["Path.home() / '.cache' / 'orinyx'"]
# One lock file is opened and wrapped. No call reads a file, writes one or opens another.
FILE_CALLS = ["os.fdopen", "os.open"]
OS_USES = {"O_CREAT", "O_NOFOLLOW", "O_RDWR", "chmod", "fdopen", "fstat", "getuid", "open"}

_HOME = {"home", "expanduser", "expandvars"}
_FILE = {"open", "fdopen", "popen", "read", "read_bytes", "read_text", "write_bytes", "write_text"}
_CODE = {"__import__", "compile", "eval", "exec", "import_module"}


def facts(source: str) -> dict:
    """The imports, home-directory expressions, file calls and `os` uses of a module."""
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    imports, home_uses, file_calls, os_uses = set(), [], [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imports.add("." * node.level + (node.module or ""))
        elif isinstance(node, ast.Attribute):
            if node.attr in _HOME:
                whole = node
                while isinstance(parents.get(whole), ast.expr):
                    whole = parents[whole]
                home_uses.append(ast.unparse(whole))
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                os_uses.add(node.attr)
        elif isinstance(node, ast.Call):
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name in _FILE | _CODE:
                file_calls.append(ast.unparse(called))
    return {
        "imports": imports,
        "home_uses": sorted(home_uses),
        "file_calls": sorted(file_calls),
        "os_uses": os_uses,
    }


def test_the_credential_store_imports_exactly_these_modules():
    assert facts(SOURCE)["imports"] == IMPORTS


def test_its_one_use_of_the_home_directory_is_the_lock_folder():
    assert facts(SOURCE)["home_uses"] == HOME_USES


def test_it_opens_one_lock_file_and_reads_none():
    found = facts(SOURCE)
    assert found["file_calls"] == FILE_CALLS
    assert found["os_uses"] == OS_USES


PLAINTEXT_READERS = {
    "a credentials file read with new imports": (
        "import netrc\n"
        "import tomllib\n\n\n"
        "def _fallback():\n"
        "    with open(Path.home() / '.config' / 'orinyx' / 'credentials') as handle:\n"
        "        return tomllib.loads(handle.read()).get('refresh_token') or netrc.netrc()\n",
        {"imports", "home_uses", "file_calls"},
    ),
    "a token file read with no new import": (
        "def _fallback():\n    return (Path.home() / '.orinyx-token').read_text()\n",
        {"home_uses", "file_calls"},
    ),
    "a dotenv file": (
        "from dotenv import load_dotenv\n\n\n"
        "def _fallback():\n"
        "    load_dotenv()\n"
        "    return os.environ.get('ORINYX_REFRESH_TOKEN')\n",
        {"imports", "os_uses"},
    ),
    "the keyring loader, which can select a plaintext backend": (
        "import keyring\n\n\ndef _fallback():\n    return keyring.get_keyring()\n",
        {"imports"},
    ),
    "a file named by the environment": (
        "def _fallback():\n"
        "    fd = os.open(os.environ['ORINYX_TOKEN_FILE'], os.O_RDONLY)\n"
        "    return os.read(fd, 65536)\n",
        {"file_calls", "os_uses"},
    ),
    "a module loaded by name": (
        "def _fallback():\n    return __import__('netrc').netrc()\n",
        {"file_calls"},
    ),
}


@pytest.mark.parametrize("case", list(PLAINTEXT_READERS))
def test_the_pins_catch_a_plaintext_reader_added_to_the_module(case):
    addition, tripped = PLAINTEXT_READERS[case]
    expected = facts(SOURCE)
    found = facts(SOURCE + "\n\n" + addition)
    assert {name for name in expected if found[name] != expected[name]} == tripped

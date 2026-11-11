"""Guards for `orinyx-mcp`'s three argument lists with every setting present.

`tests/test_stdio_entry.py` never gives the network server the settings it could start
with, so a refused argument list that slipped through to the network server would print the
network server's refusal there, not reach a listening socket. These tests give it every
setting, and run the installed console script's shape under a guard that stops the process
at the first socket bind, connect or name lookup and records which one it was:

1. No argument list other than exactly `[]`, `["stdio"]` or
   `["--version"]` starts a server, with the network and stdio settings both present.
2. The positive control: `orinyx-mcp` with no argument, and `python -m orinyx_mcp serve`,
   do reach the listen with those settings, with the same output before it.
3. `orinyx-mcp --version` binds nothing, connects nothing, looks nothing up and never
   imports uvicorn.
4. `orinyx-mcp stdio` with the network settings present starts the stdio server, not the
   network one.
5. `orinyx-mcp` with no argument refuses unusable settings with the lines 0.1.2 printed
   (each one was read from a run of the code before this change), and serves the 0.1.2 route table.
6. Two launch shapes outside the supported launch channels, pinned as they behave today
   (documented behaviour), so a change to either is seen.

Every child process is given PYTHONPATH=<this checkout>, and every guarded child records the
package file it imported; each test asserts that file is inside this checkout, so a child
that picked up an installed copy of another branch fails rather than testing the wrong code.
All keys and URLs are synthetic. No socket is ever bound: the guard exits first.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from orinyx_mcp import __version__

from tests.test_clean_errors import SENTINEL_KEY, assert_no_traceback
from tests.test_usage_errors import COLOUR_SWITCHES, PLAIN_TERMINAL

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.orinyx.example"
PASSWORD = "PWqaGuardSECRET7"
USAGE = b"usage: orinyx-mcp | orinyx-mcp stdio | orinyx-mcp --version\n"
NETWORK_MISSING = "Set MCP_PUBLIC_URL and ORINYX_API_URL\n"
BOUND = 97  # the exit code the guard uses when the process tried to bind a socket
HOP_SECRET = "synthetic-hop-" * 4

# Stops the process at the first bind, connect or name lookup, after writing which one to
# the report file. At exit it records whether uvicorn (the network server) was imported.
GUARD = """\
import atexit
import os
import socket
import sys

_REPORT = os.environ["QA_GUARD_REPORT"]


def _note(word):
    with open(_REPORT, "a", encoding="utf-8") as report:
        report.write(word + "\\n")


def _stop(word, code):
    def stop(*args, **kwargs):
        _note(word)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)

    return stop


socket.socket.bind = _stop("bind", 97)
socket.socket.connect = _stop("connect", 98)
socket.socket.connect_ex = _stop("connect", 98)
socket.getaddrinfo = _stop("lookup", 99)
socket.create_connection = _stop("connect", 98)
atexit.register(lambda: _note("uvicorn=" + str("uvicorn" in sys.modules)))
"""

# The installed `orinyx-mcp`, as pip and uv write it, after the guard.
GUARDED_SCRIPT = (
    GUARD
    + """
import re
import orinyx_mcp
from orinyx_mcp.http import serve

_note("package=" + orinyx_mcp.__file__)
if __name__ == "__main__":
    sys.argv[0] = re.sub(r"(-script\\.pyw|\\.exe)?$", "", sys.argv[0])
    sys.exit(serve())
"""
)

# `python -m orinyx_mcp serve`, after the guard.
GUARDED_MODULE = (
    GUARD
    + """
import runpy
import orinyx_mcp

_note("package=" + orinyx_mcp.__file__)
sys.argv = ["orinyx_mcp", *sys.argv[1:]]
runpy.run_module("orinyx_mcp", run_name="__main__", alter_sys=True)
"""
)

# Every setting either server needs to start: a slip-through would reach the guard.
EVERY_SETTING = {
    "ORINYX_HOP_SECRET": HOP_SECRET,
    "MCP_PUBLIC_URL": "https://mcp.example",
    "ORINYX_API_URL": API_URL,
    "ORINYX_API_KEY": SENTINEL_KEY,
    "PORT": "18765",
}

REFUSED = {
    "-h": ["-h"],
    "--help": ["--help"],
    "serve": ["serve"],
    "STDIO": ["STDIO"],
    "stdoi": ["stdoi"],
    "stdio extra": ["stdio", "extra"],
    "--version stdio": ["--version", "stdio"],
    "stdio --version": ["stdio", "--version"],
    "a key alone": [SENTINEL_KEY],
    "--api-key=key": ["--api-key=" + SENTINEL_KEY],
}


def _env(settings: dict[str, str], report: Path) -> dict[str, str]:
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_", "PYTHON"))
        and name not in COLOUR_SWITCHES
    }
    clean["PYTHONPATH"] = str(ROOT)  # this checkout's package, not an installed copy
    clean["QA_GUARD_REPORT"] = str(report)
    clean.update(PLAIN_TERMINAL)
    return {**clean, **settings}


def _run(tmp_path: Path, source: str, args: list[str], settings: dict[str, str]):
    """Run `source` as a program under the guard. Returns the finished process and the lines
    the guard recorded, having checked the package came from this checkout."""
    script = tmp_path / "orinyx-mcp"
    script.write_text(source, encoding="utf-8")
    report = tmp_path / "guard.txt"
    report.write_text("", encoding="utf-8")
    done = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=tmp_path,
        env=_env(settings, report),
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    notes = report.read_text(encoding="utf-8").splitlines()
    packages = [note.removeprefix("package=") for note in notes if note.startswith("package=")]
    assert packages == [str(ROOT / "orinyx_mcp" / "__init__.py")], (packages, done.stderr)
    return done, [note for note in notes if not note.startswith("package=")]


# --- 1. nothing but exactly [], stdio or --version starts a server -------------------------


@pytest.mark.parametrize("case", list(REFUSED))
def test_a_refused_argument_list_starts_no_server_with_every_setting_present(case, tmp_path):
    done, notes = _run(tmp_path, GUARDED_SCRIPT, REFUSED[case], EVERY_SETTING)
    assert (done.returncode, done.stdout, done.stderr) == (1, b"", USAGE), (case, notes)
    assert notes == ["uvicorn=False"], case  # no bind, connect or lookup; uvicorn never loaded


# --- 2. the positive control: no argument still reaches the listen --------------------------


def test_the_command_with_no_argument_reaches_the_listen_as_python_m_orinyx_mcp_serve_does(
    tmp_path,
):
    command, command_notes = _run(tmp_path, GUARDED_SCRIPT, [], EVERY_SETTING)
    module, module_notes = _run(tmp_path, GUARDED_MODULE, ["serve"], EVERY_SETTING)
    assert command_notes == module_notes == ["bind"]
    assert command.returncode == module.returncode == BOUND
    assert (command.stdout, command.stderr) == (module.stdout, module.stderr) == (b"", b"")


# --- 3. --version: no environment, no network, no server ------------------------------------


def test_the_version_command_makes_no_network_call_and_loads_no_server(tmp_path):
    done, notes = _run(tmp_path, GUARDED_SCRIPT, ["--version"], {})
    assert (done.returncode, done.stdout, done.stderr) == (0, f"{__version__}\n".encode(), b"")
    assert notes == ["uvicorn=False"]


def test_the_version_command_ignores_every_setting(tmp_path):
    done, notes = _run(tmp_path, GUARDED_SCRIPT, ["--version"], EVERY_SETTING)
    assert (done.returncode, done.stdout, done.stderr) == (0, f"{__version__}\n".encode(), b"")
    assert notes == ["uvicorn=False"]


# --- 4. stdio with the network settings present is still the stdio server -------------------


def test_the_stdio_command_never_starts_the_network_server(tmp_path):
    """stdin is empty, so the stdio server meets end of input and stops (exit 0). The network
    server, with these settings, would bind (exit 97). The stdio server may import uvicorn
    (the MCP library does, in 0.1.2 too), so only the socket calls are checked. Its stdout,
    the protocol stream, carries nothing it was not asked for."""
    pytest.importorskip("mcp")
    done, notes = _run(tmp_path, GUARDED_SCRIPT, ["stdio"], EVERY_SETTING)
    assert not {"bind", "connect", "lookup"} & set(notes), (notes, done.stderr)
    assert done.stdout == b""
    assert done.returncode == 0, done.stderr


# --- 5. no argument: the 0.1.2 refusals and routes ------------------------------------------

# Each line below is what the code before this change printed for these settings through the
# installed `orinyx-mcp` script, read from a run of that tree; written out, so a change fails.
NOT_STARTED_VALIDATION = (
    "The server could not start (ValidationError). No setting's value is shown; a malformed "
    "URL is the usual cause: check MCP_PUBLIC_URL, ORINYX_API_URL, ORINYX_ISSUER_URL, "
    "DOWNSTREAM_MCP_URL and ORINYX_ARENA_URL.\n"
)
PUBLIC = {
    "MCP_PUBLIC_URL": "https://mcp.example",
    "ORINYX_HOP_SECRET": HOP_SECRET,
}
UNUSABLE_0_1_2 = {
    "no settings": ({}, NETWORK_MISSING),
    "the api url and key only": (
        {"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": SENTINEL_KEY},
        NETWORK_MISSING,
    ),
    "a plain-http public url": (
        {"MCP_PUBLIC_URL": "http://mcp.example", "ORINYX_API_URL": API_URL},
        "MCP_PUBLIC_URL must be an https URL (plain http only for localhost)\n",
    ),
    "a port that is not a number": (
        {**PUBLIC, "ORINYX_API_URL": API_URL, "PORT": "eighty"},
        "PORT must be a number\n",
    ),
    "a password in the api url": (
        {**PUBLIC, "ORINYX_API_URL": f"https://u:{PASSWORD}@api.orinyx.example"},
        "ORINYX_API_URL must not contain a username or password\n",
    ),
    "an out-of-range port in the api url": (
        {**PUBLIC, "ORINYX_API_URL": "https://api.orinyx.example:99999"},
        NOT_STARTED_VALIDATION,
    ),
    "the arena on with a plain-http arena url": (
        {
            **PUBLIC,
            "ORINYX_API_URL": API_URL,
            "ORINYX_ARENA_ENABLED": "true",
            "ORINYX_ARENA_URL": "http://arena.example",
        },
        "ORINYX_ARENA_URL must be an https origin (http only for localhost)\n",
    ),
    "a short hop secret": (
        {**PUBLIC, "ORINYX_API_URL": API_URL, "ORINYX_HOP_SECRET": "short"},
        "ORINYX_HOP_SECRET must be at least 32 characters\n",
    ),
}


@pytest.mark.parametrize("case", list(UNUSABLE_0_1_2))
def test_the_command_with_no_argument_refuses_settings_as_0_1_2_did(case, tmp_path):
    settings, line = UNUSABLE_0_1_2[case]
    done, notes = _run(tmp_path, GUARDED_SCRIPT, [], settings)
    assert (done.returncode, done.stdout, done.stderr.decode()) == (1, b"", line), notes
    assert "bind" not in notes
    assert PASSWORD not in done.stderr.decode()
    assert_no_traceback(done.stderr.decode())


def test_the_network_server_serves_the_0_1_2_routes(monkeypatch):
    """The route table the code before this change built from these settings."""
    from orinyx_mcp.config import Config
    from orinyx_mcp.http import build_app

    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example")
    monkeypatch.setenv("ORINYX_HOP_SECRET", HOP_SECRET)
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    _, app = build_app(Config.from_env())
    routes = [
        (type(route).__name__, route.path, sorted(getattr(route, "methods", None) or []))
        for route in app.routes
    ]
    assert routes == [
        ("Route", "/health", ["GET", "HEAD"]),
        ("Route", "/mcp", []),
        ("Mount", "/mcp", []),
        ("Route", "/.well-known/oauth-protected-resource/mcp", ["GET", "HEAD", "OPTIONS"]),
    ]


# --- 6. launch shapes outside the supported channels, pinned as they are -------------------

# A launcher that does not bind `serve` into `__main__` (a zipapp bootstrap, a
# `load_entry_point`-style wrapper, an embedder): the arguments are ignored, as in 0.1.2, so
# a refused list reaches the network server (here refused for want of settings). This pins
# the documented behaviour; a change to how the script finds `serve` would change it.
OTHER_LAUNCHERS = {
    "import_module": (
        "import importlib\nsys.exit(importlib.import_module('orinyx_mcp.http').serve())\n"
    ),
    "module attribute": "import orinyx_mcp.http as h\nsys.exit(h.serve())\n",
}


@pytest.mark.parametrize("shape", list(OTHER_LAUNCHERS))
def test_a_launcher_without_serve_in_main_ignores_its_arguments(shape, tmp_path):
    source = (
        GUARD
        + "import orinyx_mcp\n_note('package=' + orinyx_mcp.__file__)\n"
        + OTHER_LAUNCHERS[shape]
    )
    done, notes = _run(tmp_path, source, ["stdoi"], {})
    assert (done.returncode, done.stdout, done.stderr.decode()) == (1, b"", NETWORK_MISSING)
    assert "bind" not in notes


def test_an_embedder_with_serve_in_main_has_its_arguments_read(tmp_path):
    """A user's own program that imports `serve` into `__main__` and calls it looks like the
    console script, so its own command line is read as `orinyx-mcp`'s: here its `--verbose`
    flag is refused. It fails closed, starting nothing (documented behaviour). Pinned as it
    is today."""
    source = (
        GUARD
        + "import orinyx_mcp\n_note('package=' + orinyx_mcp.__file__)\n"
        + "from orinyx_mcp.http import serve\n"
        + "verbose = '--verbose' in sys.argv\n"
        + "sys.exit(serve())\n"
    )
    done, notes = _run(tmp_path, source, ["--verbose"], EVERY_SETTING)
    assert (done.returncode, done.stdout, done.stderr) == (1, b"", USAGE)
    assert notes == ["uvicorn=False"]

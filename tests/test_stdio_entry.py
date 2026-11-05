"""`orinyx-mcp` takes exactly three argument lists, and refuses every other one.

1. `orinyx-mcp` with no argument is the network server, unchanged: the same settings needed,
   the same output and the same exit codes as `python -m orinyx_mcp serve`.
2. `orinyx-mcp stdio` is the stdio server, the same code as `python -m orinyx_mcp`: the same
   missing-setting message and exit code, and over MCP the same server name, instructions,
   tools, schemas, descriptions and prompt. Its stdout carries MCP protocol messages only.
3. `orinyx-mcp --version` prints `__version__` and a newline on stdout and exits 0. It needs
   no setting and starts no server.
4. Any other argument list exits 1, prints one usage line on stderr, prints nothing on stdout
   and starts nothing. The line names no argument it was given and no setting's value.

The real-process tests run a script written the way pip, uv and pipx write the installed
`orinyx-mcp` (it imports `serve` into `__main__` and calls it with no argument). None of them
gives the network server settings it could start with, so nothing here listens on a port.
All keys are synthetic.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest
from orinyx_mcp import __main__ as stdio
from orinyx_mcp import __version__, http
from orinyx_mcp.config import ConfigError

from tests.test_clean_errors import SENTINEL_BODY, SENTINEL_KEY, assert_no_traceback
from tests.test_usage_errors import (
    COLOUR_SWITCHES,
    HOSTILE,
    HOSTILE_BODY,
    PLAIN_HTTP_LINE,
    PLAIN_TERMINAL,
    _run_module,
)

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://api.orinyx.example"
# Written out rather than imported, so a change to the wording fails here.
USAGE = "usage: orinyx-mcp | orinyx-mcp stdio | orinyx-mcp --version\n"
NETWORK_MISSING = "Set MCP_PUBLIC_URL and ORINYX_API_URL\n"
STDIO_MISSING = "Set ORINYX_API_URL and ORINYX_API_KEY in the environment.\n"

# The installed console script, as pip writes it (uv's differs only in how it strips argv[0]).
CONSOLE_SCRIPT = """\
import re
import sys
from orinyx_mcp.http import serve
if __name__ == "__main__":
    sys.argv[0] = re.sub(r"(-script\\.pyw|\\.exe)?$", "", sys.argv[0])
    sys.exit(serve())
"""

# Every argument list that is not exactly [], ["stdio"] or ["--version"]: help flags and other
# command words, near misses, a bare separator, and a key passed by mistake.
REFUSED = {
    "-h": ["-h"],
    "--help": ["--help"],
    "serve": ["serve"],
    "STDIO": ["STDIO"],
    "stdoi": ["stdoi"],
    "stdio extra": ["stdio", "extra"],
    "--version stdio": ["--version", "stdio"],
    "stdio --version": ["stdio", "--version"],
    "stdio stdio": ["stdio", "stdio"],
    "--version --version": ["--version", "--version"],
    "--version=1": ["--version=1"],
    "-V": ["-V"],
    "version": ["version"],
    "--stdio": ["--stdio"],
    "stdio with a space": ["stdio "],
    "an empty word": [""],
    "--": ["--"],
    "-- stdio": ["--", "stdio"],
    "--api-key key": ["--api-key", SENTINEL_KEY],
    "--api-key=key": ["--api-key=" + SENTINEL_KEY],
    "stdio key": ["stdio", SENTINEL_KEY],
    "a key alone": [SENTINEL_KEY],
    "a hostile value": [HOSTILE],
}


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch):
    for name in COLOUR_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    for name, value in PLAIN_TERMINAL.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def no_settings(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)


@pytest.fixture
def started(monkeypatch):
    """Which server `serve` went on to start: the stdio entry, or the network settings read
    (refused here, so nothing listens). Each records the call and returns 1."""
    calls: list[tuple] = []

    def stdio_main(argv=None):
        calls.append(("stdio", argv))
        return 1

    class NetworkConfig:
        @classmethod
        def from_env(cls, env=None):
            calls.append(("network",))
            raise ConfigError("the network server was reached")

    monkeypatch.setattr(stdio, "main", stdio_main)
    monkeypatch.setattr(http, "Config", NetworkConfig)
    return calls


# --- in process ------------------------------------------------------------------------------


def test_no_argument_is_the_network_server(no_settings, capsys):
    assert http.serve([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", NETWORK_MISSING)


def test_stdio_is_the_python_m_orinyx_mcp_entry(started, capsys):
    assert http.serve(["stdio"]) == 1
    assert started == [("stdio", [])]
    assert capsys.readouterr().out == ""


def test_version_prints_the_version_and_starts_nothing(no_settings, started, capsys):
    assert http.serve(["--version"]) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (__version__ + "\n", "")
    assert started == []


@pytest.mark.parametrize("case", list(REFUSED))
def test_any_other_argument_list_is_refused_in_one_line(case, monkeypatch, started, capsys):
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)
    assert http.serve(REFUSED[case]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", USAGE), case
    assert started == [], case
    for hidden in (SENTINEL_BODY, HOSTILE_BODY, API_URL):
        assert hidden not in captured.err
    assert_no_traceback(captured.err)


def test_an_in_process_caller_never_hands_its_command_line_to_the_server(
    no_settings, monkeypatch, capsys
):
    """A test runner (or `python -m orinyx_mcp serve`) calls `serve()` with its own argv in
    sys.argv. Unless the running program is the `orinyx-mcp` script, that argv is not read."""
    monkeypatch.setattr(sys, "argv", ["pytest", "stdoi", "--version"])
    assert http.serve() == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", NETWORK_MISSING)


@pytest.mark.parametrize(
    ("argv", "out", "err", "code"),
    [
        ([], "", NETWORK_MISSING, 1),
        (["--version"], __version__ + "\n", "", 0),
        (["stdoi"], "", USAGE, 1),
    ],
)
def test_the_console_script_reads_its_own_command_line(
    argv, out, err, code, no_settings, monkeypatch, capsys
):
    monkeypatch.setitem(sys.modules, "__main__", types.SimpleNamespace(serve=http.serve))
    monkeypatch.setattr(sys, "argv", ["orinyx-mcp", *argv])
    assert http.serve() == code
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == (out, err)


# --- as real processes -----------------------------------------------------------------------


def _clean_env(settings: dict[str, str]) -> dict[str, str]:
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_", "PYTHON"))
        and name not in COLOUR_SWITCHES
    }
    clean["PYTHONPATH"] = str(ROOT)  # this checkout's package, not an installed copy
    clean.update(PLAIN_TERMINAL)
    return {**clean, **settings}


@pytest.fixture
def console_script(tmp_path) -> Path:
    script = tmp_path / "orinyx-mcp"
    script.write_text(CONSOLE_SCRIPT, encoding="utf-8")
    return script


def _run_command(script: Path, args: list[str], settings: dict[str, str]):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=_clean_env(settings),
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )


# Settings the network server refuses before it listens, and the stdio server's own refusals.
NETWORK_REFUSALS = {
    "no settings": {},
    "no public url": {"ORINYX_API_URL": API_URL},
    "a plain-http public url": {"MCP_PUBLIC_URL": "http://mcp.example", "ORINYX_API_URL": API_URL},
    "a port that is not a number": {
        "MCP_PUBLIC_URL": "https://mcp.example",
        "ORINYX_API_URL": API_URL,
        "PORT": "eighty",
    },
}
STDIO_REFUSALS = {
    "no settings": {},
    "no key": {"ORINYX_API_URL": API_URL},
    "a plain-http api url": {"ORINYX_API_URL": "http://api.orinyx.example"},
}


@pytest.mark.parametrize("case", list(NETWORK_REFUSALS))
def test_the_command_with_no_argument_matches_python_m_orinyx_mcp_serve(case, console_script):
    settings = {"ORINYX_API_KEY": SENTINEL_KEY, **NETWORK_REFUSALS[case]}
    command = _run_command(console_script, [], settings)
    module = _run_module("orinyx_mcp", ["serve"], settings)
    assert command.returncode == module.returncode == 1
    assert command.stdout == module.stdout == b""
    assert command.stderr == module.stderr
    if case in ("no settings", "no public url"):
        assert command.stderr.decode() == NETWORK_MISSING
    assert_no_traceback(command.stderr.decode())


@pytest.mark.parametrize("case", list(STDIO_REFUSALS))
def test_the_stdio_command_refuses_settings_as_python_m_orinyx_mcp_does(case, console_script):
    settings = {"ORINYX_API_KEY": SENTINEL_KEY, **STDIO_REFUSALS[case]}
    if case == "no key":
        del settings["ORINYX_API_KEY"]
    command = _run_command(console_script, ["stdio"], settings)
    module = _run_module("orinyx_mcp", [], settings)
    assert command.returncode == module.returncode == 1
    assert command.stdout == module.stdout == b""  # the protocol stream
    assert command.stderr == module.stderr
    expected = PLAIN_HTTP_LINE + "\n" if case == "a plain-http api url" else STDIO_MISSING
    assert command.stderr.decode() == expected


def test_the_version_command_needs_no_setting(console_script):
    done = _run_command(console_script, ["--version"], {})
    assert (done.returncode, done.stdout, done.stderr) == (0, f"{__version__}\n".encode(), b"")


@pytest.mark.parametrize(
    "case", ["-h", "--help", "serve", "STDIO", "stdoi", "stdio extra", "--version stdio"]
)
def test_the_command_refuses_any_other_argument_list(case, console_script):
    """With the stdio settings present and the network server's missing: a refusal that
    slipped through would start the stdio server or print the network server's refusal."""
    done = _run_command(
        console_script, REFUSED[case], {"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": SENTINEL_KEY}
    )
    assert (done.returncode, done.stdout, done.stderr.decode()) == (1, b"", USAGE), case


# --- the MCP interface over both stdio entries ---------------------------------------------


def _speak_mcp(command: list[str]) -> tuple[list[bytes], dict[int, dict]]:
    """Drive a stdio server through the handshake, tools/list, prompts/list and prompts/get.
    Returns every line it wrote on stdout, and each answer by request id."""
    from mcp.types import LATEST_PROTOCOL_VERSION

    env = _clean_env({"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": SENTINEL_KEY})
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    lines: queue.Queue[bytes | None] = queue.Queue()

    def read() -> None:
        for line in iter(process.stdout.readline, b""):
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    written: list[bytes] = []
    answers: dict[int, dict] = {}

    def send(message: dict) -> None:
        process.stdin.write(json.dumps(message).encode() + b"\n")
        process.stdin.flush()

    def wait_for(request_id: int) -> None:
        while request_id not in answers:
            line = lines.get(timeout=60)
            assert line is not None, f"the server closed stdout before answering {request_id}"
            written.append(line)
            message = json.loads(line)
            if "id" in message:
                answers[message["id"]] = message

    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-entry-test", "version": "0"},
                },
            }
        )
        wait_for(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        requests = [
            ("tools/list", {}),
            ("prompts/list", {}),
            ("prompts/get", {"name": "choose_a_test"}),
        ]
        for request_id, (method, params) in enumerate(requests, start=2):
            send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            wait_for(request_id)
        process.stdin.close()
        process.wait(timeout=60)
        while (line := lines.get(timeout=60)) is not None:
            written.append(line)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return written, answers


def test_the_stdio_command_serves_the_same_mcp_interface_as_python_m_orinyx_mcp(console_script):
    pytest.importorskip("mcp")
    module_lines, module = _speak_mcp([sys.executable, "-m", "orinyx_mcp"])
    command_lines, command = _speak_mcp([sys.executable, str(console_script), "stdio"])

    # stdout is the protocol stream: every line either entry wrote is a JSON-RPC message
    for line in (*module_lines, *command_lines):
        assert json.loads(line).get("jsonrpc") == "2.0", line
    for answers in (module, command):
        assert all("result" in answer for answer in answers.values()), answers
        assert answers[1]["result"]["serverInfo"]["name"] == "orinyx"
        assert "nextCursor" not in answers[2]["result"]

    assert command[1] == module[1]  # server name, version, instructions, capabilities
    assert command[2] == module[2]  # tool names, input schemas and descriptions
    assert command[3] == module[3]  # the prompt set
    assert command[4] == module[4]  # the prompt's text
    assert command_lines == module_lines  # byte for byte
    assert [tool["name"] for tool in command[2]["result"]["tools"]]
    assert [prompt["name"] for prompt in command[3]["result"]["prompts"]] == ["choose_a_test"]

"""No error path repeats a value that could hold a credential. It names the field instead.

1. `orinyx get <key>` (and accuracy, export, and the MCP tools that take a run id): a value
   that is not a UUID is refused as "run_id must be a UUID", with no part of the value.
2. `orinyx observe <key>`: a path that is not a file it reads is named by its position
   ("path 1"), never by the path itself.
3. A key holding a line break (LF, CR or both) is refused by the HTTP stack when the request
   is written. That refusal quotes the Authorization header, so it is replaced by a fixed
   sentence, and the original is not chained on.
4. `orinyx-mcp` / `python -m orinyx_mcp serve` with a URL setting it cannot use prints one
   line and exits 1. Before, it was a traceback whose last line quoted the URL, password
   included. The settings this package refuses itself, ORINYX_ARENA_URL among them, still
   print their own message.
5. `python -m orinyx_mcp` (stdio) with a DOWNSTREAM_MCP_URL that urllib cannot split prints a
   fixed line: urllib's own message quotes the URL.

Every exit code is the one these inputs gave before: 1. Each test reads stdout and stderr
whole. A leak is looked for as any run of six characters of the secret, not only the whole
value: the run-id message once printed the first 40 characters of whatever it was given.
All keys and passwords here are synthetic.
"""

import os
import socket
import threading
from pathlib import Path

import httpx
import pytest
from orinyx_mcp import __main__ as stdio
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxApiError, OrinyxClient

from tests.test_clean_errors import RUN_ID, assert_no_traceback
from tests.test_usage_errors import _run_module

# A synthetic key of 43 characters, the length of an issued one. Built in pieces that read as
# synthetic, so no source line holds a key-shaped or high-entropy literal.
KEY_BODY = "SYNTHETIC" + "k3yB0dy" * 3 + "fake"
KEY = "oxk_test_" + KEY_BODY
# A synthetic URL password.
PASSWORD = "p4ss-SYNTHETIC-" + "pa55w0rd" * 2
API_URL = "https://api.orinyx.example"
PUBLIC_URL = "https://mcp.orinyx.example"
SLICE = 6
HOP_SECRET = "synthetic-hop-" * 4

# The new messages, written out rather than imported, so a change to the wording fails here.
RUN_ID_REFUSED = "orinyx: run_id must be a UUID\n"
NOT_A_FILE = "orinyx: path {}: expected a .txt, .jsonl or .json file, or a directory\n"
NOT_SENT = (
    "the request was not sent: it broke an HTTP rule on this side, most often a header value "
    "(the API key, for example) that holds a line break. No header value is shown."
)
NOT_STARTED = (
    "The server could not start ({}). No setting's value is shown; a malformed URL is the "
    "usual cause: check MCP_PUBLIC_URL, ORINYX_API_URL, ORINYX_ISSUER_URL, DOWNSTREAM_MCP_URL "
    "and ORINYX_ARENA_URL."
)
DOWNSTREAM_MALFORMED = "DOWNSTREAM_MCP_URL is malformed (its value is not shown).\n"


def assert_no_slice(secret: str, *outputs: str) -> None:
    """No run of SLICE characters of the secret is in any output."""
    for text in outputs:
        for start in range(len(secret) - SLICE + 1):
            piece = secret[start : start + SLICE]
            assert piece not in text, f"{piece!r}, a slice of the secret, is in the output"


def test_the_slice_check_catches_a_partial_leak():
    """The check is not hollow: the old run-id message's 31-character slice, and pydantic's
    truncated `p4ss-SYNTHE...`, both fail it."""
    old_message = f"orinyx: run_id must be a UUID, got {KEY[:40]!r}\n"
    with pytest.raises(AssertionError):
        assert_no_slice(KEY_BODY, old_message)
    with pytest.raises(AssertionError):
        assert_no_slice(PASSWORD, "input_value='https://api.orinyx.example:p4ss-SYNTHE...'")


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)


def _never_sent(request: httpx.Request) -> httpx.Response:
    raise AssertionError("nothing may be sent for this input")


def _factory(url: str, key: str) -> OrinyxClient:
    return OrinyxClient(url, key, transport=httpx.MockTransport(_never_sent))


# --- 1. a value given as the run id -----------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["get", KEY],
        ["get", KEY, "--json"],
        ["accuracy", KEY],
        ["export", KEY, "--out", "unused.csv"],
    ],
    ids=["get", "get --json", "accuracy", "export"],
)
def test_a_key_given_as_the_run_id_is_named_as_the_field_never_repeated(argv, api_env, capsys):
    assert cli.main(argv, client_factory=_factory) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == RUN_ID_REFUSED
    assert_no_slice(KEY_BODY, captured.out, captured.err)


def test_the_cli_process_refuses_a_key_given_as_the_run_id_without_repeating_it():
    done = _run_module(
        "orinyx_mcp.cli", ["get", KEY], {"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": KEY}
    )
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == RUN_ID_REFUSED
    assert_no_slice(KEY_BODY, done.stderr.decode())


async def test_an_mcp_tool_given_a_key_as_the_run_id_never_repeats_it():
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    client = _factory(API_URL, "oxk_test_operator")
    try:
        async with Client(build_server(shared(client)), mode="legacy") as mcp_client:
            for name in ("get_verification", "get_accuracy", "export_verification"):
                arguments = {"run_id": KEY, **({"fmt": "csv"} if name.startswith("export") else {})}
                result = await mcp_client.call_tool(name, arguments)
                text = "\n".join(getattr(part, "text", "") for part in result.content)
                assert result.is_error, name
                assert "run_id must be a UUID" in text, (name, text)
                assert_no_slice(KEY_BODY, text)
    finally:
        client.close()


# --- 2. a value given as an observe path ------------------------------------------------------


def test_a_key_given_as_an_observe_path_is_named_by_its_position(api_env, capsys):
    assert cli.main(["observe", KEY], client_factory=_factory) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == NOT_A_FILE.format(1)
    assert_no_slice(KEY_BODY, captured.out, captured.err)


def test_the_position_counts_the_path_arguments(api_env, tmp_path, capsys):
    orders = tmp_path / "orders.txt"
    orders.write_text("warfarin 5 mg by mouth daily\n")
    assert cli.main(["observe", str(orders), KEY], client_factory=_factory) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""  # refused before anything is sent: no run to show
    assert captured.err == NOT_A_FILE.format(2)
    assert_no_slice(KEY_BODY, captured.out, captured.err)


@pytest.mark.parametrize("suffix", [".txt", ".jsonl", ".json"])
def test_an_observe_path_that_cannot_be_read_is_named_by_its_position(
    suffix, api_env, tmp_path, capsys
):
    """A key with a suffix this command reads still never comes back: the OS's error quotes
    the path, so only its reason is kept."""
    missing = tmp_path / (KEY + suffix)
    assert cli.main(["observe", str(missing)], client_factory=_factory) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "orinyx: path 1: cannot be read (No such file or directory)\n"
    assert_no_slice(KEY_BODY, captured.out, captured.err)


def test_the_cli_process_refuses_a_key_given_as_an_observe_path_without_repeating_it():
    done = _run_module(
        "orinyx_mcp.cli", ["observe", KEY], {"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": KEY}
    )
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == NOT_A_FILE.format(1)
    assert_no_slice(KEY_BODY, done.stderr.decode())


# --- 3. a key holding a line break ------------------------------------------------------------

BREAKS = {"LF": "\n", "CR": "\r", "CRLF": "\r\n"}


@pytest.fixture
def loopback_api():
    """A listener on 127.0.0.1 that accepts and closes. The real HTTP stack connects, then
    checks each header as it writes the request: that check is the one that quoted the key.
    Nothing leaves the machine."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(0.1)
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            connection.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    stop.set()
    thread.join(timeout=5)
    listener.close()


def _broken_key(line_break: str) -> str:
    return "oxk_test_" + KEY_BODY[:17] + line_break + KEY_BODY[17:]


@pytest.mark.parametrize("line_break", sorted(BREAKS))
def test_a_key_holding_a_line_break_is_refused_without_being_repeated(
    line_break, loopback_api, monkeypatch, capsys
):
    monkeypatch.setenv("ORINYX_API_URL", loopback_api)
    monkeypatch.setenv("ORINYX_API_KEY", _broken_key(BREAKS[line_break]))
    assert cli.main(["get", RUN_ID]) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"orinyx: {NOT_SENT}\n"
    assert_no_slice(KEY_BODY, captured.out, captured.err)


def _chain(error: BaseException) -> list[BaseException]:
    """The error and every error reachable from it through __cause__ and __context__."""
    seen: list[BaseException] = []
    todo = [error]
    while todo:
        current = todo.pop()
        if current is None or any(current is known for known in seen):
            continue
        seen.append(current)
        todo += [current.__cause__, current.__context__]
    return seen


@pytest.mark.parametrize("line_break", sorted(BREAKS))
def test_the_refusal_carries_no_chained_error_that_quotes_the_key(line_break, loopback_api):
    """A logged traceback prints a chained error's message too, and an error reporter can walk
    a suppressed context: the refusal holds no reference to the error that quoted the key."""
    with OrinyxClient(loopback_api, _broken_key(BREAKS[line_break])) as client:
        with pytest.raises(OrinyxApiError) as caught:
            client.get_run(RUN_ID)
    error = caught.value
    assert (error.status, error.code, error.message) == (0, "transport_error", NOT_SENT)
    assert error.__cause__ is None and error.__context__ is None
    chain = _chain(error)
    assert chain == [error]
    assert_no_slice(KEY_BODY, *(repr(link) for link in chain), *(repr(link.args) for link in chain))


@pytest.mark.parametrize("line_break", sorted(BREAKS))
def test_the_cli_process_refuses_a_key_holding_a_line_break_without_repeating_it(
    line_break, loopback_api
):
    """The same refusal from a real process: no traceback, no log line, no slice of the key
    on either stream, and the exit code is still 1."""
    done = _run_module(
        "orinyx_mcp.cli",
        ["get", RUN_ID],
        {"ORINYX_API_URL": loopback_api, "ORINYX_API_KEY": _broken_key(BREAKS[line_break])},
    )
    err = done.stderr.decode()
    assert (done.returncode, done.stdout) == (1, b"")
    assert err == f"orinyx: {NOT_SENT}\n"
    assert_no_traceback(err)
    assert_no_slice(KEY_BODY, err)


@pytest.mark.parametrize("line_break", sorted(BREAKS))
async def test_an_mcp_tool_with_a_key_holding_a_line_break_never_repeats_it(
    line_break, loopback_api, caplog
):
    """The MCP server sends the same request with the operator's key: the tool error the
    agent reads, and anything logged at INFO or above, hold the fixed sentence and no slice
    of the key."""
    pytest.importorskip("mcp")
    import logging

    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    caplog.set_level(logging.INFO)
    client = OrinyxClient(loopback_api, _broken_key(BREAKS[line_break]))
    try:
        async with Client(build_server(shared(client)), mode="legacy") as mcp_client:
            result = await mcp_client.call_tool("get_verification", {"run_id": RUN_ID})
    finally:
        client.close()
    text = "\n".join(getattr(part, "text", "") for part in result.content)
    assert result.is_error
    assert NOT_SENT in text, text
    assert_no_slice(KEY_BODY, text, caplog.text, *(r.getMessage() for r in caplog.records))


# --- 4. the network server with a URL it cannot use -------------------------------------------

# (ORINYX_* settings, the error type the line names). The password sits where each URL
# parser quotes it: as the port, beside a bad port, or in a netloc NFKC rejects.
UNUSABLE_URLS = {
    "the password as the port": (
        {"ORINYX_API_URL": f"https://api.orinyx.example:{PASSWORD}"},
        "ValidationError",
    ),
    "a password beside a bad port": (
        {"ORINYX_API_URL": f"https://user:{PASSWORD}@api.orinyx.example:99x"},
        "ValidationError",
    ),
    "a password beside a port out of range": (
        {"ORINYX_API_URL": f"https://user:{PASSWORD}@api.orinyx.example:99999"},
        "ValidationError",
    ),
    "a password in a netloc NFKC rejects": (
        {"ORINYX_API_URL": f"https://us＃er:{PASSWORD}@api.orinyx.example"},
        "ValueError",
    ),
    "the issuer's password as its port": (
        {"ORINYX_API_URL": API_URL, "ORINYX_ISSUER_URL": f"https://id.orinyx.example:{PASSWORD}"},
        "ValidationError",
    ),
    "an arena password in a netloc NFKC rejects": (
        {
            "ORINYX_API_URL": API_URL,
            "ORINYX_ARENA_ENABLED": "true",
            "ORINYX_ARENA_URL": f"https://us＃er:{PASSWORD}@arena.orinyx.example",
        },
        "ValueError",
    ),
    "a downstream password in a netloc NFKC rejects": (
        {
            "ORINYX_API_URL": API_URL,
            "DOWNSTREAM_MCP_URL": f"https://us＃er:{PASSWORD}@mcp.downstream.example/mcp",
            "DOWNSTREAM_MCP_TOOLS": "search",
        },
        "ValueError",
    ),
}


def _unusable_line(case):
    if case in ("a password beside a bad port", "a password beside a port out of range"):
        return "ORINYX_API_URL must not contain a username or password"
    if case == "a password in a netloc NFKC rejects":
        return "ORINYX_API_URL is malformed (its value is not shown)"
    if case == "an arena password in a netloc NFKC rejects":
        return "ORINYX_ARENA_URL is malformed (its value is not shown)"
    return NOT_STARTED.format(UNUSABLE_URLS[case][1])


def _server_env(settings: dict[str, str]) -> dict[str, str]:
    return {
        "MCP_PUBLIC_URL": PUBLIC_URL,
        "PORT": "8000",
        "ORINYX_HOP_SECRET": HOP_SECRET,
        **settings,
    }


@pytest.mark.parametrize("case", sorted(UNUSABLE_URLS))
def test_the_server_with_an_unusable_url_prints_one_line_and_exits_1(case, monkeypatch, capsys):
    from orinyx_mcp import http

    settings, error_type = UNUSABLE_URLS[case]
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)
    for name, value in _server_env(settings).items():
        monkeypatch.setenv(name, value)
    assert http.serve() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == _unusable_line(case) + "\n"
    assert_no_slice(PASSWORD, captured.out, captured.err)


@pytest.mark.parametrize("case", sorted(UNUSABLE_URLS))
def test_the_server_process_with_an_unusable_url_has_no_traceback(case):
    settings, error_type = UNUSABLE_URLS[case]
    done = _run_module("orinyx_mcp", ["serve"], _server_env(settings))
    err = done.stderr.decode()
    assert (done.returncode, done.stdout) == (1, b"")
    assert err == _unusable_line(case) + "\n"
    assert_no_traceback(err)
    assert_no_slice(PASSWORD, err)


def test_the_orinyx_mcp_command_is_the_server_these_tests_run():
    """`orinyx-mcp` is a console script: it calls the function the in-process tests call and
    exits with what it returns. Run the way the installed script runs it, an unusable URL
    still gives one line and exit 1."""
    import subprocess
    import sys
    import tomllib

    root = Path(__file__).resolve().parent.parent
    scripts = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert scripts["scripts"]["orinyx-mcp"] == "orinyx_mcp.http:serve"
    settings, error_type = UNUSABLE_URLS["the password as the port"]
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_", "PYTHON"))
    }
    done = subprocess.run(
        [sys.executable, "-c", "import sys; from orinyx_mcp.http import serve; sys.exit(serve())"],
        cwd=root,
        env={**clean, "PYTHONPATH": str(root), "NO_COLOR": "1", **_server_env(settings)},
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    err = done.stderr.decode()
    assert (done.returncode, done.stdout) == (1, b"")
    assert err == NOT_STARTED.format(error_type) + "\n"
    assert_no_traceback(err)
    assert_no_slice(PASSWORD, err)


@pytest.mark.parametrize(
    "settings, line",
    [
        (
            {"ORINYX_API_URL": API_URL, "MCP_PUBLIC_URL": "http://mcp.orinyx.example"},
            "MCP_PUBLIC_URL must be an https URL (plain http only for localhost)",
        ),
        (
            {"ORINYX_API_URL": f"http://user:{PASSWORD}@api.orinyx.example"},
            "ORINYX_API_URL must not contain a username or password",
        ),
        ({"ORINYX_API_URL": API_URL, "PORT": "eighty"}, "PORT must be a number"),
        (
            {
                "ORINYX_API_URL": API_URL,
                "ORINYX_ARENA_ENABLED": "true",
                "ORINYX_ARENA_URL": "http://arena.example",
            },
            "ORINYX_ARENA_URL must be an https origin (http only for localhost)",
        ),
        (
            {
                "ORINYX_API_URL": API_URL,
                "ORINYX_ARENA_ENABLED": "true",
                "ORINYX_ARENA_URL": f"https://user:{PASSWORD}@arena.orinyx.example",
            },
            "ORINYX_ARENA_URL must not contain a username or password",
        ),
    ],
    ids=[
        "plain-http public url",
        "plain-http api url with a password",
        "port not a number",
        "plain-http arena url",
        "arena url with a password",
    ],
)
def test_a_setting_the_server_refuses_itself_is_still_named_in_one_line(settings, line):
    done = _run_module("orinyx_mcp", ["serve"], {**_server_env({}), **settings})
    err = done.stderr.decode()
    assert (done.returncode, done.stdout) == (1, b"")
    assert err == line + "\n"
    assert_no_traceback(err)
    assert_no_slice(PASSWORD, err)


def test_the_arena_url_refusal_is_printed_by_the_server_itself(monkeypatch, capsys):
    """The arena refusal is this package's own: serve prints it, not the generic line."""
    from orinyx_mcp import http

    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)
    settings = {
        "ORINYX_API_URL": API_URL,
        "ORINYX_ARENA_ENABLED": "true",
        "ORINYX_ARENA_URL": "http://arena.example",
    }
    for name, value in _server_env(settings).items():
        monkeypatch.setenv(name, value)
    assert http.serve() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ORINYX_ARENA_URL must be an https origin (http only for localhost)\n"


# --- 5. the stdio server with a downstream URL urllib cannot split ----------------------------

DOWNSTREAM_URLS = {
    "a password in a netloc NFKC rejects": (
        f"https://us＃er:{PASSWORD}@mcp.downstream.example/mcp"
    ),
    "an unclosed IPv6 bracket": f"https://[{PASSWORD}",
}


@pytest.mark.parametrize("case", sorted(DOWNSTREAM_URLS))
def test_the_stdio_server_never_repeats_a_downstream_url_it_cannot_split(case, monkeypatch, capsys):
    pytest.importorskip("mcp")
    from orinyx_mcp import server

    def must_not_start(*args, **kwargs):
        raise AssertionError("the stdio server must not start with this configuration")

    monkeypatch.setattr(server, "build_server", must_not_start)
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    monkeypatch.setenv("DOWNSTREAM_MCP_URL", DOWNSTREAM_URLS[case])
    monkeypatch.setenv("DOWNSTREAM_MCP_TOOLS", "search")
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout is the MCP protocol stream
    assert captured.err == DOWNSTREAM_MALFORMED
    assert_no_slice(PASSWORD, captured.out, captured.err)
    assert_no_slice(KEY_BODY, captured.out, captured.err)


def test_the_stdio_process_never_repeats_a_downstream_url_it_cannot_split():
    pytest.importorskip("mcp")
    done = _run_module(
        "orinyx_mcp",
        [],
        {
            "ORINYX_API_URL": API_URL,
            "ORINYX_API_KEY": KEY,
            "DOWNSTREAM_MCP_URL": DOWNSTREAM_URLS["a password in a netloc NFKC rejects"],
            "DOWNSTREAM_MCP_TOOLS": "search",
        },
    )
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == DOWNSTREAM_MALFORMED
    assert_no_slice(PASSWORD, done.stderr.decode())


def test_a_downstream_setting_the_stdio_server_refuses_itself_is_still_named(monkeypatch, capsys):
    pytest.importorskip("mcp")
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    monkeypatch.setenv("DOWNSTREAM_MCP_URL", f"http://user:{PASSWORD}@mcp.downstream.example")
    monkeypatch.setenv("DOWNSTREAM_MCP_TOOLS", "search")
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "DOWNSTREAM_MCP_URL must be an https URL (plain http only for localhost)\n"
    )
    assert_no_slice(PASSWORD, captured.out, captured.err)


def test_this_file_holds_no_real_looking_key():
    from tests.test_config_safety import real_looking_keys

    assert real_looking_keys(Path(__file__).read_text(encoding="utf-8")) == []

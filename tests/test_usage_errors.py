"""Usage errors and unusable configuration: no argument value and no key comes back out.

1. A usage error from `orinyx` never repeats an argument's value: a key passed by mistake as
   `--api-key <key>` or `--api-key=<key>`, a stray positional, a dash-led or glued word, an
   invalid choice for the command or --format, an ambiguous option given `=value`, a flag
   given `=value`. Unrecognised options are named, without their values. Every usage error
   exits 1 (the exit-code contract: 1 is an error or usage error, never 2), prints nothing
   on stdout and never builds a client. No word after a bare `--` is ever named: argparse
   reads each one as a value, however much it looks like an option.
2. A plain-http ORINYX_API_URL is one readable line on stderr and exit 1, on the CLI and on
   the stdio server (whose stdout, the protocol stream, stays empty). A URL or key that cannot
   be used for another reason is one fixed line that shows neither value.
3. The same, as real processes: `python -m orinyx_mcp.cli` and `python -m orinyx_mcp`.

The byte pins are of plain text. Python 3.14's argparse colours its usage and error lines when
the environment asks for colour, and wraps them to the terminal width, so every test here runs
with colour off and an 80-column terminal, in process and in a child process alike.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from orinyx_mcp import cli

from tests.test_clean_errors import RUN_ID, SENTINEL_BODY, SENTINEL_KEY, assert_no_traceback

ROOT = Path(__file__).resolve().parent.parent
# A value with every character a repr, a split or an escape could mangle: quotes, a space,
# `=`, a backslash, a non-ASCII letter. Its body never appears in an output.
HOSTILE_BODY = "H0ST'IL\"E q7=x\\zé"
HOSTILE = "ork_live_" + HOSTILE_BODY
VALUES = {"sentinel": (SENTINEL_KEY, SENTINEL_BODY), "hostile": (HOSTILE, "H0ST")}

TOP_USAGE = (
    "usage: orinyx [-h]\n"
    "              {login,logout,status,verify,get,accuracy,export,observe} ...\n"
)
COMMAND_CHOICES = (
    "'login', 'logout', 'status', 'verify', 'get', 'accuracy', 'export', 'observe'",
    "login, logout, status, verify, get, accuracy, export, observe",
)
FORMAT_CHOICES = ("'csv', 'pdf', 'report'", "csv, pdf, report")


def _choice_lines(prefix: str, choices: tuple[str, str]) -> set[str]:
    """argparse quotes its choices list on newer Pythons (3.14) and not on older (3.12)."""
    return {f"{prefix}invalid choice (choose from {listed})" for listed in choices}


UNRECOGNIZED = "orinyx: error: unrecognized arguments: "
HIDDEN_ONE = {UNRECOGNIZED + "--api-key (plus 1 value not shown)"}
BAD_COMMAND = _choice_lines("orinyx: error: argument command: ", COMMAND_CHOICES)
BAD_FORMAT = _choice_lines("orinyx export: error: argument --format: ", FORMAT_CHOICES)
AMBIGUOUS = {"orinyx verify: error: ambiguous option: --to could match --tool, --tool-version"}

# Each usage error that quoted a value before: (argv with {v} for the value, the error lines
# it may end with, other words that must not come back). The value is the sentinel key or the
# hostile value.
LEAKY: dict[str, tuple[list[str], set[str], tuple[str, ...]]] = {
    # an unrecognised option followed by its value
    "--api-key v after the run id": (["get", RUN_ID, "--api-key", "{v}"], HIDDEN_ONE, ()),
    "observe ... --api-key v": (["observe", "one.txt", "--api-key", "{v}"], HIDDEN_ONE, ()),
    # an unrecognised option given =value
    "--api-key=v": (["get", RUN_ID, "--api-key={v}"], {UNRECOGNIZED + "--api-key"}, ()),
    # argparse takes a word holding a space for a positional, so with the hostile value this
    # word is the command (an invalid choice); either way the value is not shown.
    "--api-key=v before the command": (
        ["--api-key={v}", "get", RUN_ID],
        {UNRECOGNIZED + "--api-key"} | BAD_COMMAND,
        (),
    ),
    "--token=v": (["get", RUN_ID, "--token={v}"], {UNRECOGNIZED + "--token"}, ()),
    # the value is taken as the run id, and the run id is what is left over
    "--api-key v before the run id": (["get", "--api-key", "{v}", RUN_ID], HIDDEN_ONE, (RUN_ID,)),
    # stray positionals, dash-led and glued words
    "two stray positionals": (
        ["get", RUN_ID, "{v}", "second"],
        {UNRECOGNIZED + "2 values not shown"},
        ("second",),
    ),
    "-v": (["get", RUN_ID, "-{v}"], {UNRECOGNIZED + "1 value not shown"}, ()),
    "-kv": (["get", RUN_ID, "-k{v}"], {UNRECOGNIZED + "1 value not shown"}, ()),
    "--v": (["get", RUN_ID, "--{v}"], {UNRECOGNIZED + "1 value not shown"}, ()),
    "one word '--api-key v'": (
        ["get", RUN_ID, "--api-key {v}"],
        {UNRECOGNIZED + "1 value not shown"},
        (),
    ),
    # an invalid choice for the command
    "v as the command": (["{v}"], BAD_COMMAND, ()),
    "--api-key v before the command": (["--api-key", "{v}", "get", RUN_ID], BAD_COMMAND, ()),
    "a command typo": (["verfy", "--file", "f"], BAD_COMMAND, ("verfy",)),
    # an invalid choice for --format
    "--format v": (["export", RUN_ID, "--format", "{v}", "--out", "o.csv"], BAD_FORMAT, ()),
    "--format=v": (["export", RUN_ID, "--format={v}", "--out", "o.csv"], BAD_FORMAT, ()),
    "a --format typo": (
        ["export", RUN_ID, "--format", "cvs", "--out", "o.csv"],
        BAD_FORMAT,
        ("cvs",),
    ),
    # an ambiguous option given =value
    "--to=v": (["verify", "--file", "f", "--to={v}"], AMBIGUOUS, ()),
    # a flag given =value: "ignored explicit argument"
    "--json=v": (
        ["get", RUN_ID, "--json={v}"],
        {"orinyx get: error: argument --json: ignored explicit argument"},
        (),
    ),
    "--js=v": (
        ["get", RUN_ID, "--js={v}"],
        {"orinyx get: error: argument --json: ignored explicit argument"},
        (),
    ),
    "--check-interactions=v": (
        ["verify", "--file", "f", "--check-interactions={v}"],
        {"orinyx verify: error: argument --check-interactions: ignored explicit argument"},
        (),
    ),
    "-h=v": (["-h={v}"], {"orinyx: error: argument -h/--help: ignored explicit argument"}, ()),
    "--help=v": (
        ["--help={v}"],
        {"orinyx: error: argument -h/--help: ignored explicit argument"},
        (),
    ),
    "--he=v": (["--he={v}"], {"orinyx: error: argument -h/--help: ignored explicit argument"}, ()),
    "get --help=v": (
        ["get", "--help={v}"],
        {"orinyx get: error: argument -h/--help: ignored explicit argument"},
        (),
    ),
}


# What decides whether argparse colours or wraps its output. Python 3.14 reads PYTHON_COLORS
# first (it overrides NO_COLOR), then NO_COLOR, FORCE_COLOR and TERM; the width is COLUMNS.
PLAIN_TERMINAL = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "80"}
COLOUR_SWITCHES = ("FORCE_COLOR", "PYTHON_COLORS", *PLAIN_TERMINAL)


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch):
    """Colour off and 80 columns, whatever the caller's terminal or environment asks for."""
    for name in COLOUR_SWITCHES:
        monkeypatch.delenv(name, raising=False)
    for name, value in PLAIN_TERMINAL.items():
        monkeypatch.setenv(name, value)


def run_usage_error(argv: list[str], capsys) -> tuple[object, str, str, list[str]]:
    built: list[str] = []
    with pytest.raises(SystemExit) as exited:
        cli.main(argv, client_factory=lambda url, key: built.append(key))
    captured = capsys.readouterr()
    return exited.value.code, captured.out, captured.err, built


@pytest.fixture
def api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ORINYX_API_URL", "https://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "one.txt").write_text("warfarin 5 mg by mouth daily\n")


def _leaky_params():
    """Each case once per value it can carry; a case with no value slot (a typo) once."""
    for case, (template, _, _) in LEAKY.items():
        takes_value = any("{v}" in word for word in template)
        for value in sorted(VALUES) if takes_value else ["sentinel"]:
            yield pytest.param(case, value, id=f"{case}-{value}" if takes_value else case)


@pytest.mark.parametrize(("case", "value"), list(_leaky_params()))
def test_a_usage_error_never_repeats_an_argument_value(case, value, api_env, capsys):
    template, error_lines, also_hidden = LEAKY[case]
    full, body = VALUES[value]
    argv = [word.replace("{v}", full) for word in template]
    code, out, err, built = run_usage_error(argv, capsys)
    assert code == cli.EXIT_ERROR == 1, (argv, code, err)
    assert out == "" and built == [], (argv, out)
    assert err.startswith("usage: orinyx"), err
    assert err.splitlines()[-1] in error_lines, err
    for hidden in (full, body, repr(full), *also_hidden):
        assert hidden not in err, (argv, err)
    assert_no_traceback(err)


def test_a_key_flag_names_only_the_option(api_env, capsys):
    """The two forms of a key passed by mistake, pinned byte for byte."""
    code, out, err, _ = run_usage_error(["get", RUN_ID, "--api-key", SENTINEL_KEY], capsys)
    assert (code, out) == (1, "")
    assert (
        err
        == TOP_USAGE + "orinyx: error: unrecognized arguments: --api-key (plus 1 value not shown)\n"
    )
    code, out, err, _ = run_usage_error(["get", RUN_ID, "--api-key=" + SENTINEL_KEY], capsys)
    assert (code, out) == (1, "")
    assert err == TOP_USAGE + "orinyx: error: unrecognized arguments: --api-key\n"


# Usage errors that never quoted a value: still exit 1, with their argparse text unchanged.
VALUE_FREE = {
    "no command": [],
    "verify without --file": ["verify"],
    "--file without its value": ["verify", "--file"],
    "an ambiguous option without a value": ["verify", "--file", "f", "--to"],
    "unknown options only": ["get", RUN_ID, "--bogus", "--other", "-x"],
    "export without --out": ["export", RUN_ID],
}


@pytest.mark.parametrize("case", list(VALUE_FREE))
def test_every_usage_error_exits_1_never_2(case, api_env, capsys):
    code, out, err, built = run_usage_error(VALUE_FREE[case], capsys)
    assert code == cli.EXIT_ERROR == 1 and code != cli.EXIT_FLAGGED, (case, code)
    assert out == "" and built == [] and " error: " in err, (case, err)


def test_unknown_option_names_are_listed_as_argparse_lists_them(api_env, capsys):
    _, _, err, _ = run_usage_error(VALUE_FREE["unknown options only"], capsys)
    assert err == TOP_USAGE + "orinyx: error: unrecognized arguments: --bogus --other -x\n"


# --- words after a bare `--` -----------------------------------------------------------------

# Past the first bare `--` argparse reads every word as a value, so a key typed there is a
# value even when, all lower case and led by dashes, it looks like an option name. The `--`
# itself is syntax, never a value: when argparse leaves it over it is named as `--`.
LOWER_KEY = "--ork_live_" + "lowersentinel" + "q7zx" * 8
LOWER_BODY = LOWER_KEY.removeprefix("--ork_live_")
DASHED = {"lower-case": (LOWER_KEY, LOWER_BODY), "mixed-case": ("--" + SENTINEL_KEY, SENTINEL_BODY)}

# (argv with {v} for the value, the exact text after "unrecognized arguments: ")
AFTER_SEPARATOR: dict[str, tuple[list[str], str]] = {
    "get RUN -- v": (["get", RUN_ID, "--", "{v}"], "1 value not shown"),
    "get RUN -- -k": (["get", RUN_ID, "--", "-k"], "1 value not shown"),
    "get -- RUN v": (["get", "--", RUN_ID, "{v}"], "1 value not shown"),
    "get RUN -- v=x": (["get", RUN_ID, "--", "{v}=x"], "1 value not shown"),
    "get RUN -- --json": (["get", RUN_ID, "--", "--json"], "1 value not shown"),
    "accuracy RUN -- -k": (["accuracy", RUN_ID, "--", "-k"], "1 value not shown"),
    "get RUN -- -- v": (["get", RUN_ID, "--", "--", "{v}"], "2 values not shown"),
    "get RUN -- v --bogus": (["get", RUN_ID, "--", "{v}", "--bogus"], "2 values not shown"),
    "get RUN -- --": (["get", RUN_ID, "--", "--"], "1 value not shown"),
    "get RUN -- x": (["get", RUN_ID, "--", "x"], "1 value not shown"),
    # an unknown option before the `--` is still named; the value after it is not
    "get RUN --bogus -- v": (
        ["get", RUN_ID, "--bogus", "--", "{v}"],
        "--bogus -- (plus 1 value not shown)",
    ),
    "--bogus get RUN -- v": (
        ["--bogus", "get", RUN_ID, "--", "{v}"],
        "--bogus (plus 1 value not shown)",
    ),
    # the same word on both sides: named before the `--`, hidden after it
    "get RUN --bogus -- --bogus": (
        ["get", RUN_ID, "--bogus", "--", "--bogus"],
        "--bogus -- (plus 1 value not shown)",
    ),
    "get RUN --json -- --json": (
        ["get", RUN_ID, "--json", "--", "--json"],
        "-- (plus 1 value not shown)",
    ),
    "verify --file f -- v -k": (
        ["verify", "--file", "f", "--", "{v}", "-k"],
        "-- (plus 2 values not shown)",
    ),
    "export RUN --out o -- v": (
        ["export", RUN_ID, "--out", "o", "--", "{v}"],
        "-- (plus 1 value not shown)",
    ),
    # a trailing `--` with nothing after it is the only word left over
    "verify --file f --json --": (["verify", "--file", "f", "--json", "--"], "--"),
}


def _after_separator_params():
    for case, (template, _) in AFTER_SEPARATOR.items():
        if any("{v}" in word for word in template):
            for value in DASHED:
                yield pytest.param(case, value, id=f"{case}-{value}")
        else:
            yield pytest.param(case, None, id=case)


@pytest.mark.parametrize(("case", "value"), list(_after_separator_params()))
def test_no_word_after_a_bare_separator_is_ever_named(case, value, api_env, capsys):
    template, tail = AFTER_SEPARATOR[case]
    full, body = DASHED[value] if value else ("", "")
    argv = [word.replace("{v}", full) for word in template]
    code, out, err, built = run_usage_error(argv, capsys)
    assert (code, out, built) == (1, "", []), (argv, code, out)
    assert err == TOP_USAGE + UNRECOGNIZED + tail + "\n", (argv, err)
    separator = argv.index("--")
    before = set(argv[:separator])
    named = err.splitlines()[-1].removeprefix(UNRECOGNIZED).split()
    for word in argv[separator + 1 :]:
        # a word typed on both sides is pinned by the exact line above
        if word != "--" and word not in before:
            assert word not in named, (argv, word, err)
    if value:
        for hidden in (full, body, full.split("=", 1)[0]):
            assert hidden not in err, (argv, err)
    assert_no_traceback(err)


# --- configuration that cannot be used -------------------------------------------------------

PLAIN_HTTP_LINE = "ORINYX_API_URL must use https (plain http only for localhost)."
MALFORMED_LINE = "ORINYX_API_URL or ORINYX_API_KEY is malformed (neither value is shown)."
# A secret carried in a URL (a password or junk port text). It never appears in an output.
URL_SECRET = "pw" + "Q8vR" * 4
NON_ASCII_KEY = "ork_live_" + "N0NASCé" + "q7Zx" * 4
API_KEY_ENV = {"ORINYX_API_KEY": SENTINEL_KEY}

# (ORINYX_API_URL, ORINYX_API_KEY, the line printed, what must not come back)
UNUSABLE: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "plain http": ("http://api.orinyx.example", SENTINEL_KEY, PLAIN_HTTP_LINE, ()),
    "plain http with a user and password": (
        f"http://user:{URL_SECRET}@api.orinyx.example",
        SENTINEL_KEY,
        "ORINYX_API_URL must not contain a username or password",
        (URL_SECRET, "user:"),
    ),
    "a port that is not a number": (
        f"https://api.orinyx.example:{URL_SECRET}",
        SENTINEL_KEY,
        MALFORMED_LINE,
        (URL_SECRET, "api.orinyx.example"),
    ),
    "a user name that does not survive NFKC": (
        f"https://us＃er:{URL_SECRET}@api.orinyx.example",
        SENTINEL_KEY,
        "ORINYX_API_URL is malformed (its value is not shown)",
        (URL_SECRET, "us＃er"),
    ),
    "an unclosed IPv6 host": (
        f"https://[{URL_SECRET}",
        SENTINEL_KEY,
        "ORINYX_API_URL is malformed (its value is not shown)",
        (URL_SECRET,),
    ),
    "a key with a non-ASCII character": (
        "https://api.orinyx.example",
        NON_ASCII_KEY,
        MALFORMED_LINE,
        ("N0NASC", "\\xe9", "é"),
    ),
}


def _set_config(monkeypatch, case: str) -> tuple[str, tuple[str, ...]]:
    url, key, line, hidden = UNUSABLE[case]
    monkeypatch.setenv("ORINYX_API_URL", url)
    monkeypatch.setenv("ORINYX_API_KEY", key)
    return line, (SENTINEL_BODY, *hidden)


@pytest.mark.parametrize("case", list(UNUSABLE))
def test_the_cli_refuses_an_unusable_url_or_key_in_one_line(case, monkeypatch, tmp_path, capsys):
    """The real client, no transport: nothing is sent, since building the client fails."""
    line, hidden = _set_config(monkeypatch, case)
    claims = tmp_path / "claims.json"
    claims.write_text('[{"rawText": "x", "drug": "x", "claimType": "dose_range"}]')
    orders = tmp_path / "one.txt"
    orders.write_text("warfarin 5 mg by mouth daily\n")
    for argv in (["get", RUN_ID], ["verify", "--file", str(claims)], ["observe", str(orders)]):
        code = cli.main(argv)
        captured = capsys.readouterr()
        assert (code, captured.out) == (cli.EXIT_ERROR, ""), (argv, code, captured.out)
        assert captured.err == f"orinyx: {line}\n", (argv, captured.err)
        for word in hidden:
            assert word not in captured.err, (argv, word)


@pytest.mark.parametrize("case", list(UNUSABLE))
def test_the_stdio_server_refuses_an_unusable_url_or_key_in_one_line(case, monkeypatch, capsys):
    pytest.importorskip("mcp")
    from orinyx_mcp import __main__ as stdio
    from orinyx_mcp import server

    def must_not_start(*args, **kwargs):
        raise AssertionError("the stdio server must not start with this configuration")

    monkeypatch.setattr(server, "build_server", must_not_start)
    line, hidden = _set_config(monkeypatch, case)
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout is the MCP protocol stream
    assert captured.err == f"{line}\n"
    for word in hidden:
        assert word not in captured.err, word


# --- the same, as real processes -------------------------------------------------------------


def _run_module(module: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    clean = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_", "PYTHON"))
        and name not in COLOUR_SWITCHES
    }
    clean["PYTHONPATH"] = str(ROOT)  # this checkout's package, not an installed copy
    clean.update(PLAIN_TERMINAL)
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=ROOT,
        env={**clean, **env},
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )


def test_the_cli_process_hides_a_key_flag_and_exits_1():
    done = _run_module(
        "orinyx_mcp.cli",
        ["get", RUN_ID, "--api-key", SENTINEL_KEY],
        {"ORINYX_API_URL": "https://api.orinyx.example", **API_KEY_ENV},
    )
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == (
        TOP_USAGE + "orinyx: error: unrecognized arguments: --api-key (plus 1 value not shown)\n"
    )


@pytest.mark.parametrize(
    "case", ["get RUN -- v", "verify --file f -- v -k", "export RUN --out o -- v"]
)
def test_the_cli_process_never_names_a_word_after_a_bare_separator(case):
    template, tail = AFTER_SEPARATOR[case]
    argv = [word.replace("{v}", LOWER_KEY) for word in template]
    done = _run_module(
        "orinyx_mcp.cli", argv, {"ORINYX_API_URL": "https://api.orinyx.example", **API_KEY_ENV}
    )
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == TOP_USAGE + UNRECOGNIZED + tail + "\n"
    assert LOWER_BODY.encode() not in done.stderr and b"-k" not in done.stderr


@pytest.mark.parametrize(("module", "prefix"), [("orinyx_mcp.cli", "orinyx: "), ("orinyx_mcp", "")])
def test_a_plain_http_url_is_one_line_from_a_real_process(module, prefix):
    if module == "orinyx_mcp":
        pytest.importorskip("mcp")
    args = ["get", RUN_ID] if module == "orinyx_mcp.cli" else []
    done = _run_module(module, args, {"ORINYX_API_URL": "http://api.orinyx.example", **API_KEY_ENV})
    assert done.returncode == 1
    assert done.stdout == b""  # for the stdio server, the protocol stream
    assert done.stderr.decode() == f"{prefix}{PLAIN_HTTP_LINE}\n"
    assert SENTINEL_BODY.encode() not in done.stderr


@pytest.mark.parametrize(("module", "prefix"), [("orinyx_mcp.cli", "orinyx: "), ("orinyx_mcp", "")])
def test_a_password_in_a_bad_port_never_reaches_a_real_process_output(module, prefix):
    if module == "orinyx_mcp":
        pytest.importorskip("mcp")
    args = ["get", RUN_ID] if module == "orinyx_mcp.cli" else []
    url = f"https://api.orinyx.example:{URL_SECRET}"
    done = _run_module(module, args, {"ORINYX_API_URL": url, **API_KEY_ENV})
    assert (done.returncode, done.stdout) == (1, b"")
    assert done.stderr.decode() == f"{prefix}{MALFORMED_LINE}\n"
    assert URL_SECRET.encode() not in done.stderr

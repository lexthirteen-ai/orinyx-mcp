"""Configuration safety.

1. An API key comes from the environment (ORINYX_API_KEY) only: no command-line flag and no
   config file is a source of one.
2. No error message, log line or --json output prints the key. A distinctive synthetic key
   is set in the environment and every failure path is driven; it must never come back.
3. No tracked file shows a real-looking key: placeholders only.
"""

import ast
import logging
import os
import re
import stat
import subprocess
from pathlib import Path

import httpx
import pytest
from orinyx_mcp import __main__ as stdio
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxApiError
from orinyx_mcp.config import Config

from tests.test_clean_errors import (
    API_URL,
    FAILURES,
    REFUSALS,
    RUN_ID,
    SENTINEL_BODY,
    SENTINEL_KEY,
    STATUSES,
    TOOL_CALLS,
    api_client,
    call_tools,
    cli_commands,
    refusing,
    run_cli,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "orinyx_mcp"
CREDENTIAL_WORDS = re.compile(r"key|token|secret|credential|password|passwd|bearer|auth", re.I)


def assert_no_key(*texts: str) -> None:
    for text in texts:
        assert SENTINEL_BODY not in text, text


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)


# --- 1. keys come from the environment only ---------------------------------------------------


def _all_parsers(parser):
    yield parser
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        for sub in choices.values() if isinstance(choices, dict) else ():
            if hasattr(sub, "_actions"):
                yield from _all_parsers(sub)


def test_no_cli_option_or_argument_takes_a_key():
    """Fails if any command grows an --api-key / --token / --secret style option."""
    found = []
    for parser in _all_parsers(cli._parser()):
        for action in parser._actions:
            names = [*action.option_strings, action.dest or "", action.metavar or ""]
            found += [f"{parser.prog}: {n}" for n in names if CREDENTIAL_WORDS.search(str(n))]
    assert found == []


def test_a_key_flag_is_a_usage_error_and_the_client_is_never_built(api_env, capsys):
    built = []
    for argv in (
        ["get", RUN_ID, "--api-key", "x"],
        ["--api-key", "x", "get", RUN_ID],
        ["get", RUN_ID, "--token=x"],
    ):
        with pytest.raises(SystemExit) as exited:
            cli.main(argv, client_factory=lambda url, key: built.append(key))
        assert exited.value.code == cli.EXIT_ERROR, argv
    assert built == []
    capsys.readouterr()


def test_a_key_passed_by_mistake_as_a_flag_is_not_echoed(api_env, capsys):
    with pytest.raises(SystemExit):
        cli.main(["get", RUN_ID, "--api-key", SENTINEL_KEY], client_factory=lambda u, k: None)
    captured = capsys.readouterr()
    assert_no_key(captured.out, captured.err)


def test_the_cli_hands_the_client_exactly_the_environment_key(api_env, capsys):
    seen = []

    def factory(url, key):
        seen.append((url, key))
        return api_client(refusing(404), key)

    cli.main(["get", RUN_ID], client_factory=factory)
    capsys.readouterr()
    assert seen == [(API_URL, SENTINEL_KEY)]


DECOY_CONFIG_FILES = (
    ".orinyx",
    ".orinyxrc",
    ".orinyx.toml",
    ".env",
    "orinyx.toml",
    "orinyx.json",
    ".config/orinyx/config.toml",
    ".config/orinyx/config.json",
    ".config/orinyx/credentials",
    ".netrc",
)


def test_without_the_environment_key_no_config_file_supplies_one(monkeypatch, tmp_path, capsys):
    """Key-bearing files in the home and working directories are never read: with
    ORINYX_API_KEY unset the CLI and the stdio server stop and ask for the variable."""
    home = tmp_path / "home"
    work = tmp_path / "work"
    for base in (home, work):
        for name in DECOY_CONFIG_FILES:
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"ORINYX_API_KEY={SENTINEL_KEY}\napi_key = {SENTINEL_KEY!r}\n"
                f'{{"apiKey": "{SENTINEL_KEY}"}}\n'
                f"machine api.orinyx.example login x password {SENTINEL_KEY}\n"
            )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.delenv("ORINYX_API_KEY", raising=False)
    monkeypatch.chdir(work)

    built = []
    code = cli.main(["get", RUN_ID], client_factory=lambda url, key: built.append(key))
    assert code == cli.EXIT_ERROR and built == []
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert "ORINYX_API_KEY" in captured.err
    assert_no_key(captured.out, captured.err)


def test_the_stdio_entry_point_takes_no_flags(monkeypatch, capsys):
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)
    for argv in (["--api-key", "x"], ["--token", "x"], ["serve", "--api-key", "x"]):
        assert stdio.main(argv) == 1, argv
    captured = capsys.readouterr()
    assert "usage: python -m orinyx_mcp [serve]" in captured.err
    assert_no_key(captured.out, captured.err)


def _module_trees():
    for path in sorted(PACKAGE.rglob("*.py")):
        yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(), filename=str(path))


# Modules that read a configuration or credentials file. None is imported by the package.
CONFIG_FILE_READERS = {"tomllib", "toml", "tomli", "configparser", "dotenv", "yaml", "netrc"}
CONFIG_FILE_READERS |= {"keyring", "dotenv.main"}


def test_the_package_imports_no_config_file_reader_and_reads_no_home_directory():
    found = []
    for name, tree in _module_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [f"{name}: import {a.name}" for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(f"{name}: from {node.module}")
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in ("expanduser", "home")
                and name != "orinyx_mcp/credentials.py"
            ):
                found.append(f"{name}: .{node.attr} (home directory)")
    readers = [
        hit
        for hit in found
        if hit.split(" ")[-1].split(".")[0] in CONFIG_FILE_READERS or "home directory" in hit
    ]
    assert [hit for hit in readers if not hit.startswith("orinyx_mcp/credentials.py:")] == []


def test_only_the_environment_names_the_api_key():
    """Every mention of ORINYX_API_KEY in code is a read of os.environ, and the two entry
    points that build a client from it take the key from that read alone."""
    reads = []
    for name, tree in _module_trees():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and node.args):
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and first.value == "ORINYX_API_KEY"):
                continue
            reads.append(name)
            assert ast.unparse(node.func) == "os.environ.get", (name, ast.unparse(node))
    assert sorted(reads) == ["orinyx_mcp/__main__.py", "orinyx_mcp/cli.py"]


def test_the_config_module_reads_the_environment_only():
    source = (PACKAGE / "config.py").read_text()
    tree = ast.parse(source)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    file_reads = {c for c in calls if re.search(r"\bopen\b|read_text|read_bytes|Path", c)}
    assert file_reads == set()
    imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imports |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"os", "re", "collections.abc", "dataclasses", "urllib.parse"}, imports


def test_the_network_config_holds_no_api_key():
    """The network server forwards each caller's own credential; its config has no key
    field and ignores ORINYX_API_KEY in its environment."""
    fields = set(Config.__dataclass_fields__)
    assert {f for f in fields if re.search(r"key|token|credential|password", f)} == set()
    config = Config.from_env(
        {
            "MCP_PUBLIC_URL": "https://mcp.example",
            "ORINYX_API_URL": API_URL,
            "ORINYX_API_KEY": SENTINEL_KEY,
        }
    )
    assert_no_key(repr(config), *(str(getattr(config, f)) for f in fields))


# --- 2. the key never comes back out ---------------------------------------------------------


def _exception_texts(exc: BaseException) -> list[str]:
    texts = []
    while exc is not None:
        texts += [str(exc), repr(exc), *(str(a) for a in exc.args)]
        exc = exc.__cause__ or exc.__context__
    return texts


@pytest.mark.parametrize(
    "case", [f"refusal_{s}" for s in STATUSES] + [f"failure_{f}" for f in sorted(FAILURES)]
)
def test_client_errors_and_logs_never_carry_the_key(case, caplog):
    caplog.set_level(logging.DEBUG)
    kind, _, which = case.partition("_")
    handler = refusing(int(which)) if kind == "refusal" else FAILURES[which][0]
    client = api_client(handler)
    calls = (
        lambda: client.verify_orders(["warfarin 5 mg by mouth daily"]),
        lambda: client.get_run(RUN_ID),
        lambda: client.accuracy(RUN_ID),
        lambda: client.export(RUN_ID, "csv"),
        lambda: client.labels("warfarin"),
        lambda: client.exam_runs(),
    )
    for call in calls:
        with pytest.raises(OrinyxApiError) as raised:
            call()
        assert_no_key(*_exception_texts(raised.value), raised.value.message)
        assert_no_key(*(str(d) for d in raised.value.details))
    client.close()
    assert_no_key(caplog.text, *(r.getMessage() for r in caplog.records))


@pytest.mark.parametrize("status", STATUSES)
async def test_mcp_tool_errors_and_logs_never_carry_the_key(status, caplog):
    caplog.set_level(logging.DEBUG)
    results = await call_tools(refusing(status), list(TOOL_CALLS))
    for name, (_, text) in results.items():
        assert SENTINEL_BODY not in text, name
    assert_no_key(caplog.text)


@pytest.mark.parametrize("failure", sorted(FAILURES))
async def test_mcp_tool_failures_never_carry_the_key(failure, caplog):
    caplog.set_level(logging.DEBUG)
    results = await call_tools(FAILURES[failure][0], list(TOOL_CALLS))
    for name, (_, text) in results.items():
        assert SENTINEL_BODY not in text, name
    assert_no_key(caplog.text)


def test_the_tool_error_raised_inside_the_server_never_carries_the_key():
    pytest.importorskip("mcp")
    import asyncio

    from orinyx_mcp.server import build_server, shared

    for status in STATUSES:
        server = build_server(shared(api_client(refusing(status))))
        with pytest.raises(Exception) as raised:  # noqa: PT011 - the SDK's ToolError moved
            asyncio.run(server.call_tool("get_verification", {"run_id": RUN_ID}))
        assert type(raised.value).__name__ == "ToolError"
        assert REFUSALS[status][1] in str(raised.value)
        assert_no_key(*_exception_texts(raised.value))


@pytest.mark.parametrize("handler_name", [f"refusal_{s}" for s in STATUSES] + sorted(FAILURES))
def test_cli_output_never_carries_the_key(handler_name, api_env, tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    if handler_name.startswith("refusal_"):
        handler = refusing(int(handler_name.removeprefix("refusal_")))
    else:
        handler = FAILURES[handler_name][0]
    for name, argv in cli_commands(tmp_path).items():
        code, out, err = run_cli(argv, handler, capsys)
        assert code == cli.EXIT_ERROR, name
        assert_no_key(out, err)
    assert_no_key(caplog.text)


def test_cli_local_errors_never_carry_the_key(api_env, tmp_path, capsys):
    """Errors raised before or without a request: a bad run id, a missing file, a refused
    record, a missing URL."""
    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("{not json\n")
    for argv in (
        ["get", "not-a-uuid"],
        ["verify", "--file", str(tmp_path / "missing.json")],
        ["observe", str(bad_json)],
        ["accuracy", "../x"],
    ):
        code, out, err = run_cli(argv, refusing(404), capsys)
        assert code == cli.EXIT_ERROR and err.startswith("orinyx: "), (argv, err)
        assert_no_key(out, err)
    os.environ.pop("ORINYX_API_URL")
    assert cli.main(["get", RUN_ID]) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert_no_key(captured.out, captured.err)


async def test_the_network_credential_check_never_logs_the_token(caplog):
    """The network server's check of a caller's credential: an unreachable API and every
    refusal leave the token out of the log."""
    pytest.importorskip("mcp")
    from orinyx_mcp.http import IntrospectionVerifier

    caplog.set_level(logging.DEBUG)

    def unreachable(request):
        raise httpx.ConnectError("connection refused", request=request)

    handlers = [unreachable, *(refusing(s) for s in STATUSES)]
    for handler in handlers:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            verifier = IntrospectionVerifier(API_URL, "https://mcp.example/mcp", http)
            assert await verifier.verify_token(SENTINEL_KEY) is None
    assert "credential check failed" in caplog.text  # the unreachable case was logged
    assert_no_key(caplog.text)


# --- 3. no tracked file shows a real-looking key --------------------------------------------

# Real-looking:
# - an Orinyx credential prefix, `ork_` then two or more letters then `_` (ork_live_,
#   ork_test_, ork_oat_, ork_ort_, a longer one such as ork_signup_), in any case (ORK_LIVE_,
#   ork_LIVE_), followed by 16 or more key-alphabet characters;
# - a bearer (any case, so `authorization: bearer ...` too) followed by a 16+ character
#   literal;
# - one of the credential variables assigned (= or :) a 16+ character literal; the variable
#   names are upper case, except SIGNUP_HOOK_SECRET, which matches in any case;
# - the X-Orinyx-Signup-Secret header (any case) given a 16+ character literal.
# A placeholder (<your ork_live_ key>, $ORINYX_API_KEY, ...) does not start with a
# key-alphabet character and so never matches.
REAL_LOOKING = (
    re.compile(r"\bork_[a-z]{2,}_[a-z0-9_\-]{16,}", re.I),
    re.compile(r"\bbearer\s+([A-Za-z0-9_\-.~+/]{16,})", re.I),
    re.compile(
        r"\b(?:ORINYX_API_KEY|DOWNSTREAM_MCP_TOKEN|ORINYX_HOP_SECRET|(?i:SIGNUP_HOOK_SECRET))"
        r"[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_\-.~+/]{16,}"
    ),
    re.compile(r"\bX-Orinyx-Signup-Secret[\"']?\s*:\s*[\"']?[A-Za-z0-9_\-.~+/]{16,}", re.I),
)
# Exact strings allowed to match REAL_LOOKING. Empty: add an entry only for a string that is
# provably not a credential, with the reason beside it.
ALLOWED: frozenset[str] = frozenset()
_SKIP_DIRS = {".git", ".venv", ".worktrees", "__pycache__", ".pytest_cache", ".ruff_cache"}
_BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".whl", ".gz", ".zip"}


def _walk_files(root: Path) -> list[Path]:
    """Every file under root, never descending into a _SKIP_DIRS directory at any level."""
    found: list[Path] = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        found += [Path(dirpath) / f for f in files]
    return found


def _tracked_files(root: Path = ROOT) -> list[Path]:
    """`git ls-files` in a checkout; a walk of the tree (minus caches) anywhere else."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=30
        ).stdout.decode()
        names = [n for n in listed.split("\0") if n]
    except (OSError, subprocess.SubprocessError):
        names = []
    if names:
        return [root / n for n in names]
    return _walk_files(root)


def real_looking_keys(text: str) -> list[str]:
    hits = [m.group(0) for pattern in REAL_LOOKING for m in pattern.finditer(text)]
    return [hit for hit in hits if hit not in ALLOWED]


def _masked(hit: str) -> str:
    """Enough to find a hit, never enough to use it: its first characters and its length."""
    return f"{hit[:8]}... ({len(hit)} chars)"


def key_scan(root: Path, files: list[Path]) -> list[str]:
    """Each real-looking key in these files as `path:line: <masked hit>`. A file that cannot
    be read (an OSError: no permission, an I/O error) is not known to be clean, so it is a
    hit too, as `path: could not be read (<error type>)`, and the scan goes on to the rest."""
    hits = []
    for path in files:
        if path.suffix.lower() in _BINARY:
            continue
        where = path.relative_to(root).as_posix()
        # Whether it is a file is asked inside the try, and by stat() rather than is_file():
        # under a directory that cannot be searched, is_file() raises on Python 3.12 but answers
        # False on 3.14, which would pass the file unread as "not a file".
        try:
            mode = path.stat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            continue  # listed but not there (deleted, or a dangling symlink): nothing to read
        except OSError as exc:
            hits.append(f"{where}: could not be read ({type(exc).__name__})")
            continue
        if not stat.S_ISREG(mode):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            hits.append(f"{where}: could not be read ({type(exc).__name__})")
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            hits += [f"{where}:{number}: {_masked(hit)}" for hit in real_looking_keys(line)]
    return hits


def assert_no_real_looking_key(root: Path, files: list[Path]) -> None:
    hits = key_scan(root, files)
    assert not hits, "real-looking keys or unreadable files (values masked):\n" + "\n".join(hits)


def test_the_detector_tells_a_real_looking_key_from_a_placeholder():
    real = "ork_live_" + "Q3vX9kLm2Pz8Rt5Wn1Yb"
    body = "Q3vX9kLm2Pz8Rt5Wn1Yb"
    assert real_looking_keys(f"export ORINYX_API_KEY={real}")
    assert real_looking_keys(f"Authorization: Bearer {real}")
    assert real_looking_keys('"DOWNSTREAM_MCP_TOKEN": "' + "tok" + "_9f8e7d6c5b4a3f2e1d" + '"')
    for prefix in ("live", "test", "oat", "ort"):  # a key, a test key, sign-in, refresh token
        assert real_looking_keys(f"ork_{prefix}_{body}"), prefix
    assert real_looking_keys(f"refresh_token = {'ork_ort_'}{body}")
    assert real_looking_keys(f"export SIGNUP_HOOK_SECRET={body}")
    assert real_looking_keys(f'SIGNUP_HOOK_SECRET: "{body}"')
    assert real_looking_keys(f"SIGNUP_HOOK_SECRET={body[:16]}")  # 16 characters is enough
    assert real_looking_keys(f'-H "authorization: bearer {body}"')
    assert real_looking_keys(f"AUTHORIZATION: BEARER {body}")
    for placeholder in (
        "export ORINYX_API_KEY=<an ork_live_ key issued to you>",
        '"ORINYX_API_KEY": "<your ork_live_ key>"',
        '-e ORINYX_API_KEY="$ORINYX_API_KEY"',
        "a key (`ork_live_...`)",
        "ORINYX_API_KEY: ${{ secrets.ORINYX_API_KEY }}",
        '--header "Authorization: Bearer $ORINYX_API_KEY"',
        "Ask Orinyx for a tester API key (`ork_live_…`)",
        "ORINYX_API_KEY=... python evals/mcp_local_check.py",
        f"SIGNUP_HOOK_SECRET={body[:15]}",  # 15 characters is not
        "a refresh token (`ork_ort_...`)",
        "-H 'authorization: bearer $ORINYX_API_KEY'",
        "the bearer an agent presents is handed to the API",
        "OrinyxClient(url, 'ork_live_test')",
    ):
        assert real_looking_keys(placeholder) == [], placeholder


def test_no_tracked_file_shows_a_real_looking_key():
    files = _tracked_files()
    names = {path.relative_to(ROOT).as_posix() for path in files}
    assert {"README.md", "docs/QUICKSTART.md", "SECURITY.md"} <= names  # the docs were read
    assert_no_real_looking_key(ROOT, files)


def test_the_key_scan_masks_every_hit_and_prunes_skipped_directories(tmp_path):
    """A planted synthetic key is reported by path and line, never by value, and a skipped
    directory is pruned even where its parent holds no file (tmp_path holds only folders)."""
    planted = "ork_live_" + "PLANTED" + "w4Rk" * 6
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "settings.env").write_text(f"# synthetic\nORINYX_API_KEY={planted}\n")
    vendored = tmp_path / ".venv" / "lib"
    vendored.mkdir(parents=True)
    (vendored / "vendored.py").write_text(f"KEY = '{planted}'\n")

    files = _walk_files(tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in files] == ["pkg/settings.env"]
    with pytest.raises(AssertionError) as failure:
        assert_no_real_looking_key(tmp_path, files)
    message = str(failure.value)
    assert "pkg/settings.env:2: ork_live... (" in message
    assert "pkg/settings.env:2: ORINYX_A... (" in message
    assert planted not in message
    assert "PLANTED" not in message and "w4Rk" not in message


# A synthetic credential body, assembled so no source line holds a key-shaped literal.
SYNTHETIC_BODY = "Synth" + "eticValue0123456"


def test_a_pasted_signup_secret_header_value_is_real_looking():
    body = SYNTHETIC_BODY
    for line in (
        f'-H "X-Orinyx-Signup-Secret: {body}"',
        f"x-orinyx-signup-secret: {body}",
        f"X-ORINYX-SIGNUP-SECRET:{body}",
        f"headers = {{'X-Orinyx-Signup-Secret': '{body}'}}",
        f'{{"X-Orinyx-Signup-Secret": "{body}"}}',
        f"X-Orinyx-Signup-Secret: {body[:16]}",  # 16 characters is enough
    ):
        assert real_looking_keys(line), line
    for line in (
        '-H "X-Orinyx-Signup-Secret: $SIGNUP_HOOK_SECRET"',
        "X-Orinyx-Signup-Secret: ${SIGNUP_HOOK_SECRET}",
        "X-Orinyx-Signup-Secret: <the shared secret>",
        f"X-Orinyx-Signup-Secret: {body[:15]}",  # 15 characters is not
        "the X-Orinyx-Signup-Secret header carries the shared secret",
    ):
        assert real_looking_keys(line) == [], line


def test_a_signup_hook_secret_in_any_case_with_a_value_is_real_looking():
    body = SYNTHETIC_BODY
    for line in (
        f"signup_hook_secret={body}",
        f'signup_hook_secret = "{body}"',
        f"export signup_hook_secret='{body}'",
        f"Signup_Hook_Secret: {body}",
        f"signup_hook_secret={body[:16]}",  # 16 characters is enough
    ):
        assert real_looking_keys(line), line
    for line in (
        "signup_hook_secret=$SIGNUP_HOOK_SECRET",
        'signup_hook_secret = os.environ["SIGNUP_HOOK_SECRET"]',
        "signup_hook_secret: str | None = None",
        "signup_hook_secret=<the shared secret>",
        f"signup_hook_secret={body[:15]}",  # 15 characters is not
    ):
        assert real_looking_keys(line) == [], line


def test_a_key_prefix_in_any_case_is_real_looking():
    body = SYNTHETIC_BODY
    for prefix in ("ork_LIVE_", "ORK_LIVE_", "Ork_Live_", "ork_Test_", "ORK_OAT_", "ork_ORT_"):
        assert real_looking_keys(f"key: {prefix}{body}"), prefix
    for line in (
        "a key (`ORK_LIVE_...`)",
        "<your ORK_LIVE_ key>",
        f"ORK_LIVE_{body[:15]}",  # 15 characters is not
        f"WORK_LIVE_{body}",  # not a prefix: no word boundary before it
    ):
        assert real_looking_keys(line) == [], line


def test_a_key_prefix_of_six_or_more_letters_is_real_looking():
    """The letters between `ork_` and the next `_` may be any number from two up, so a
    longer prefix than the four in use today (ork_signup_, ork_session_) is caught too."""
    body = SYNTHETIC_BODY
    for letters in ("signup", "session", "refresh", "abcdefghijklmnop", "SESSION"):
        assert real_looking_keys(f"ork_{letters}_{body}"), letters
    for line in (
        "a sign-up key (`ork_signup_...`)",
        f"ork_signup_{body[:15]}",  # 15 characters is not
        f"work_session_{body}",  # not a prefix: no word boundary before it
    ):
        assert real_looking_keys(line) == [], line


def test_the_key_scan_masks_each_new_kind_of_hit(tmp_path):
    body = SYNTHETIC_BODY
    lines = [
        f"X-Orinyx-Signup-Secret: {body}",
        f"signup_hook_secret={body}",
        f"ORK_LIVE_{body}",
        f"ork_session_{body}",
    ]
    (tmp_path / "pasted.txt").write_text("\n".join(lines) + "\n")
    hits = key_scan(tmp_path, _walk_files(tmp_path))
    assert hits == [
        f"pasted.txt:1: X-Orinyx... ({len(lines[0])} chars)",
        f"pasted.txt:2: signup_h... ({len(lines[1])} chars)",
        f"pasted.txt:3: ORK_LIVE... ({len(lines[2])} chars)",
        f"pasted.txt:4: ork_sess... ({len(lines[3])} chars)",
    ]
    assert "Synth" not in "\n".join(hits)


def test_a_file_the_key_scan_cannot_read_fails_the_scan_by_name(tmp_path, monkeypatch):
    """An unreadable file is reported (path and error type, nothing else) rather than passed
    as clean or allowed to stop the scan: the files after it are still scanned."""
    planted = "ork_live_" + "PLANTED" + "w4Rk" * 6
    (tmp_path / "a_clean.txt").write_text("nothing here\n")
    (tmp_path / "b_locked.env").write_text("unreadable in this test\n")
    (tmp_path / "c_key.env").write_text(f"ORINYX_API_KEY={planted}\n")
    read_text = Path.read_text

    def refusing_one(self, *args, **kwargs):
        if self.name == "b_locked.env":
            raise PermissionError(13, "Permission denied")
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", refusing_one)
    files = sorted(_walk_files(tmp_path))
    hits = key_scan(tmp_path, files)
    assert hits[0] == "b_locked.env: could not be read (PermissionError)"
    assert [hit.split(":")[0] for hit in hits[1:]] == ["c_key.env", "c_key.env"]
    with pytest.raises(AssertionError) as failure:
        assert_no_real_looking_key(tmp_path, files)
    assert "b_locked.env: could not be read (PermissionError)" in str(failure.value)
    assert "Permission denied" not in str(failure.value)


def test_a_file_without_read_permission_fails_the_key_scan(tmp_path):
    """The same over the operating system's own refusal, where it refuses (not as root)."""
    locked = tmp_path / "locked.env"
    locked.write_text("unreadable\n")
    locked.chmod(0)
    try:
        try:
            locked.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("this user can read a file with no permissions")
        assert key_scan(tmp_path, [locked]) == ["locked.env: could not be read (PermissionError)"]
    finally:
        locked.chmod(0o600)


def test_a_file_under_a_directory_without_search_permission_fails_the_key_scan(tmp_path):
    """A listed file whose directory cannot be searched is not known to be clean: it fails the
    scan by name, the same on every Python, and the files after it are still scanned. (Python
    3.12's is_file() raises here and 3.14's answers False, so neither may decide.)"""
    planted = "ork_live_" + "PLANTED" + "w4Rk" * 6
    locked = tmp_path / "b_locked"
    locked.mkdir()
    hidden = locked / "settings.env"
    hidden.write_text("unreadable in this test\n")
    (tmp_path / "c_key.env").write_text(f"ORINYX_API_KEY={planted}\n")
    files = [tmp_path / "a_missing.env", hidden, tmp_path / "c_key.env"]
    locked.chmod(0)
    try:
        try:
            hidden.stat()
        except PermissionError:
            pass
        else:
            pytest.skip("this user can search a directory with no permissions")
        hits = key_scan(tmp_path, files)
        with pytest.raises(AssertionError) as failure:
            assert_no_real_looking_key(tmp_path, files)
    finally:
        locked.chmod(0o700)
    assert hits[0] == "b_locked/settings.env: could not be read (PermissionError)"
    assert [hit.split(":")[0] for hit in hits[1:]] == ["c_key.env", "c_key.env"]
    assert "b_locked/settings.env: could not be read (PermissionError)" in str(failure.value)
    assert "Permission denied" not in str(failure.value) and "PLANTED" not in str(failure.value)


def test_a_listed_path_that_is_not_a_file_is_still_skipped_by_the_key_scan(tmp_path):
    """What the scan skipped before it asked by stat() it still skips: a listed path that is
    gone (a deleted tracked file), a dangling symlink, and a directory are nothing to read."""
    (tmp_path / "a_dir").mkdir()
    (tmp_path / "b_dangling.env").symlink_to(tmp_path / "nowhere.env")
    files = [tmp_path / "a_dir", tmp_path / "b_dangling.env", tmp_path / "c_deleted.env"]
    assert key_scan(tmp_path, files) == []

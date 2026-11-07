"""`scripts/e2e_install_check.py` fails on any difference from the release's expected sets.

The comparison is tested with fakes; a few tests start a real stdio server (this package's
own, and small stand-ins written to `tmp_path`) to show the whole script end to end. No test
uses a real key or a real network service: the only server the script talks to is a stub on
127.0.0.1.
"""

import importlib.util
import json
import re
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "e2e_install_check", ROOT / "scripts" / "e2e_install_check.py"
)
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)

TOOLS = {"alpha", "beta"}
PROMPTS = {"choose"}


def observed(**changes) -> "e2e.Observed":
    base = {
        "server_name": "orinyx",
        "tools": set(TOOLS),
        "prompts": set(PROMPTS),
        "outputs": ["{}"],
        "stderr": "",
        "requests": [],
    }
    return e2e.Observed(**{**base, **changes})


def test_matching_sets_pass():
    assert e2e.evaluate(observed(), TOOLS, PROMPTS) == []


@pytest.mark.parametrize(
    "changes, expected_text",
    [
        ({"tools": TOOLS | {"extra"}}, "unexpected ['extra']"),
        ({"tools": TOOLS - {"beta"}}, "missing ['beta']"),
        ({"prompts": {"other"}}, "prompts differ: missing ['choose'], unexpected ['other']"),
        ({"prompts": set()}, "prompts differ: missing ['choose']"),
        ({"server_name": "someone-else"}, "server name is 'someone-else'"),
        ({"requests": ["GET /v1/anything"]}, "the server called the API: ['GET /v1/anything']"),
        ({"outputs": ["x " + e2e.SYNTHETIC_KEY]}, "the synthetic key appears"),
        ({"stderr": "boot " + e2e.SYNTHETIC_KEY}, "the synthetic key appears"),
    ],
)
def test_each_difference_is_one_failure(changes, expected_text):
    failures = e2e.evaluate(observed(**changes), TOOLS, PROMPTS)
    assert len(failures) == 1
    assert expected_text in failures[0]


def expected_file(tmp_path, tools=TOOLS, prompts=PROMPTS) -> Path:
    path = tmp_path / "expected.json"
    path.write_text(json.dumps({"tools": sorted(tools), "prompts": sorted(prompts)}))
    return path


def fake_collect(monkeypatch, result, record_request=None):
    async def collect(server, server_args, api):
        if record_request:
            e2e.Stub.seen.append(record_request)
        return result

    monkeypatch.setattr(e2e, "collect", collect)


def run_main(tmp_path, capsys):
    code = e2e.main(["--server", "x", "--expected", str(expected_file(tmp_path))])
    return code, capsys.readouterr().out


def test_main_exits_zero_on_a_match(tmp_path, capsys, monkeypatch):
    fake_collect(monkeypatch, observed())
    code, out = run_main(tmp_path, capsys)
    assert (code, out) == (0, "e2e install check: ok\n")


@pytest.mark.parametrize(
    "result, request_line",
    [
        (observed(tools=TOOLS | {"extra"}), None),
        (observed(tools={"alpha"}), None),
        (observed(prompts={"changed"}), None),
        (observed(), "GET /v1/health"),
    ],
    ids=["extra tool", "missing tool", "changed prompt", "one stub request"],
)
def test_main_exits_one_with_a_fail_line(tmp_path, capsys, monkeypatch, result, request_line):
    fake_collect(monkeypatch, result, request_line)
    code, out = run_main(tmp_path, capsys)
    assert code == 1
    assert out.splitlines()[0].startswith("FAIL: ")
    assert out.splitlines()[-1] == "e2e install check: FAIL"


def test_main_fails_when_the_server_cannot_complete_the_handshake(tmp_path, capsys, monkeypatch):
    async def collect(server, server_args, api):
        raise OSError("no such file")

    monkeypatch.setattr(e2e, "collect", collect)
    code, out = run_main(tmp_path, capsys)
    assert code == 1
    assert "FAIL: the server did not complete the handshake (OSError)" in out


def test_main_fails_on_an_unreadable_expected_file(tmp_path, capsys):
    assert e2e.main(["--server", "x", "--expected", str(tmp_path / "missing.json")]) == 1
    assert "FAIL: expected sets cannot be read" in capsys.readouterr().out


def test_the_script_holds_no_literal_key_shaped_string():
    text = (ROOT / "scripts" / "e2e_install_check.py").read_text()
    assert "ork_live_" not in text.replace('"ork_" + "live_"', "")
    assert e2e.SYNTHETIC_KEY.startswith("ork_live_")


def test_no_flag_takes_a_credential():
    text = (ROOT / "scripts" / "e2e_install_check.py").read_text()
    flags = [line for line in text.splitlines() if "add_argument(" in line or '"--' in line]
    assert not any("key" in line.lower() or "token" in line.lower() for line in flags)


# The committed expected sets, against the server this tree registers. `__version__` trails the
# release being prepared until release day, so these read the newest committed file. A tool
# added after that file was written fails here, and a new release gets a new file.


def release_order(path: Path) -> tuple:
    """Sorts `0.1.5rc1.json` before `0.1.5.json`, and both before `0.1.6.json`."""
    numbers, pre = re.fullmatch(r"([0-9.]+)((?:a|b|rc)[0-9]+)?", path.stem).groups()
    return tuple(int(part) for part in numbers.split(".")), pre is None, pre or ""


def newest_expected() -> Path:
    """The expected-sets file of the highest version under release/expected/."""
    return max((ROOT / "release" / "expected").glob("*.json"), key=release_order)


def test_a_final_version_sorts_after_its_pre_releases():
    names = ["0.1.6rc1", "0.1.5", "0.1.5rc1", "0.1.5b2", "0.1.10"]
    ordered = sorted((Path(f"{name}.json") for name in names), key=release_order)
    assert [path.stem for path in ordered] == ["0.1.5b2", "0.1.5rc1", "0.1.5", "0.1.6rc1", "0.1.10"]


def test_the_expected_sets_for_this_version_equal_what_the_server_registers(monkeypatch):
    from orinyx_mcp.server import build_server

    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    server = build_server(lambda: None)
    tools = {tool.name for tool in server._tool_manager.list_tools()}
    prompts = {prompt.name for prompt in server._prompt_manager.list_prompts()}
    expected_tools, expected_prompts = e2e.load_expected(newest_expected())
    assert tools == expected_tools
    assert prompts == expected_prompts


# Whole-script runs against a real stdio server.

STAND_IN = textwrap.dedent(
    """\
    import json, os, sys, urllib.request
    from mcp.server.mcpserver import MCPServer

    MODE = sys.argv[1] if len(sys.argv) > 1 else "clean"
    if MODE == "calls-the-api":
        try:
            urllib.request.urlopen(os.environ["ORINYX_API_URL"] + "/v1/startup", timeout=5)
        except Exception:
            pass
    instructions = "hello"
    if MODE == "echoes-the-key":
        instructions = "key is " + os.environ["ORINYX_API_KEY"]
    if MODE == "reports-environment":
        instructions = json.dumps(sorted(os.environ))
    if MODE == "key-on-stderr":
        print(os.environ["ORINYX_API_KEY"], file=sys.stderr)
    server = MCPServer("orinyx", instructions=instructions)

    @server.tool()
    def alpha() -> str:
        return "a"

    @server.tool()
    def beta() -> str:
        return "b"

    @server.prompt()
    def choose() -> str:
        return "c"

    server.run()
    """
)


def run_stand_in(tmp_path, capsys, mode, monkeypatch):
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN)
    monkeypatch.setenv("ORINYX_API_KEY", "an-unrelated-value-in-the-parent-environment")
    code = e2e.main(
        [
            "--server",
            sys.executable,
            "--server-arg",
            str(script),
            "--server-arg",
            mode,
            "--expected",
            str(expected_file(tmp_path)),
        ]
    )
    return code, capsys.readouterr().out


def test_a_clean_stand_in_server_passes(tmp_path, capsys, monkeypatch):
    code, out = run_stand_in(tmp_path, capsys, "clean", monkeypatch)
    assert (code, out) == (0, "e2e install check: ok\n")


def test_a_server_that_calls_the_api_at_start_up_fails(tmp_path, capsys, monkeypatch):
    code, out = run_stand_in(tmp_path, capsys, "calls-the-api", monkeypatch)
    assert code == 1
    assert "FAIL: the server called the API: ['GET /v1/startup']" in out


def test_a_server_that_echoes_the_key_fails(tmp_path, capsys, monkeypatch):
    code, out = run_stand_in(tmp_path, capsys, "echoes-the-key", monkeypatch)
    assert code == 1
    assert "the synthetic key appears" in out
    assert e2e.SYNTHETIC_KEY not in out


def test_a_server_that_writes_the_key_to_stderr_fails(tmp_path, capsys, monkeypatch):
    code, out = run_stand_in(tmp_path, capsys, "key-on-stderr", monkeypatch)
    assert code == 1
    assert "the synthetic key appears" in out
    assert e2e.SYNTHETIC_KEY not in out


def test_the_server_sees_only_path_and_the_two_settings(tmp_path, capsys, monkeypatch):
    seen = {}

    async def collect(server, server_args, api):
        result = await real_collect(server, server_args, api)
        seen["names"] = set(json.loads(json.loads(result.outputs[0])["instructions"]))
        return result

    real_collect = e2e.collect
    monkeypatch.setattr(e2e, "collect", collect)
    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    monkeypatch.setenv("HOME", "/nowhere")
    run_stand_in(tmp_path, capsys, "reports-environment", monkeypatch)
    # Python itself may add locale variables on some systems.
    names = seen["names"] - {"LC_CTYPE", "__CF_USER_TEXT_ENCODING"}
    assert names == {"PATH", "ORINYX_API_URL", "ORINYX_API_KEY"}


def package_run(tmp_path, monkeypatch, *server_args) -> int:
    monkeypatch.chdir(ROOT)  # `python -m orinyx_mcp` imports this tree, not another install
    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    path = newest_expected()
    return e2e.main(["--server", sys.executable, *server_args, "--expected", str(path)])


def test_the_package_answers_over_python_dash_m(tmp_path, monkeypatch, capsys):
    code = package_run(tmp_path, monkeypatch, "--server-arg=-m", "--server-arg=orinyx_mcp")
    assert (code, capsys.readouterr().out) == (0, "e2e install check: ok\n")


def test_the_package_answers_over_the_stdio_command(tmp_path, monkeypatch, capsys):
    script = tmp_path / "orinyx_mcp_command.py"
    # Written the way pip writes the installed `orinyx-mcp` script, but importing this tree.
    script.write_text(
        f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
        "import re\nfrom orinyx_mcp.http import serve\n"
        "if __name__ == '__main__':\n"
        "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
        "    sys.exit(serve())\n"
    )
    code = package_run(tmp_path, monkeypatch, "--server-arg", str(script), "--server-arg", "stdio")
    assert (code, capsys.readouterr().out) == (0, "e2e install check: ok\n")


def test_the_expected_sets_catch_a_tool_the_release_does_not_list(tmp_path, monkeypatch, capsys):
    path = tmp_path / "short.json"
    expected = json.loads(newest_expected().read_text())
    expected["tools"].remove("finish_exam")
    path.write_text(json.dumps(expected))
    monkeypatch.chdir(ROOT)
    code = e2e.main(
        [
            "--server",
            sys.executable,
            "--server-arg=-m",
            "--server-arg=orinyx_mcp",
            "--expected",
            str(path),
        ]
    )
    assert code == 1
    assert "unexpected ['finish_exam']" in capsys.readouterr().out


def test_a_server_that_never_answers_fails_within_the_timeout(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    started = time.monotonic()
    code = e2e.main(
        [
            "--server",
            sys.executable,
            "--server-arg=-c",
            "--server-arg=import time; time.sleep(120)",
            "--expected",
            str(expected_file(tmp_path)),
            "--timeout",
            "1.5",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL: the server did not complete the handshake within 1.5 seconds" in out
    assert out.endswith("e2e install check: FAIL\n")
    assert time.monotonic() - started < 30


def test_the_timeout_defaults_to_sixty_seconds(monkeypatch, tmp_path):
    seen = {}

    async def collect(server, server_args, api):
        return observed()

    real_wait_for = e2e.asyncio.wait_for

    async def wait_for(awaitable, timeout):
        seen["timeout"] = timeout
        return await real_wait_for(awaitable, timeout)

    monkeypatch.setattr(e2e, "collect", collect)
    monkeypatch.setattr(e2e.asyncio, "wait_for", wait_for)
    assert e2e.main(["--server", "x", "--expected", str(expected_file(tmp_path))]) == 0
    assert seen["timeout"] == 60

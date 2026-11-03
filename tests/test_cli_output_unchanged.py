"""Value-free usage errors changed only the errors that quoted a value. Everything else the
`orinyx` CLI prints is pinned here, byte for byte, to what it printed before that change:
the help text of the top level and of each subcommand, the normal outputs of every command,
the errors that are not usage errors, the usage errors that never quoted a value, and every
exit code.

`tests/fixtures/cli_output_before.json` was captured by running `capture()` below against
the package as it stood at commit 7fa8f7e, before value-free usage errors and the clean
plain-http error landed, on Python 3.14 and 3.12 (both gave the same bytes). The API is an
httpx.MockTransport answering with the synthetic run in tests/test_text.py; nothing is sent.
A file path in an output is written as `<work>`, the case's own temporary directory.

Two entries were changed by hand since, when those errors stopped repeating a value: "a run
id that is not a UUID" no longer quotes the run id, and "observe a file of the wrong kind"
names the path by its position. Every other entry is as captured."""

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import httpx
import pytest
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxClient

from tests.test_text import ACCURACY, RUN

FIXTURE = Path(__file__).parent / "fixtures" / "cli_output_before.json"
API_URL = "https://api.orinyx.example"
# A synthetic key, assembled so no source line holds a key-shaped literal.
KEY = "ork_live_" + "UNCHANGED" + "x9Qm" * 6
RUN_ID = RUN["runId"]
CLAIMS = [{"rawText": "warfarin 20 mg daily", "drug": "warfarin", "claimType": "dose_range"}]
# One order in a record answers with a run that has no flag and no abstention: exit 0.
CLEAN_RUN = {
    **RUN,
    "verdicts": RUN["verdicts"][1:2],
    "aggregate": {"total": 1, "supported": 1, "contradicted": 0, "abstain": 0},
}
# A run with no flag and one abstention: not verified, exit 3.
ABSTAINED_RUN_ID = "5b0c2d4e-6f70-4a81-9b23-c4d5e6f70819"
ABSTAINED_RUN = {
    **RUN,
    "runId": ABSTAINED_RUN_ID,
    "verdicts": RUN["verdicts"][2:3],
    "aggregate": {"total": 1, "supported": 0, "contradicted": 0, "abstain": 1},
}


def _api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/accuracy"):
        return httpx.Response(200, json={**ACCURACY, "runId": RUN_ID})
    if path.endswith(".csv"):
        return httpx.Response(
            200,
            content=b"claim,verdict\nwarfarin 20 mg daily,contradicted\n",
            headers={
                "content-type": "text/csv",
                "content-disposition": 'attachment; filename="run.csv"',
            },
        )
    if path.endswith(".pdf"):
        return httpx.Response(
            200, content=b"%PDF-1.4 synthetic\n", headers={"content-type": "application/pdf"}
        )
    if path.endswith(ABSTAINED_RUN_ID):
        return httpx.Response(200, json=ABSTAINED_RUN)
    if path == "/v1/verifications/orders":
        orders = json.loads(request.content)["orders"]
        return httpx.Response(200, json=CLEAN_RUN if len(orders) == 1 else RUN)
    return httpx.Response(200, json=RUN)


def _factory(url: str, key: str) -> OrinyxClient:
    return OrinyxClient(url, key, transport=httpx.MockTransport(_api))


def _workspace(work: Path) -> None:
    (work / "claims.json").write_text(json.dumps(CLAIMS))
    agent = work / "agent"
    agent.mkdir()
    (agent / "one.txt").write_text("warfarin 5 mg by mouth daily\n")
    (agent / "two.jsonl").write_text(
        json.dumps({"orders": ["warfarin 5 mg daily", "metformin 500 mg twice daily"]})
        + "\n"
        + json.dumps({"note": "no orders here"})
        + "\n"
    )
    (work / "bad.jsonl").write_text("{not json\n")


ENV = {"ORINYX_API_URL": API_URL, "ORINYX_API_KEY": KEY}


def cases(work: Path) -> dict[str, tuple[list[str], dict[str, str]]]:
    """Each case: (argv, the ORINYX_* environment)."""
    w = str(work)
    claims, out = f"{w}/claims.json", f"{w}/out.file"
    return {
        # help
        "--help": (["--help"], ENV),
        "-h": (["-h"], ENV),
        "verify --help": (["verify", "--help"], ENV),
        "get --help": (["get", "--help"], ENV),
        "accuracy --help": (["accuracy", "--help"], ENV),
        "export --help": (["export", "--help"], ENV),
        "observe --help": (["observe", "--help"], ENV),
        "-h glued to a value": (["-h" + KEY], ENV),
        # normal outputs
        "verify": (["verify", "--file", claims], ENV),
        "verify --json": (["verify", "--file", claims, "--json"], ENV),
        "verify --tool --tool-version --check-interactions": (
            ["verify", "--file", claims, "--tool", "t", "--tool-version", "1"]
            + ["--check-interactions"],
            ENV,
        ),
        "get": (["get", RUN_ID], ENV),
        "get --json": (["get", RUN_ID, "--json"], ENV),
        "get a run that is not verified": (["get", ABSTAINED_RUN_ID], ENV),
        "accuracy": (["accuracy", RUN_ID], ENV),
        "accuracy --json": (["accuracy", RUN_ID, "--json"], ENV),
        "export csv": (["export", RUN_ID, "--out", out], ENV),
        "export pdf": (["export", RUN_ID, "--format", "pdf", "--out", out], ENV),
        "export report": (["export", RUN_ID, "--format=report", "--out", out], ENV),
        "observe a clean .txt": (["observe", f"{w}/agent/one.txt"], ENV),
        "observe a .jsonl with a skipped record": (["observe", f"{w}/agent/two.jsonl"], ENV),
        "observe a directory --json": (["observe", f"{w}/agent", "--json"], ENV),
        # errors that are not usage errors
        "no environment": (["get", RUN_ID], {}),
        "no key": (["get", RUN_ID], {"ORINYX_API_URL": API_URL}),
        "a run id that is not a UUID": (["get", "not-a-uuid"], ENV),
        "a missing --file": (["verify", "--file", f"{w}/missing.json"], ENV),
        "observe a bad JSON line": (["observe", f"{w}/bad.jsonl"], ENV),
        "observe a file of the wrong kind": (["observe", f"{w}/x.csv"], ENV),
        # usage errors that never quoted a value
        "no command": ([], ENV),
        "verify without --file": (["verify"], ENV),
        "--file without its value": (["verify", "--file"], ENV),
        "--file followed by a flag": (["verify", "--file", "--json"], ENV),
        "observe without paths": (["observe"], ENV),
        "get without a run id": (["get"], ENV),
        "export without --out": (["export", RUN_ID], ENV),
        "an ambiguous option without a value": (["verify", "--file", "f", "--to"], ENV),
        "one unknown option": (["get", RUN_ID, "--bogus"], ENV),
        "two unknown options": (["get", RUN_ID, "--bogus", "--other"], ENV),
        "an unknown short option": (["get", RUN_ID, "-x"], ENV),
    }


@contextlib.contextmanager
def _environment(env: dict[str, str]):
    """The case's ORINYX_* variables, an 80-column terminal and no colour."""
    with mock.patch.dict(os.environ, {"COLUMNS": "80", "LINES": "24", "NO_COLOR": "1"}):
        for name in ("ORINYX_API_URL", "ORINYX_API_KEY", "FORCE_COLOR", "PYTHON_COLORS"):
            os.environ.pop(name, None)
        os.environ.update(env)
        yield


def capture(name: str, work: Path) -> dict:
    """Run one case in a fresh directory: {exit, out, err}, with `<work>` for its path."""
    _workspace(work)
    argv, env = cases(work)[name]
    out, err = io.StringIO(), io.StringIO()
    with _environment(env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv, client_factory=_factory)
        except SystemExit as exc:
            code = exc.code
    return {
        "exit": code,
        "out": out.getvalue().replace(str(work), "<work>"),
        "err": err.getvalue().replace(str(work), "<work>"),
    }


def capture_all() -> dict[str, dict]:
    results = {}
    for name in cases(Path("unused")):
        with tempfile.TemporaryDirectory() as work:
            results[name] = capture(name, Path(work))
    return results


BEFORE: dict[str, dict] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_the_fixture_holds_every_case_and_only_those():
    assert sorted(BEFORE) == sorted(cases(Path("unused")))


@pytest.mark.parametrize("name", sorted(cases(Path("unused"))))
def test_the_output_is_byte_identical_to_before(name, tmp_path):
    assert capture(name, tmp_path) == BEFORE[name]


def test_the_pinned_outputs_cover_help_normal_runs_and_every_exit_code():
    """The fixture is not hollow: each help text is there, the runs printed something, and
    the exits are the contract's 0 clean, 1 error, 2 flagged, 3 not verified."""
    for name in ("--help", "verify --help", "get --help", "export --help", "observe --help"):
        assert BEFORE[name]["out"].startswith("usage: orinyx"), name
        assert BEFORE[name]["exit"] == 0, name
    assert BEFORE["-h glued to a value"] == BEFORE["-h"]
    for name in ("verify", "get", "accuracy", "export csv", "observe a clean .txt"):
        assert BEFORE[name]["out"].strip() and BEFORE[name]["err"] == "", name
    assert {case["exit"] for case in BEFORE.values()} == {0, 1, 2, 3}
    usage_errors = [name for name, case in BEFORE.items() if "error:" in case["err"]]
    assert len(usage_errors) == 11
    assert all(BEFORE[name]["exit"] == cli.EXIT_ERROR for name in usage_errors)
    assert KEY not in json.dumps(BEFORE)

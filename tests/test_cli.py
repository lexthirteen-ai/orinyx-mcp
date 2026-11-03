"""The `orinyx` CLI: a thin wrapper over OrinyxClient for frameworks that do
not speak MCP. Credentials come from the environment only; exit code 2 means flagged, 3 not
verified, 0 clean, 1 error, so a LangChain / CrewAI / AutoGen tool can branch on it."""

import json

import pytest
from orinyx_mcp import cli

from tests.test_text import RUN
from tests.test_tools import FakeClient

CLAIMS = [
    {
        "rawText": "warfarin 20 mg daily",
        "drug": "warfarin",
        "claimType": "dose_range",
        "structuredValue": {"dose": 20, "unit": "mg"},
    }
]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", "https://orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "ork_live_test")


def test_verify_prints_text_and_exits_2_when_flagged(env, tmp_path, capsys):
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(CLAIMS))
    fake = FakeClient()
    code = cli.main(
        ["verify", "--file", str(path), "--tool", "acme-scribe", "--tool-version", "1.4.2"],
        client_factory=lambda url, key: fake,
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "[MODERATE] warfarin 20 mg daily" in out
    assert fake.calls[0][2]["tool_name"] == "acme-scribe"


def test_verify_json_output(env, tmp_path, capsys):
    path = tmp_path / "claims.json"
    path.write_text(json.dumps({"assertions": CLAIMS}))  # a full request body works too
    code = cli.main(
        ["verify", "--file", str(path), "--json"], client_factory=lambda u, k: FakeClient()
    )
    body = json.loads(capsys.readouterr().out)
    assert code == 2 and body["runId"] == RUN["runId"]


def test_clean_run_exits_0(env, tmp_path, capsys):
    from orinyx_mcp.client import VerificationResult

    class Clean(FakeClient):
        def verify(self, claims, **kwargs):
            clean = {
                **RUN,
                "verdicts": RUN["verdicts"][1:2],
                "aggregate": {"total": 1, "supported": 1, "contradicted": 0, "abstain": 0},
            }
            return VerificationResult.from_json(clean)

    path = tmp_path / "claims.json"
    path.write_text(json.dumps(CLAIMS))
    assert cli.main(["verify", "--file", str(path)], client_factory=lambda u, k: Clean()) == 0


def test_all_abstain_run_exits_3_not_clean(env, tmp_path, capsys):
    """No flag is not the same as verified: an abstain means the label did not settle it."""
    from orinyx_mcp.client import VerificationResult

    class Unsettled(FakeClient):
        def verify(self, claims, **kwargs):
            run = {
                **RUN,
                "verdicts": RUN["verdicts"][2:],
                "aggregate": {"total": 1, "supported": 0, "contradicted": 0, "abstain": 1},
            }
            return VerificationResult.from_json(run)

    path = tmp_path / "claims.json"
    path.write_text(json.dumps(CLAIMS))
    code = cli.main(["verify", "--file", str(path)], client_factory=lambda u, k: Unsettled())
    assert code == cli.EXIT_NOT_VERIFIED == 3


def test_usage_errors_never_exit_with_the_flagged_code(env, capsys):
    """argparse exits 2 on a usage error; 2 means "flagged" here, so usage errors exit 1."""
    for argv in (["verify"], ["export", "x", "--format", "html", "--out", "f"], ["nope"]):
        with pytest.raises(SystemExit) as excinfo:
            cli.main(argv, client_factory=lambda u, k: FakeClient())
        assert excinfo.value.code == 1, argv


def test_get_and_accuracy_commands(env, capsys):
    assert cli.main(["get", RUN["runId"]], client_factory=lambda u, k: FakeClient()) == 2
    assert "Checked 3 claims" in capsys.readouterr().out
    assert cli.main(["accuracy", RUN["runId"]], client_factory=lambda u, k: FakeClient()) == 0
    assert "ACCURACY (physician review)" in capsys.readouterr().out


def test_export_writes_the_file(env, tmp_path, capsys):
    out = tmp_path / "report.pdf"
    code = cli.main(
        ["export", RUN["runId"], "--format", "report", "--out", str(out)],
        client_factory=lambda u, k: FakeClient(),
    )
    assert code == 0 and out.read_bytes() == b"data"
    assert str(out) in capsys.readouterr().out


def test_missing_credentials_exit_1(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("ORINYX_API_URL", raising=False)
    monkeypatch.delenv("ORINYX_API_KEY", raising=False)
    path = tmp_path / "claims.json"
    path.write_text(json.dumps(CLAIMS))
    assert cli.main(["verify", "--file", str(path)]) == 1
    assert "ORINYX_API_KEY" in capsys.readouterr().err


def test_api_errors_exit_1_with_the_message(env, capsys):
    from orinyx_mcp.client import OrinyxApiError

    class Broken(FakeClient):
        def get_run(self, run_id):
            raise OrinyxApiError(404, "not_found", "Verification run x not found.")

    assert cli.main(["get", "x"], client_factory=lambda u, k: Broken()) == 1
    assert "not found" in capsys.readouterr().err


# --- observe: read an agent's saved output and check every order in it --------------------


def _run(**aggregate):
    """A run whose verdict rows match the given aggregate counts."""
    counts = {"total": 1, "supported": 0, "contradicted": 0, "abstain": 0, **aggregate}
    rows = [
        {**RUN["verdicts"][0], "verdict": verdict}
        for verdict in ("supported", "contradicted", "abstain", "unreadable")
        for _ in range(counts.get(verdict, 0))
    ]
    return {**RUN, "aggregate": counts, "verdicts": rows}


CLEAN = _run(supported=1)
ABSTAINED = _run(abstain=1)


class Recorder(FakeClient):
    """Returns the queued runs in order (the flagged RUN once the queue is empty)."""

    def __init__(self, *runs):
        super().__init__()
        self.runs = list(runs)

    def verify_orders(self, orders, **kwargs):
        from orinyx_mcp.client import VerificationResult

        self.calls.append(("verify_orders", orders, kwargs))
        return VerificationResult.from_json(self.runs.pop(0) if self.runs else RUN)


def _observe(argv, client):
    return cli.main(["observe", *argv], client_factory=lambda u, k: client)


def _jsonl(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_observe_txt_sends_each_line_as_an_order(env, tmp_path, capsys):
    path = tmp_path / "turn.txt"
    path.write_text("warfarin 20 mg by mouth daily\n\n  lisinopril 10 mg daily  \n")
    fake = Recorder()
    code = _observe([str(path), "--tool", "acme-scribe", "--tool-version", "1.4.2"], fake)
    assert code == cli.EXIT_FLAGGED
    assert fake.calls == [
        (
            "verify_orders",
            ["warfarin 20 mg by mouth daily", "lisinopril 10 mg daily"],
            {"tool_name": "acme-scribe", "tool_version": "1.4.2", "check_interactions": False},
        )
    ]
    out = capsys.readouterr().out
    assert f"turn.txt#0  run {RUN['runId']}" in out


def test_observe_jsonl_one_run_per_record_with_a_dotted_field(env, tmp_path, capsys):
    path = _jsonl(
        tmp_path / "trace.jsonl",
        [
            {"output": {"orders": ["warfarin 5 mg daily", "aspirin 81 mg daily"]}},
            {"output": {"orders": "metformin 500 mg twice daily\nlisinopril 10 mg daily"}},
        ],
    )
    fake = Recorder(CLEAN, CLEAN)
    code = _observe([str(path), "--field", "output.orders", "--check-interactions"], fake)
    assert code == cli.EXIT_CLEAN
    assert [call[1] for call in fake.calls] == [
        ["warfarin 5 mg daily", "aspirin 81 mg daily"],
        ["metformin 500 mg twice daily", "lisinopril 10 mg daily"],
    ]
    assert all(call[2]["check_interactions"] for call in fake.calls)


def test_observe_directory_reads_supported_files_in_order(env, tmp_path, capsys):
    (tmp_path / "b.txt").write_text("warfarin 5 mg daily\n")
    _jsonl(tmp_path / "a.jsonl", [{"orders": ["aspirin 81 mg daily"]}])
    (tmp_path / "c.json").write_text(json.dumps([{"orders": ["metformin 500 mg daily"]}]))
    (tmp_path / "notes.md").write_text("not read")
    fake = Recorder(CLEAN, CLEAN, CLEAN)
    assert _observe([str(tmp_path)], fake) == cli.EXIT_CLEAN
    assert [call[1] for call in fake.calls] == [
        ["aspirin 81 mg daily"],
        ["warfarin 5 mg daily"],
        ["metformin 500 mg daily"],
    ]


def test_observe_names_records_without_the_field(env, tmp_path, capsys):
    path = _jsonl(tmp_path / "t.jsonl", [{"text": "no orders here"}, {"orders": ["x 1 mg"]}])
    fake = Recorder(CLEAN)
    assert _observe([str(path)], fake) == cli.EXIT_CLEAN
    assert len(fake.calls) == 1
    out = capsys.readouterr().out
    assert "Skipped 1 record without 'orders': t.jsonl#0" in out


def test_observe_screen_hit_refuses_everything_and_never_repeats_the_text(env, tmp_path, capsys):
    _jsonl(tmp_path / "a.jsonl", [{"orders": ["warfarin 5 mg daily"]}])
    _jsonl(tmp_path / "b.jsonl", [{"orders": ["aspirin 81 mg daily", "call 555-123-4567"]}])
    fake = Recorder()
    assert _observe([str(tmp_path)], fake) == cli.EXIT_ERROR
    assert fake.calls == []
    err = capsys.readouterr().err
    assert "b.jsonl#0" in err and "phone" in err
    assert "555-123-4567" not in err


def test_observe_refuses_records_over_the_api_limits(env, tmp_path, capsys):
    too_many = _jsonl(tmp_path / "many.jsonl", [{"orders": ["x 1 mg"] * 51}])
    too_long = _jsonl(tmp_path / "long.jsonl", [{"orders": ["x" * 501]}])
    for path, words in ((too_many, "51 orders"), (too_long, "500 characters")):
        fake = Recorder()
        assert _observe([str(path)], fake) == cli.EXIT_ERROR
        assert fake.calls == []
        assert words in capsys.readouterr().err


def test_observe_exit_is_the_worst_run(env, tmp_path, capsys):
    path = _jsonl(tmp_path / "t.jsonl", [{"orders": ["a 1 mg"]}, {"orders": ["b 1 mg"]}])
    assert _observe([str(path)], Recorder(RUN, CLEAN)) == cli.EXIT_FLAGGED
    assert _observe([str(path)], Recorder(CLEAN, ABSTAINED)) == cli.EXIT_NOT_VERIFIED
    assert _observe([str(path)], Recorder(CLEAN, CLEAN)) == cli.EXIT_CLEAN


def test_observe_with_nothing_to_check_is_an_error(env, tmp_path, capsys):
    path = _jsonl(tmp_path / "t.jsonl", [{"text": "no orders"}])
    fake = Recorder()
    assert _observe([str(path)], fake) == cli.EXIT_ERROR
    assert fake.calls == []
    assert "no orders" in capsys.readouterr().err.lower()


def test_observe_json_output(env, tmp_path, capsys):
    path = _jsonl(tmp_path / "t.jsonl", [{"orders": ["a 1 mg"]}, {"note": "none"}])
    assert _observe([str(path), "--json"], Recorder(CLEAN)) == cli.EXIT_CLEAN
    body = json.loads(capsys.readouterr().out)
    assert body["skipped"] == ["t.jsonl#1"]
    assert [(r["source"], r["runId"]) for r in body["runs"]] == [("t.jsonl#0", RUN["runId"])]
    assert body["runs"][0]["raw"]["aggregate"] == CLEAN["aggregate"]


def test_observe_api_error_keeps_the_runs_already_made(env, tmp_path, capsys):
    from orinyx_mcp.client import OrinyxApiError

    class FailsSecond(Recorder):
        def verify_orders(self, orders, **kwargs):
            if self.calls:
                raise OrinyxApiError(503, "unavailable", "Engine unavailable.")
            return super().verify_orders(orders, **kwargs)

    path = _jsonl(tmp_path / "t.jsonl", [{"orders": ["a 1 mg"]}, {"orders": ["b 1 mg"]}])
    assert _observe([str(path)], FailsSecond(CLEAN)) == cli.EXIT_ERROR
    captured = capsys.readouterr()
    assert f"t.jsonl#0  run {RUN['runId']}" in captured.out
    assert "t.jsonl#1" in captured.err and "Engine unavailable." in captured.err


def test_observe_unreadable_input_is_an_error(env, tmp_path, capsys):
    bad = tmp_path / "t.jsonl"
    bad.write_text("{not json\n")
    assert _observe([str(bad)], Recorder()) == cli.EXIT_ERROR
    assert "t.jsonl" in capsys.readouterr().err

"""Untrusted summaries and new engine verdicts cannot become a clean run."""

import json
from copy import deepcopy

import pytest
from orinyx_mcp import cli
from orinyx_mcp.client import VerificationResult
from orinyx_mcp.text import render_run_table, render_run_text

from tests.test_text import RUN


def run(verdict="supported", **aggregate):
    data = deepcopy(RUN)
    data["verdicts"] = [{**data["verdicts"][0], "verdict": verdict}]
    data["aggregate"] = {
        "total": 1,
        "contradicted": 0,
        "unreadable": 0,
        "supported": int(verdict == "supported"),
        "abstain": int(verdict not in ("supported", "contradicted", "unreadable")),
        **aggregate,
    }
    return data


class Client:
    def __init__(self, *runs):
        self.runs = iter(runs)

    def verify(self, *args, **kwargs):
        return VerificationResult.from_json(next(self.runs))

    verify_orders = verify


@pytest.mark.parametrize("command", ["verify", "observe"])
@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    "data,code,field",
    [
        (run("contradicted", supported=0), cli.EXIT_ERROR, "flagged"),
        (run(supported=0), cli.EXIT_ERROR, "supported"),
        (run(total=0), cli.EXIT_ERROR, "total"),
        (run("future_verdict"), cli.EXIT_NOT_VERIFIED, None),
        (run("future_verdict", abstain=0), cli.EXIT_ERROR, "not_verified"),
    ],
)
def test_cli_rows_determine_exit(
    command, as_json, data, code, field, tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("ORINYX_API_URL", "https://orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "ork_live_secret_sentinel")
    path = tmp_path / "synthetic.json"
    path.write_text(
        json.dumps([{}] if command == "verify" else {"orders": ["warfarin 5 mg daily"]})
    )
    args = ["verify", "--file", str(path)] if command == "verify" else ["observe", str(path)]
    if as_json:
        args.append("--json")
    assert cli.main(args, client_factory=lambda u, k: Client(data)) == code
    captured = capsys.readouterr()
    assert "ork_live_secret_sentinel" not in captured.err
    if field:
        assert "aggregate/verdict rows disagree" in captured.err
        assert field in captured.err
    if as_json:
        body = json.loads(captured.out)
        assert (body if command == "verify" else body["runs"][0]["raw"]) == data
    elif "future_verdict" == data["verdicts"][0]["verdict"]:
        assert "NOT VERIFIED" in captured.out and "future_verdict" in captured.out


@pytest.mark.parametrize("render", [render_run_text, render_run_table])
@pytest.mark.parametrize(
    "verdict", ["future_verdict", "", "SUPPORTED", "future|value\nsecond line"]
)
def test_unknown_is_visible_and_counted(render, verdict):
    text = render(run(verdict))
    assert "NOT VERIFIED" in text
    assert "Unknown verdict" in text
    assert (
        repr(verdict).replace("|", "\\|") in text
        if render is render_run_table
        else repr(verdict) in text
    )
    assert "0 supported, 1 abstained" in text


@pytest.mark.parametrize("render", [render_run_text, render_run_table])
def test_inconsistent_run_is_not_verified(render):
    text = render(run(supported=0))
    assert "NOT VERIFIED: aggregate/verdict rows disagree: supported" in text
    assert "1 supported" in text


def test_observe_error_outranks_flag_and_unknown(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ORINYX_API_URL", "https://orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "synthetic")
    path = tmp_path / "orders.json"
    path.write_text(json.dumps([{"orders": ["warfarin 5 mg daily"]}] * 3))
    client = Client(run("contradicted", contradicted=1), run("future_verdict"), run(supported=0))
    assert cli.main(["observe", str(path)], client_factory=lambda u, k: client) == cli.EXIT_ERROR
    assert "NOT VERIFIED" in capsys.readouterr().out

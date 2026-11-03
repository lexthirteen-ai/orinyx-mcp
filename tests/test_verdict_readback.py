"""Retrieving a stored run must preserve the CLI safety contract too.

The verdict-consistency tests cover verify/observe with a fake client; these cover get via the real
HTTP client, including its optional accuracy request and unmodified JSON output.
"""

import json
from copy import deepcopy

import httpx
import pytest
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.text import render_run_text

from tests.test_text import RUN


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize(
    "verdict,aggregate,exit_code,text_shows",
    [
        ("supported", "supported", cli.EXIT_CLEAN, "SUPPORTED (1)"),
        ("contradicted", "contradicted", cli.EXIT_FLAGGED, "FLAGS (1)\n1. [MODERATE]"),
        ("unreadable", "unreadable", cli.EXIT_FLAGGED, "UNREADABLE AS WRITTEN (1)"),
        ("abstain", "abstain", cli.EXIT_NOT_VERIFIED, "ABSTAINED (1) - NOT VERIFIED"),
        (
            "future_verdict",
            "abstain",
            cli.EXIT_NOT_VERIFIED,
            "Unknown verdict 'future_verdict'; NOT VERIFIED.",
        ),
        (
            "contradicted",
            "supported",
            cli.EXIT_ERROR,
            "NOT VERIFIED: aggregate/verdict rows disagree",
        ),
    ],
)
def test_get_checks_real_response_rows_before_returning_success(
    verdict, aggregate, exit_code, text_shows, as_json, monkeypatch, capsys
):
    data = deepcopy(RUN)
    data["verdicts"] = [{**data["verdicts"][0], "verdict": verdict}]
    data["aggregate"] = {
        "total": 1,
        "supported": 0,
        "contradicted": 0,
        "abstain": 0,
        "unreadable": 0,
    }
    data["aggregate"][aggregate] = 1
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/accuracy"):
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "No review"}}
            )
        assert request.url.path == f"/v1/verifications/{data['runId']}"
        return httpx.Response(200, json=data)

    monkeypatch.setenv("ORINYX_API_URL", "https://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "synthetic-readback-key")
    args = ["get", data["runId"], *(["--json"] if as_json else [])]
    code = cli.main(
        args,
        client_factory=lambda url, key: OrinyxClient(
            url, key, transport=httpx.MockTransport(respond)
        ),
    )
    assert code == exit_code
    output = capsys.readouterr()
    assert len(calls) == (1 if as_json else 2)
    if as_json:
        assert json.loads(output.out) == data
    else:
        # The stored run is rendered as the run view (no review on file), and each row shows
        # the block its verdict belongs in.
        assert output.out == render_run_text(data, None) + "\n"
        assert text_shows in output.out
    if exit_code == cli.EXIT_ERROR:
        assert "aggregate/verdict rows disagree" in output.err
    assert "synthetic-readback-key" not in output.out + output.err

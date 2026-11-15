"""A lone surrogate in text from the API is shown as its escape, and the report still prints.

JSON can spell half of a surrogate pair on its own (a backslash, `u` and `d800`). Decoded, that
is a character no terminal can be sent: written to standard output as UTF-8 it raised an encoding
error, so `orinyx get` printed no report at all and exited 1 instead of 2. Like every other
character that is not printable, it is now shown as its backslash escape, the report prints in
both forms, and the exit code is the run's own. `--json` already escaped it and is unchanged.
"""

import json

import httpx
import pytest
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.text import render_run_table, render_run_text

RUN_ID = "4f7a2c1e-9b3d-4e8a-8c51-2a6d0e9f3b17"
LONE = chr(0xD800)
SHOWN = chr(92) + "ud800"  # the six characters a reader sees in its place


def _run(raw_text: str, explanation: str) -> dict:
    return {
        "runId": RUN_ID,
        "verdicts": [
            {
                "rawText": raw_text,
                "drug": "warfarin",
                "claimType": "dose_range",
                "verdict": "contradicted",
                "severity": "major",
                "explanation": explanation,
                "severityReason": "Rated Major by the fixed rule for dose claims.",
                "citation": {
                    "source": "openFDA",
                    "section": "Dosage and Administration",
                    "sourceId": "abc-123",
                    "citation": "Coumadin prescribing information",
                    "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123",
                },
            }
        ],
        "aggregate": {"total": 1, "supported": 0, "contradicted": 1, "abstain": 0, "unreadable": 0},
    }


CLEAN = _run("warfarin 20 mg daily", "Dose 20 mg exceeds the stated maximum of 10 mg.")
HOSTILE = _run("warfarin 20 mg" + LONE + " daily", "Dose 20 mg" + LONE + " exceeds the maximum.")


def _surrogates(text: str) -> list[str]:
    return [f"U+{ord(ch):04X}" for ch in text if 0xD800 <= ord(ch) <= 0xDFFF]


@pytest.mark.parametrize("render", [render_run_text, render_run_table])
def test_a_lone_surrogate_is_shown_as_its_escape_in_both_forms(render):
    text = render(HOSTILE, None)
    assert _surrogates(text) == []
    assert text.encode("utf-8")  # a terminal can be sent every character
    assert "warfarin 20 mg" + SHOWN + " daily" in text
    assert len(text.split("\n")) == len(render(CLEAN, None).split("\n"))


def _get(args, run, monkeypatch, capsys):
    # Sent as JSON with ASCII escapes, which is how a lone surrogate travels.
    body = json.dumps(run).encode("ascii")

    def respond(request):
        if request.url.path.endswith("/accuracy"):
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "none"}})
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})

    monkeypatch.setenv("ORINYX_API_URL", "https://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "synthetic-display-key")
    code = cli.main(
        ["get", RUN_ID, *args],
        client_factory=lambda url, key: OrinyxClient(
            url, key, transport=httpx.MockTransport(respond)
        ),
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_get_prints_the_report_and_exits_flagged(monkeypatch, capsys):
    code, out, err = _get([], HOSTILE, monkeypatch, capsys)
    assert (code, err) == (cli.EXIT_FLAGGED, "")
    assert _surrogates(out) == []
    assert "warfarin 20 mg" + SHOWN + " daily" in out
    assert out == render_run_text(HOSTILE, None) + "\n"


def test_json_output_keeps_the_escape_the_api_sent(monkeypatch, capsys):
    code, out, _ = _get(["--json"], HOSTILE, monkeypatch, capsys)
    assert code == cli.EXIT_FLAGGED
    assert json.loads(out) == HOSTILE
    assert _surrogates(out) == []

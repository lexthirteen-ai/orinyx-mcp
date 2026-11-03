"""The four exam reads now check the answer's shape. What they print for an answer of the
right shape is pinned here, byte for byte, to what they printed before that check landed.

`tests/fixtures/exam_text_before.json` was captured by running `capture_all()` below against
the package as it stood at commit dce33c9, before the shape checks. Each case is called twice
over the real OrinyxClient with an httpx.MockTransport answering one synthetic engine body
(nothing is sent): the tool function directly, whose text is pinned, and the same tool through
the in-memory MCP server, whose result must not be an error and must carry that same text.

The bodies cover each read's shape edges (a done answer with `case` null and with no `case`
key, an empty case list, a report whose verdict is null) and each exam kind the renderers
handle (claims, reply/advice, coding). Several reuse the synthetic constants of
tests/test_exam_tools.py, so a change there shows up here as a changed pin.
"""

import copy
import json
from pathlib import Path

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxClient

from tests.test_exam_tools import (
    ADVICE_REPORT,
    CASE,
    CODING_CASE,
    CODING_REPORT,
    REPLY_CASE,
    REPORT,
    TRAJECTORY,
)

FIXTURE = Path(__file__).parent / "fixtures" / "exam_text_before.json"
API_URL = "https://api.orinyx.example"

# Bodies with every key the engine sends, null where it sends null.
FULL_CASE = {
    "caseId": "amb-003",
    "vignette": "Clinician: continue warfarin 5 mg.",
    "patientContext": {"age": 70, "sex": "F"},
    "kind": "claims",
    "dateOfService": None,
}
FULL_CASE_NO_CONTEXT = FULL_CASE | {"caseId": "amb-004", "patientContext": None}
FULL_CODING_CASE = {
    "caseId": "cod-001",
    "vignette": "Follow-up for type 2 diabetes.",
    "patientContext": None,
    "kind": "coding",
    "dateOfService": "2026-03-14",
}
FULL_REPLY_CASE = REPLY_CASE | {"dateOfService": None}
CASE_SET_PIN = {"id": "ambient-core", "version": "1.0.0", "contentHash": "sha256:abc"}
FINISHED_RUN = {
    "id": 12,
    "vendorId": 3,
    "verificationRunId": "00000000-0000-4000-8000-000000000012",
    "vignetteSet": "ambient-core",
    "status": "completed",
    "totalClaims": 5,
    "supported": 3,
    "contradicted": 1,
    "abstained": 1,
    "majorContradictions": 0,
    "published": False,
    "completedAt": "2026-10-04T23:10:00Z",
    "caseSetId": "ambient-core",
    "caseSetVersion": "1.0.0",
    "caseSetContentHash": "sha256:abc",
    "verdict": "fail",
    "priorRunId": None,
    "allowPartial": False,
    "metrics": None,
    "metricsScoringVersion": None,
    "kbScopeFingerprint": None,
    "appVersion": None,
}
FULL_REPORT = REPORT | {
    "kind": "claims",
    "scoringContract": "claims",
    "caseSet": REPORT["caseSet"] | {"contentHash": "sha256:abc", "thresholds": {}},
    "allowPartial": False,
    "scoringVersion": 3,
    "kbScopeFingerprint": None,
    "appVersion": None,
    "completedAt": "2026-10-04T23:10:00Z",
    "trajectory": TRAJECTORY,
    "faultProbes": [],
}
MINIMAL_REPORT = {
    "runId": 12,
    "caseSet": {"id": "s", "version": "1", "clinicallyReviewed": False},
    "verdict": "pass",
    "metrics": {},
    "speed": {},
    "cases": [],
}

# name -> (tool, extra arguments, route suffix, the API's 200 body)
CASES: dict[str, tuple[str, dict, str, dict]] = {
    "next/claims": ("get_next_exam_case", {}, "next-case", {"remaining": 2, "case": CASE}),
    "next/one-remaining": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 12, "remaining": 1, "case": FULL_CASE},
    ),
    "next/no-patient-context": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 12, "remaining": 3, "case": FULL_CASE_NO_CONTEXT},
    ),
    "next/reply": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 21, "remaining": 1, "case": FULL_REPLY_CASE},
    ),
    "next/coding": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 31, "remaining": 3, "case": FULL_CODING_CASE},
    ),
    "next/coding-with-context": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 31, "remaining": 3, "case": CODING_CASE},
    ),
    "next/done-case-null": (
        "get_next_exam_case",
        {},
        "next-case",
        {"runId": 12, "remaining": 0, "case": None},
    ),
    "next/done-no-case-key": ("get_next_exam_case", {}, "next-case", {"runId": 12, "remaining": 0}),
    "cases/claims": (
        "get_exam_cases",
        {},
        "cases",
        {"runId": 12, "caseSet": CASE_SET_PIN, "cases": [FULL_CASE, FULL_CASE_NO_CONTEXT]},
    ),
    "cases/claims-short": ("get_exam_cases", {}, "cases", {"runId": 12, "cases": [CASE]}),
    "cases/reply": (
        "get_exam_cases",
        {},
        "cases",
        {"runId": 21, "caseSet": CASE_SET_PIN, "cases": [FULL_REPLY_CASE]},
    ),
    "cases/coding": (
        "get_exam_cases",
        {},
        "cases",
        {"runId": 31, "caseSet": CASE_SET_PIN, "cases": [FULL_CODING_CASE, CODING_CASE]},
    ),
    "cases/mixed-claims-and-reply": (
        "get_exam_cases",
        {},
        "cases",
        {"runId": 12, "caseSet": CASE_SET_PIN, "cases": [FULL_CASE, FULL_REPLY_CASE]},
    ),
    "cases/empty-list": (
        "get_exam_cases",
        {},
        "cases",
        {"runId": 12, "caseSet": CASE_SET_PIN, "cases": []},
    ),
    "finish/full": ("finish_exam", {}, "complete", FINISHED_RUN),
    "finish/partial-advisory": (
        "finish_exam",
        {"allow_partial": True},
        "complete",
        FINISHED_RUN | {"allowPartial": True, "verdict": "advisory"},
    ),
    "finish/short": (
        "finish_exam",
        {},
        "complete",
        {"id": 12, "status": "completed", "verdict": "fail"},
    ),
    "report/claims": ("get_exam_report", {}, "report", REPORT),
    "report/claims-full-with-trajectory": ("get_exam_report", {}, "report", FULL_REPORT),
    "report/claims-signed": (
        "get_exam_report",
        {},
        "report",
        REPORT | {"caseSet": REPORT["caseSet"] | {"clinicallyReviewed": True}},
    ),
    "report/claims-partial-catch-unscored": (
        "get_exam_report",
        {},
        "report",
        REPORT
        | {
            "allowPartial": True,
            "metrics": REPORT["metrics"] | {"catch_rate": None, "unscored_seeded_errors": 2},
        },
    ),
    "report/claims-verdict-null": ("get_exam_report", {}, "report", REPORT | {"verdict": None}),
    "report/claims-advisory": (
        "get_exam_report",
        {},
        "report",
        REPORT | {"verdict": "advisory", "reasons": []},
    ),
    "report/unknown-scoring-contract": (
        "get_exam_report",
        {},
        "report",
        REPORT | {"scoringContract": "unknown-kind"},
    ),
    "report/minimal": ("get_exam_report", {}, "report", MINIMAL_REPORT),
    "report/advice": ("get_exam_report", {}, "report", ADVICE_REPORT),
    "report/coding": ("get_exam_report", {}, "report", CODING_REPORT),
    "report/coding-with-trajectory": (
        "get_exam_report",
        {},
        "report",
        CODING_REPORT | {"trajectory": TRAJECTORY},
    ),
}


def _client(suffix: str, body: dict) -> OrinyxClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/benchmark-runs/12/{suffix}", request.url.path
        return httpx.Response(200, json=copy.deepcopy(body))

    return OrinyxClient(API_URL, "k", transport=httpx.MockTransport(handler))


async def capture(name: str) -> dict:
    """One case: the tool's text when called directly, whether the MCP call is an error, and
    whether the MCP caller reads the same text."""
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    tool, kwargs, suffix, body = CASES[name]
    with _client(suffix, body) as client:
        direct = getattr(tools, tool)(client, run_id=12, **kwargs)
    client = _client(suffix, body)
    try:
        async with Client(build_server(shared(client)), mode="legacy") as mcp_client:
            result = await mcp_client.call_tool(tool, {"run_id": 12, **kwargs})
    finally:
        client.close()
    text = "\n".join(getattr(part, "text", "") for part in result.content)
    return {
        "text": direct,
        "mcp_is_error": bool(result.is_error),
        "mcp_text_is_the_same": text == direct,
    }


async def capture_all() -> dict[str, dict]:
    return {name: await capture(name) for name in CASES}


BEFORE: dict[str, dict] = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def test_the_fixture_holds_every_case_and_only_those():
    assert sorted(BEFORE) == sorted(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_exam_text_is_byte_identical_to_before(name):
    assert await capture(name) == BEFORE[name]


def test_the_pinned_texts_are_successes_and_cover_each_edge_and_kind():
    """The fixture is not hollow: every pin is a success with text, and the edges and kinds
    the cases are named for are in it."""
    for name, pinned in BEFORE.items():
        assert pinned["mcp_is_error"] is False, name
        assert pinned["mcp_text_is_the_same"] is True, name
        assert pinned["text"].strip(), name
    done = "Run 12: every case has been answered. Call finish_exam, then get_exam_report."
    assert BEFORE["next/done-case-null"]["text"] == done
    assert BEFORE["next/done-no-case-key"]["text"] == done
    assert BEFORE["next/one-remaining"]["text"].startswith("Case amb-003\n")
    assert "1 case remaining, this one included." in BEFORE["next/one-remaining"]["text"]
    assert BEFORE["cases/empty-list"]["text"].startswith("Run 12: 0 cases. ")
    assert BEFORE["cases/coding"]["text"].startswith("Run 12: 2 cases. ")
    assert BEFORE["finish/short"]["text"] == (
        "Run 12 is finished and scored. Call get_exam_report(run_id=12)."
    )
    verdict_null = BEFORE["report/claims-verdict-null"]["text"]
    assert "\nResult (REHEARSAL - not evidence): NONE - " in verdict_null
    assert "\nResult: FAIL - " in BEFORE["report/claims-signed"]["text"]
    for name, heading in (
        ("report/claims", "\nACCURACY\n"),
        ("report/advice", "\nCASES\n"),
        ("report/coding", " answered with no codes.\n"),
    ):
        assert heading in BEFORE[name]["text"], name

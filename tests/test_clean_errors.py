"""Clean errors: what this file proves, and what it pins as a known failure.

Proven, over the real OrinyxClient with an httpx.MockTransport standing in for the API (no
network):

- the six API refusals (401, 403, 404, 422, 429, 503) on every tool `build_server` registers
  by default: each is a tool ERROR RESULT whose text carries the refusal's code, status and
  message, except the refusals a tool answers in words by design (ANSWERED_IN_WORDS);
- start_a_test's exact answers: a refused credential (401) is answered with one fixed text and
  nothing else, and its menus (tester, product account with and without open exams, both
  surfaces refused, full account) are pinned byte for byte;
- a transport failure, a non-JSON error page and a non-JSON answer on every default tool: a
  tool error carrying its reason;
- a malformed answer (a well-formed JSON object of the wrong shape) on every default tool: a
  tool error carrying `invalid_response`, and on the four exam tools never the success
  sentence they reported before their client calls checked the shape
  (WRONG_SHAPE_SUCCESS_TEXT; tests/test_exam_shape.py drives near-miss shapes too);
- the six refusals on every `orinyx` CLI command (verify, get, accuracy, export, observe, with
  and without --json): exit code 1 (the error code of the exit-code contract: 0 clean, 1
  error, 2 flagged, 3 not verified) with the refusal's message on stderr;
- a transport failure, a non-JSON error page, a non-JSON answer and a wrong-shape answer on
  those commands but export: exit code 1 with a non-empty `orinyx:` message on stderr (the
  failure's reason itself for the first two) and no traceback; export is driven with a
  transport failure and a non-JSON answer: exit code 1, no traceback, no file written;
- a plain-http ORINYX_API_URL on the CLI and the stdio entry point: a readable message on
  stderr and exit code 1, not a traceback, and the key is not in it.

No known failure is pinned here.
"""

import json
from collections.abc import Callable

import httpx
import pytest
from orinyx_mcp import cli
from orinyx_mcp.client import OrinyxClient

from tests.test_text import RUN

API_URL = "https://api.orinyx.example"
# A synthetic key. tests/test_config_safety.py checks that it never appears in any output.
SENTINEL_KEY = "ork_live_" + "SENTINEL" + "q7Zx" * 8
# The key's distinctive body: a leak of the key without its prefix is a leak too.
SENTINEL_BODY = SENTINEL_KEY.removeprefix("ork_live_")
RUN_ID = RUN["runId"]

# One error envelope per refusal the API gives. Messages are synthetic.
REFUSALS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "The API key is not valid or has been revoked."),
    403: ("forbidden", "This key does not carry the scope this route needs."),
    404: ("not_found", "No verification run with that id."),
    422: ("validation_error", "assertions: at least one claim is required."),
    429: ("rate_limited", "Too many requests from this key; retry in 30 seconds."),
    503: ("unavailable", "The verification engine is temporarily unavailable."),
}
STATUSES = sorted(REFUSALS)

Handler = Callable[[httpx.Request], httpx.Response]


def refusing(status: int) -> Handler:
    """An API that answers every request with this refusal's error envelope."""
    code, message = REFUSALS[status]

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"error": {"code": code, "message": message, "details": []}}
        return httpx.Response(status, json=body)

    return handler


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _html_gateway_page(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        502, text="<html>Bad gateway</html>", headers={"content-type": "text/html"}
    )


def _not_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})


def _wrong_shape(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"unexpected": True})


# Failures that are not a refusal: (handler, the readable reason the caller must see).
FAILURES: dict[str, tuple[Handler, str]] = {
    "transport_error": (_unreachable, "connection refused"),
    "non_json_error_page": (_html_gateway_page, "Bad gateway"),
    "not_json": (_not_json, "invalid_response"),
    "wrong_shape": (_wrong_shape, "invalid_response"),
}


def api_client(handler: Handler, key: str = SENTINEL_KEY) -> OrinyxClient:
    return OrinyxClient(API_URL, key, transport=httpx.MockTransport(handler))


def assert_no_traceback(text: str) -> None:
    assert "Traceback" not in text, text
    assert 'File "' not in text, text


# --- MCP tool path ---------------------------------------------------------------------------

# Every tool `build_server` registers by default, with arguments that pass local validation,
# so the call reaches the API and meets its refusal.
TOOL_CALLS: dict[str, dict] = {
    "verify_medications": {
        "claims": [
            {
                "rawText": "warfarin 5 mg daily",
                "drug": "warfarin",
                "claimType": "dose_range",
                "structuredValue": {"dose": 5, "unit": "mg"},
            }
        ]
    },
    "verify_order_text": {"orders": ["warfarin 5 mg by mouth daily"]},
    "get_verification": {"run_id": RUN_ID},
    "get_accuracy": {"run_id": RUN_ID},
    "export_verification": {"run_id": RUN_ID, "fmt": "csv"},
    "find_otc_monographs": {"ingredient": "acetaminophen"},
    "get_otc_monograph": {"monograph_id": "M013"},
    "read_otc_monograph_section": {"document_id": 1},
    "find_fda_label": {"drug": "warfarin"},
    "read_fda_label_section": {"set_id": "abc-123", "section": "warnings"},
    "start_a_test": {},
    "get_next_exam_case": {"run_id": 12},
    "get_exam_cases": {"run_id": 12},
    "submit_exam_answers": {"run_id": 12, "answers": [{"caseId": "case-1", "claims": []}]},
    "finish_exam": {"run_id": 12},
    "get_exam_report": {"run_id": 12},
}

# start_a_test's whole answer when the API refuses the credential itself (401). Written out
# here rather than imported, so a change to the wording fails this file.
CREDENTIAL_REFUSED_TEXT = (
    "Orinyx refused this key or sign-in (401), so no test can run yet. If you use an API key, "
    "check that ORINYX_API_KEY holds the whole ork_live_ key you were issued. On the hosted "
    "connector, sign in again. If it is still refused, the key may have been revoked: ask the "
    "Orinyx operator for a new one. Do not answer in Orinyx's place: say the check could not "
    "be run."
)

# Refusals a tool answers in words by design, as a normal result (today's contract):
# find_fda_label reports a name the knowledge base does not hold; start_a_test treats a 403
# as "this account cannot use that surface" and lists what it can do, and a 401 as the
# credential itself refused.
ANSWERED_IN_WORDS: dict[tuple[str, int], str] = {
    ("find_fda_label", 404): "is not in the knowledge base",
    ("start_a_test", 401): CREDENTIAL_REFUSED_TEXT,
    ("start_a_test", 403): "Not available to a product account",
}


async def call_tools(handler: Handler, names: list[str]) -> dict[str, tuple[bool, str]]:
    """Call each tool through an in-memory MCP client: {name: (is_error, text)}."""
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    client = api_client(handler)
    results: dict[str, tuple[bool, str]] = {}
    try:
        async with Client(build_server(shared(client)), mode="legacy") as mcp_client:
            listed = {tool.name for tool in (await mcp_client.list_tools()).tools}
            assert set(names) <= listed, sorted(set(names) - listed)
            for name in names:
                result = await mcp_client.call_tool(name, TOOL_CALLS[name])
                text = "\n".join(getattr(part, "text", "") for part in result.content)
                results[name] = (bool(result.is_error), text)
    finally:
        client.close()
    return results


async def test_every_default_tool_is_covered_here():
    """A tool added to the server without a row in TOOL_CALLS fails this test."""
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server, shared

    server = build_server(shared(api_client(refusing(503))))
    registered = {tool.name for tool in server._tool_manager.list_tools()}
    assert registered == set(TOOL_CALLS)


@pytest.mark.parametrize("status", STATUSES)
async def test_an_api_refusal_reaches_the_mcp_caller_as_a_readable_tool_error(status):
    code, message = REFUSALS[status]
    names = [name for name in TOOL_CALLS if name != "start_a_test"]  # covered below
    results = await call_tools(refusing(status), names)
    problems = []
    for name, (is_error, text) in results.items():
        if (name, status) in ANSWERED_IN_WORDS:
            if is_error or ANSWERED_IN_WORDS[(name, status)] not in text:
                problems.append(f"{name}: expected the worded answer, got {text!r}")
        elif not is_error:
            problems.append(f"{name}: not an error result: {text[:200]!r}")
        elif f"{code} ({status}): {message}" not in text:
            problems.append(f"{name}: the reason is missing: {text!r}")
        if "Traceback" in text or 'File "' in text:
            problems.append(f"{name}: traceback in the answer: {text!r}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("status", STATUSES)
async def test_start_a_test_passes_a_refusal_on_with_its_reason(status):
    code, message = REFUSALS[status]
    is_error, text = (await call_tools(refusing(status), ["start_a_test"]))["start_a_test"]
    assert_no_traceback(text)
    if ("start_a_test", status) in ANSWERED_IN_WORDS:
        assert not is_error and ANSWERED_IN_WORDS[("start_a_test", status)] in text
    else:
        assert is_error, text
        assert f"{code} ({status}): {message}" in text
    if status == 401:
        assert text == CREDENTIAL_REFUSED_TEXT


# --- start_a_test, byte for byte ---------------------------------------------------------------

# start_a_test asks up to three routes: the verification list (can this credential check
# claims?), the open exam list (is this a product account, and what is open?) and, for a
# credential that can check claims, the monograph list (may it read label and monograph text?).


def by_route(verifications: Handler, exams: Handler) -> Handler:
    """An API that answers start_a_test's reads separately. The lookup read is always admitted
    here; tests/test_lookup_offer.py drives it refused and failing."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/verifications":
            return verifications(request)
        if request.url.path == "/v1/benchmark-runs":
            return exams(request)
        if request.url.path == "/v1/monographs":
            return _no_runs(request)
        raise AssertionError(f"start_a_test asked an unexpected route: {request.url.path}")

    return handler


def _no_runs(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"data": []})


def _open_exams(request: httpx.Request) -> httpx.Response:
    runs = [
        {
            "id": 12,
            "caseSetId": "ambient-core",
            "caseSetVersion": "1.0.0",
            "casesTotal": 10,
            "casesAnswered": 4,
        },
        {
            "id": 14,
            "caseSetId": "icd10cm-outpatient-core",
            "caseSetVersion": "1.0.0",
            "kind": "coding",
        },
    ]
    return httpx.Response(200, json={"data": runs})


# The menu's paragraphs as they read today. Launch copy quotes this text, so any change to a
# line, its order or its spacing must fail here.
MENU_QUICK_CHECK_TESTER = (
    '  Use verify_order_text with the orders exactly as written ("warfarin 5 mg by mouth '
    'daily"): Orinyx splits each into its dose, route and frequency itself. Use '
    "verify_medications only when you already hold structured claims. Each claim comes back "
    "supported, flagged (with severity, reason and the FDA citation), unreadable as written "
    "(do not act on it) or not verified. The run reports how long Orinyx took."
)
MENU_QUICK_CHECK_PRODUCT = (
    "  Not available to a product account: a product sitting an exam cannot also check claims "
    "with the grader. Sign in with a tester account for this. Do not answer the question "
    "yourself in Orinyx's place: say the check could not be run."
)
MENU_EXAM_NEEDS_PRODUCT = [
    "  This needs a product account. The Orinyx operator registers the product, opens an exam "
    "for it and gives you a product sign-in. Ask the operator to set one up."
]
MENU_EXAM_NONE_OPEN = [
    "  No exam is open for this account. Ask the Orinyx operator to open one for your product."
]
MENU_EXAM_OPEN = [
    "  Open: run 12 on ambient-core 1.0.0 (4 of 10 answered; this exam takes claims).",
    "  Open: run 14 on icd10cm-outpatient-core 1.0.0 (open; this exam takes ICD-10-CM codes).",
    "  To sit one:",
    "  1. get_next_exam_case(run_id=12): one case; Orinyx starts the clock.",
    "  2. submit_exam_answers: your claims for that case. Orinyx records the answer and does "
    "not show you how it judged it.",
    "  3. Repeat until no case remains, then finish_exam.",
    "  4. get_exam_report: catch rate, false flags and speed.",
    "  The report gives the catch rate with its denominator and your speed per case. Each "
    "product gets one credible attempt per test-set version.",
]
MENU_LOOKUP_TESTER = (
    "  Prescribing labels: find_fda_label with a drug name, then read_fda_label_section. OTC "
    "monographs: find_otc_monographs, then get_otc_monograph and read_otc_monograph_section. "
    "Reference text, not a verdict."
)
MENU_LOOKUP_PRODUCT = "  Not available to a product account."


def menu(quick_check: str, exam: list[str], lookup: str) -> str:
    return "\n".join(
        [
            "What kind of test do you want to run with Orinyx?",
            "",
            "QUICK CHECK - you have medication claims and want each one checked.",
            quick_check,
            "",
            "SCORED EXAM - score an AI product on a fixed test set. A transcript exam scores the "
            "medication-label errors its notes carry (a catch rate); a patient-message exam "
            "scores how its replies handle planted situations; a coding exam scores its "
            "ICD-10-CM codes against a coder's key. Every report adds speed.",
            *exam,
            "",
            "LOOK SOMETHING UP - read FDA prescribing-label or over-the-counter monograph text.",
            lookup,
            "",
            "Send synthetic test data only, never patient records.",
            "Orinyx flags; the clinician decides.",
        ]
    )


# (verification list, open exam list) -> the whole menu.
START_A_TEST_MENUS: dict[str, tuple[Handler, Handler, str]] = {
    "both-refused-403": (
        refusing(403),
        refusing(403),
        menu(MENU_QUICK_CHECK_PRODUCT, MENU_EXAM_NEEDS_PRODUCT, MENU_LOOKUP_PRODUCT),
    ),
    "tester": (
        _no_runs,
        refusing(403),
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_NEEDS_PRODUCT, MENU_LOOKUP_TESTER),
    ),
    "product-with-open-exams": (
        refusing(403),
        _open_exams,
        menu(MENU_QUICK_CHECK_PRODUCT, MENU_EXAM_OPEN, MENU_LOOKUP_PRODUCT),
    ),
    "product-nothing-open": (
        refusing(403),
        _no_runs,
        menu(MENU_QUICK_CHECK_PRODUCT, MENU_EXAM_NONE_OPEN, MENU_LOOKUP_PRODUCT),
    ),
    "full-account": (
        _no_runs,
        _open_exams,
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_OPEN, MENU_LOOKUP_TESTER),
    ),
}


@pytest.mark.parametrize("account", sorted(START_A_TEST_MENUS))
async def test_start_a_test_menus_read_exactly_as_before(account):
    verifications, exams, expected = START_A_TEST_MENUS[account]
    is_error, text = (await call_tools(by_route(verifications, exams), ["start_a_test"]))[
        "start_a_test"
    ]
    assert not is_error, text
    assert text == expected


# A credential refused on the exam list read is refused, whatever the verification read said:
# the API refuses a credential on every route alike, so the menu would mislead.
CREDENTIAL_REFUSED_ON_EXAMS: dict[str, Handler] = {
    "verifications-ok": _no_runs,
    "verifications-403": refusing(403),
    "verifications-401": refusing(401),
}


@pytest.mark.parametrize("verifications", sorted(CREDENTIAL_REFUSED_ON_EXAMS))
async def test_start_a_test_answers_a_refused_credential_with_that_text_alone(verifications):
    handler = by_route(CREDENTIAL_REFUSED_ON_EXAMS[verifications], refusing(401))
    is_error, text = (await call_tools(handler, ["start_a_test"]))["start_a_test"]
    assert not is_error, text
    assert text == CREDENTIAL_REFUSED_TEXT


# Exam list failures start_a_test does not answer in words: (handler, the reason to carry).
EXAM_LIST_FAILURES: dict[str, tuple[Handler, str]] = {
    str(status): (refusing(status), f"{code} ({status}): {message}")
    for status, (code, message) in REFUSALS.items()
    if status not in (401, 403)
}
EXAM_LIST_FAILURES["transport_error"] = (_unreachable, "connection refused")


@pytest.mark.parametrize("failure", sorted(EXAM_LIST_FAILURES))
async def test_start_a_test_passes_other_exam_list_failures_on_as_errors(failure):
    """Only 401 and 403 on the exam list are answered in words; the rest stay tool errors."""
    exams, reason = EXAM_LIST_FAILURES[failure]
    is_error, text = (await call_tools(by_route(_no_runs, exams), ["start_a_test"]))["start_a_test"]
    assert is_error, text
    assert reason in text
    assert CREDENTIAL_REFUSED_TEXT not in text
    assert_no_traceback(text)


# The success sentence each exam tool rendered from a wrong-shape answer while its client call
# checked only that the answer was a JSON object. None may appear in what a malformed answer
# now gives. Each fragment is exactly what the tool renders when the shape check is bypassed
# (tests/test_exam_shape.py proves it), so its absence here is not vacuous.
WRONG_SHAPE_SUCCESS_TEXT: dict[str, str] = {
    "get_next_exam_case": "every case has been answered",
    "get_exam_cases": "Run 12: 0 cases",
    "finish_exam": "is finished and scored",
    "get_exam_report": "Result (REHEARSAL - not evidence): NONE",
}


@pytest.mark.parametrize(
    ("failure", "name"),
    [
        pytest.param(failure, name, id=f"{failure}-{name}")
        for failure in sorted(FAILURES)
        for name in TOOL_CALLS
    ],
)
async def test_a_transport_failure_or_bad_answer_is_a_readable_tool_error(failure, name):
    handler, reason = FAILURES[failure]
    is_error, text = (await call_tools(handler, [name]))[name]
    assert is_error, (name, text)
    assert reason in text, (name, text)
    if name in WRONG_SHAPE_SUCCESS_TEXT:
        assert WRONG_SHAPE_SUCCESS_TEXT[name] not in text, (name, text)
    assert_no_traceback(text)


# --- CLI path --------------------------------------------------------------------------------

CLAIMS = TOOL_CALLS["verify_medications"]["claims"]


def cli_commands(tmp_path) -> dict[str, list[str]]:
    """Every CLI command that calls the API, with and without --json where it has one."""
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps(CLAIMS))
    orders = tmp_path / "turn.txt"
    orders.write_text("warfarin 5 mg by mouth daily\n")
    return {
        "verify": ["verify", "--file", str(claims)],
        "verify --json": ["verify", "--file", str(claims), "--json"],
        "get": ["get", RUN_ID],
        "get --json": ["get", RUN_ID, "--json"],
        "accuracy": ["accuracy", RUN_ID],
        "accuracy --json": ["accuracy", RUN_ID, "--json"],
        "export": ["export", RUN_ID, "--format", "csv", "--out", str(tmp_path / "out.csv")],
        "observe": ["observe", str(orders)],
        "observe --json": ["observe", str(orders), "--json"],
    }


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)


def run_cli(argv: list[str], handler: Handler, capsys) -> tuple[int, str, str]:
    built: list[OrinyxClient] = []

    def factory(url: str, key: str) -> OrinyxClient:
        built.append(OrinyxClient(url, key, transport=httpx.MockTransport(handler)))
        return built[-1]

    code = cli.main(argv, client_factory=factory)
    captured = capsys.readouterr()
    assert len(built) == 1
    return code, captured.out, captured.err


def assert_json_or_empty(out: str) -> None:
    """On an error --json prints nothing, or (observe) the runs already made, as JSON."""
    if out.strip():
        json.loads(out)


@pytest.mark.parametrize("status", STATUSES)
def test_an_api_refusal_exits_1_with_its_reason_on_stderr(status, api_env, tmp_path, capsys):
    _, message = REFUSALS[status]
    for name, argv in cli_commands(tmp_path).items():
        code, out, err = run_cli(argv, refusing(status), capsys)
        assert code == cli.EXIT_ERROR, (name, code, out, err)
        assert message in err, (name, err)
        assert err.startswith("orinyx: "), (name, err)
        assert_no_traceback(out + err)
        if "--json" in argv:
            assert_json_or_empty(out)
        elif name != "observe":
            assert out == "", (name, out)


@pytest.mark.parametrize("failure", sorted(FAILURES))
def test_a_transport_failure_or_bad_answer_exits_1_readably(failure, api_env, tmp_path, capsys):
    handler, reason = FAILURES[failure]
    for name, argv in cli_commands(tmp_path).items():
        if name.startswith("export"):
            continue  # an export is a file, not JSON: covered by the transport case below
        code, out, err = run_cli(argv, handler, capsys)
        assert code == cli.EXIT_ERROR, (name, code, out, err)
        assert err.startswith("orinyx: ") and err.strip() != "orinyx:", (name, err)
        if failure in ("transport_error", "non_json_error_page"):
            assert reason in err, (name, err)
        assert_no_traceback(out + err)


def test_an_export_that_is_not_the_requested_file_exits_1_readably(api_env, tmp_path, capsys):
    argv = cli_commands(tmp_path)["export"]
    for handler in (_unreachable, _not_json):
        code, out, err = run_cli(argv, handler, capsys)
        assert code == cli.EXIT_ERROR and err.startswith("orinyx: "), (code, err)
        assert_no_traceback(out + err)
    assert not (tmp_path / "out.csv").exists()


def test_a_plain_http_api_url_is_a_readable_error_not_a_traceback(monkeypatch, capsys):
    monkeypatch.setenv("ORINYX_API_URL", "http://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)
    assert cli.main(["get", RUN_ID]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "https" in err and SENTINEL_BODY not in err


def test_the_stdio_server_refuses_a_plain_http_api_url_readably(monkeypatch, capsys):
    pytest.importorskip("mcp")
    from orinyx_mcp import __main__ as stdio
    from orinyx_mcp import server

    def must_not_start(*args, **kwargs):
        raise AssertionError("the stdio server must not start with this configuration")

    monkeypatch.setattr(server, "build_server", must_not_start)
    monkeypatch.setenv("ORINYX_API_URL", "http://api.orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", SENTINEL_KEY)
    assert stdio.main([]) == 1
    err = capsys.readouterr().err
    assert "https" in err and SENTINEL_BODY not in err

"""The four exam reads refuse a well-formed 200 of the wrong shape.

get_next_exam_case, get_exam_cases, finish_exam and get_exam_report each read one JSON object
from the API. A JSON object that is not the shape the engine sends is refused by the client
as `OrinyxApiError(200, "invalid_response", ...)`, and reaches an MCP caller as a tool error,
never as a success sentence built from missing fields.

The shape each read requires ("an int" never includes a bool; "a case" is an object whose
`caseId` is a non-empty string):

- next case: `remaining` is an int. With `case` absent or null (the engine's "every case has
  been answered") it is 0; with a case it is 1 or more;
- cases: `cases` is a list, and every item is a case;
- finish: `id` is an int and `status` is "completed" (a 200 from /complete is a completed run);
- report: the key `verdict` is present and null or a string; `caseSet` and `metrics` are
  objects; `caseSet.clinicallyReviewed`, when present, is a bool; `reasons`, when present, is
  a list of strings; `cases` is a list of cases.

The near-miss answers below differ from an accepted answer in one value each, and carry a
planted marker the refusal must never repeat. A report whose `clinicallyReviewed` is not a
bool is refused rather than rendered, because the renderer reads it by truthiness: "false"
would print a result with no REHEARSAL banner.

Over the real OrinyxClient with an httpx.MockTransport (no network). All data is synthetic.
"""

import copy

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxApiError, OrinyxClient

from tests.test_clean_errors import WRONG_SHAPE_SUCCESS_TEXT, call_tools

API_URL = "https://api.orinyx.example"
# A value no error text may repeat: a refusal names the shape, never the answer's content.
MARKER = "SHAPEMARKER"
CASE = {"caseId": "amb-003", "vignette": "Clinician: continue warfarin 5 mg."}
REPORT_SHAPE = {"verdict": "fail", "caseSet": {}, "metrics": {}, "cases": []}

# tool name -> (client method, extra method args, route suffix)
READS: dict[str, tuple[str, tuple, str]] = {
    "get_next_exam_case": ("exam_next_case", (), "next-case"),
    "get_exam_cases": ("exam_cases", (), "cases"),
    "finish_exam": ("exam_finish", (False,), "complete"),
    "get_exam_report": ("exam_report", (), "report"),
}

# Wrong-shape answers, each a JSON object: (tool, id) -> body.
WRONG_SHAPES: dict[tuple[str, str], dict] = {
    ("get_next_exam_case", "unexpected"): {"unexpected": True},
    ("get_next_exam_case", "no-remaining"): {"case": CASE},
    ("get_next_exam_case", "remaining-a-string"): {"remaining": "1", "case": CASE},
    ("get_next_exam_case", "remaining-null"): {"remaining": None, "case": CASE},
    ("get_next_exam_case", "case-without-caseId"): {"remaining": 1, "case": {"vignette": MARKER}},
    ("get_next_exam_case", "case-empty-object"): {"remaining": 0, "case": {}},
    ("get_next_exam_case", "case-a-string"): {"remaining": 1, "case": MARKER},
    ("get_next_exam_case", "case-a-list"): {"remaining": 1, "case": [CASE]},
    ("get_exam_cases", "unexpected"): {"unexpected": True},
    ("get_exam_cases", "cases-missing"): {"runId": 12, "data": [CASE]},
    ("get_exam_cases", "cases-null"): {"cases": None},
    ("get_exam_cases", "cases-an-object"): {"cases": CASE},
    ("get_exam_cases", "an-item-not-an-object"): {"cases": [CASE, MARKER]},
    ("get_exam_cases", "an-item-without-caseId"): {"cases": [{"vignette": MARKER}]},
    ("finish_exam", "unexpected"): {"unexpected": True},
    ("finish_exam", "empty"): {},
    ("finish_exam", "no-status"): {"id": 12, "verdict": MARKER},
    ("finish_exam", "no-id"): {"status": "completed"},
    ("get_exam_report", "unexpected"): {"unexpected": True},
    ("get_exam_report", "no-verdict"): {k: v for k, v in REPORT_SHAPE.items() if k != "verdict"},
    ("get_exam_report", "caseSet-null"): REPORT_SHAPE | {"caseSet": None},
    ("get_exam_report", "caseSet-a-list"): REPORT_SHAPE | {"caseSet": [MARKER]},
    ("get_exam_report", "metrics-missing"): {
        k: v for k, v in REPORT_SHAPE.items() if k != "metrics"
    },
    ("get_exam_report", "metrics-null"): REPORT_SHAPE | {"metrics": None},
    ("get_exam_report", "cases-missing"): {k: v for k, v in REPORT_SHAPE.items() if k != "cases"},
    ("get_exam_report", "cases-an-object"): REPORT_SHAPE | {"cases": {"caseId": MARKER}},
}

# Accepted answers that carry the marker; each near-miss below changes one value of one of them.
MARKED_CASE = CASE | {"vignette": MARKER}
NEXT_DONE = {"runId": 12, "remaining": 0, "detail": MARKER}
NEXT_ONE = {"runId": 12, "remaining": 1, "case": MARKED_CASE}
CASES_ONE = {"runId": 12, "cases": [MARKED_CASE]}
FINISHED = {"id": 12, "status": "completed", "verdict": MARKER}
SIGNED_SET = {"id": "s", "version": MARKER, "clinicallyReviewed": True}
REPORT_ANSWER = {
    "runId": 12,
    "verdict": "pass",
    "reasons": [],
    "caseSet": {"id": "s", "version": MARKER, "clinicallyReviewed": False},
    "metrics": {},
    "cases": [{"caseId": "amb-003"}],
}


def _next_case_id(case_id) -> dict:
    return NEXT_ONE | {"case": MARKED_CASE | {"caseId": case_id}}


def _report_set(**changes) -> dict:
    return REPORT_ANSWER | {"caseSet": REPORT_ANSWER["caseSet"] | changes}


# Near misses of each rule, refused the same way.
WRONG_SHAPES |= {
    # next case: no case says "every case has been answered", so `remaining` must be 0.
    ("get_next_exam_case", "remaining-5-no-case"): NEXT_DONE | {"remaining": 5},
    ("get_next_exam_case", "remaining-5-case-null"): NEXT_DONE | {"remaining": 5, "case": None},
    ("get_next_exam_case", "remaining-1-no-case"): NEXT_DONE | {"remaining": 1},
    ("get_next_exam_case", "remaining-1-case-null"): NEXT_DONE | {"remaining": 1, "case": None},
    ("get_next_exam_case", "remaining-minus-1-no-case"): NEXT_DONE | {"remaining": -1},
    ("get_next_exam_case", "remaining-true-no-case"): NEXT_DONE | {"remaining": True},
    ("get_next_exam_case", "remaining-false-no-case"): NEXT_DONE | {"remaining": False},
    ("get_next_exam_case", "remaining-false-case-null"): NEXT_DONE
    | {"remaining": False, "case": None},
    ("get_next_exam_case", "remaining-a-float-zero-no-case"): NEXT_DONE | {"remaining": 0.0},
    # next case: a case counts itself, so `remaining` is an int of 1 or more.
    ("get_next_exam_case", "remaining-true-with-a-case"): NEXT_ONE | {"remaining": True},
    ("get_next_exam_case", "remaining-0-with-a-case"): NEXT_ONE | {"remaining": 0},
    ("get_next_exam_case", "remaining-minus-1-with-a-case"): NEXT_ONE | {"remaining": -1},
    ("get_next_exam_case", "caseId-null"): _next_case_id(None),
    ("get_next_exam_case", "caseId-an-int"): _next_case_id(7),
    ("get_next_exam_case", "caseId-empty"): _next_case_id(""),
    ("get_exam_cases", "caseId-null"): CASES_ONE | {"cases": [MARKED_CASE | {"caseId": None}]},
    ("get_exam_cases", "caseId-an-int"): CASES_ONE | {"cases": [MARKED_CASE | {"caseId": 7}]},
    ("get_exam_cases", "caseId-empty"): CASES_ONE | {"cases": [MARKED_CASE | {"caseId": ""}]},
    ("get_exam_cases", "second-caseId-empty"): CASES_ONE
    | {"cases": [CASE, MARKED_CASE | {"caseId": ""}]},
    # finish: only a completed run with an int id proves the finish happened.
    ("finish_exam", "id-null"): FINISHED | {"id": None},
    ("finish_exam", "id-true"): FINISHED | {"id": True},
    ("finish_exam", "id-false"): FINISHED | {"id": False},
    ("finish_exam", "id-a-string"): FINISHED | {"id": "12"},
    ("finish_exam", "id-a-float"): FINISHED | {"id": 12.0},
    ("finish_exam", "status-null"): FINISHED | {"status": None},
    ("finish_exam", "status-open"): FINISHED | {"status": "open"},
    ("finish_exam", "status-error"): FINISHED | {"status": "error", "error": {"detail": MARKER}},
    ("finish_exam", "status-true"): FINISHED | {"status": True},
    ("finish_exam", "status-false"): FINISHED | {"status": False},
    ("finish_exam", "id-and-status-null"): FINISHED | {"id": None, "status": None},
    # report: verdict null or a string.
    ("get_exam_report", "verdict-an-int"): REPORT_ANSWER | {"verdict": 5},
    ("get_exam_report", "verdict-true"): REPORT_ANSWER | {"verdict": True},
    ("get_exam_report", "verdict-false"): REPORT_ANSWER | {"verdict": False},
    ("get_exam_report", "verdict-an-object"): REPORT_ANSWER | {"verdict": {"detail": MARKER}},
    # report: clinicallyReviewed, when present, a bool.
    ("get_exam_report", "clinicallyReviewed-string-false"): _report_set(clinicallyReviewed="false"),
    ("get_exam_report", "clinicallyReviewed-string-true"): _report_set(clinicallyReviewed="true"),
    ("get_exam_report", "clinicallyReviewed-null"): _report_set(clinicallyReviewed=None),
    ("get_exam_report", "clinicallyReviewed-1"): _report_set(clinicallyReviewed=1),
    ("get_exam_report", "clinicallyReviewed-0"): _report_set(clinicallyReviewed=0),
    # report: every case item an object with a non-empty string caseId.
    ("get_exam_report", "cases-an-int-item"): REPORT_ANSWER | {"cases": [1]},
    ("get_exam_report", "cases-an-empty-object-item"): REPORT_ANSWER | {"cases": [{}]},
    ("get_exam_report", "case-caseId-empty"): REPORT_ANSWER | {"cases": [{"caseId": ""}]},
    ("get_exam_report", "case-caseId-null"): REPORT_ANSWER | {"cases": [{"caseId": None}]},
    ("get_exam_report", "case-caseId-an-int"): REPORT_ANSWER | {"cases": [{"caseId": 3}]},
    # report: reasons, when present, a list of strings.
    ("get_exam_report", "reasons-null"): REPORT_ANSWER | {"reasons": None},
    ("get_exam_report", "reasons-a-string"): REPORT_ANSWER | {"reasons": "abc"},
    ("get_exam_report", "reasons-an-int-item"): REPORT_ANSWER | {"reasons": [1]},
    ("get_exam_report", "reasons-a-null-item"): REPORT_ANSWER | {"reasons": [None]},
    ("get_exam_report", "reasons-an-object"): REPORT_ANSWER | {"reasons": {}},
    ("get_exam_report", "reasons-a-string-then-an-int"): REPORT_ANSWER | {"reasons": [MARKER, 1]},
}

# The edges of each rule that the engine does send: accepted and returned unchanged.
ACCEPTED_SHAPES: dict[tuple[str, str], dict] = {
    ("get_next_exam_case", "a-case"): {"runId": 12, "remaining": 2, "case": CASE},
    ("get_next_exam_case", "done-case-null"): {"runId": 12, "remaining": 0, "case": None},
    ("get_next_exam_case", "done-no-case-key"): {"runId": 12, "remaining": 0},
    ("get_exam_cases", "empty-list"): {"runId": 12, "cases": []},
    ("get_exam_cases", "one-case"): {"runId": 12, "cases": [CASE]},
    ("finish_exam", "id-and-status"): {"id": 12, "status": "completed"},
    ("get_exam_report", "verdict-null"): REPORT_SHAPE | {"verdict": None},
    # The accepted answer each near miss above was made from, extra keys and all.
    ("get_next_exam_case", "done-with-an-extra-key"): NEXT_DONE,
    ("get_next_exam_case", "done-case-null-with-an-extra-key"): NEXT_DONE | {"case": None},
    ("get_next_exam_case", "remaining-1-with-a-case"): NEXT_ONE,
    ("get_exam_cases", "one-marked-case"): CASES_ONE,
    ("finish_exam", "completed-with-other-keys"): FINISHED,
    ("get_exam_report", "unsigned-with-reasons-empty"): REPORT_ANSWER,
    ("get_exam_report", "clinicallyReviewed-absent"): REPORT_ANSWER
    | {"caseSet": {"id": "s", "version": MARKER}},
    ("get_exam_report", "clinicallyReviewed-true"): REPORT_ANSWER | {"caseSet": SIGNED_SET},
    ("get_exam_report", "reasons-absent"): {
        k: v for k, v in REPORT_ANSWER.items() if k != "reasons"
    },
    ("get_exam_report", "reasons-one-string"): REPORT_ANSWER | {"reasons": ["hard: x"]},
    ("get_exam_report", "verdict-a-string-cases-empty"): REPORT_ANSWER | {"cases": []},
}


def _ids(shapes: dict[tuple[str, str], dict]) -> list[str]:
    return [f"{name}-{shape}" for name, shape in sorted(shapes)]


def _answering(suffix: str, body: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/benchmark-runs/12/{suffix}", request.url.path
        return httpx.Response(200, json=copy.deepcopy(body))

    return handler


def _read(name: str, body: dict) -> dict:
    method, args, suffix = READS[name]
    transport = httpx.MockTransport(_answering(suffix, body))
    with OrinyxClient(API_URL, "k", transport=transport) as client:
        return getattr(client, method)(12, *args)


@pytest.mark.parametrize(("name", "shape"), sorted(WRONG_SHAPES), ids=_ids(WRONG_SHAPES))
def test_the_client_refuses_a_wrong_shape_answer_as_invalid_response(name, shape):
    with pytest.raises(OrinyxApiError) as refused:
        _read(name, WRONG_SHAPES[(name, shape)])
    assert (refused.value.status, refused.value.code) == (200, "invalid_response")
    assert str(refused.value).startswith("invalid_response (200): unexpected ")
    assert str(refused.value).endswith(" shape")
    assert MARKER not in str(refused.value)


@pytest.mark.parametrize(("name", "shape"), sorted(ACCEPTED_SHAPES), ids=_ids(ACCEPTED_SHAPES))
def test_the_client_returns_an_engine_shaped_answer_unchanged(name, shape):
    body = ACCEPTED_SHAPES[(name, shape)]
    assert _read(name, body) == body


def test_every_exam_read_is_driven_wrong_and_right():
    assert {name for name, _ in WRONG_SHAPES} == set(READS)
    assert {name for name, _ in ACCEPTED_SHAPES} == set(READS)
    assert all(WRONG_SHAPES[(name, "unexpected")] == {"unexpected": True} for name in READS)


@pytest.mark.parametrize(("name", "shape"), sorted(WRONG_SHAPES), ids=_ids(WRONG_SHAPES))
async def test_a_wrong_shape_answer_is_a_tool_error_never_a_success(name, shape):
    _, _, suffix = READS[name]
    is_error, text = (await call_tools(_answering(suffix, WRONG_SHAPES[(name, shape)]), [name]))[
        name
    ]
    assert is_error, text
    assert "invalid_response (200): unexpected " in text, text
    assert WRONG_SHAPE_SUCCESS_TEXT[name] not in text, text
    assert MARKER not in text
    assert "Traceback" not in text and 'File "' not in text


@pytest.mark.parametrize("name", sorted(READS))
def test_the_recorded_success_text_is_what_the_tool_would_say_on_a_wrong_shape(name):
    """The fragment the wrong-shape check looks for is real: a client that passed the
    `{"unexpected": true}` answer through, as the client did before it checked shapes, makes
    the tool render exactly that fragment. So its absence from the error proves something."""
    method, _, _ = READS[name]

    class PassThrough:
        """Answers like a client that checks only that the answer is a JSON object."""

        def __getattr__(self, attr):
            assert attr == method, attr
            return lambda *args, **kwargs: {"unexpected": True}

    text = getattr(tools, name)(PassThrough(), run_id=12)
    assert WRONG_SHAPE_SUCCESS_TEXT[name] in text, text


@pytest.mark.parametrize(("name", "shape"), sorted(ACCEPTED_SHAPES), ids=_ids(ACCEPTED_SHAPES))
async def test_an_engine_shaped_answer_is_a_tool_success(name, shape):
    _, _, suffix = READS[name]
    is_error, text = (await call_tools(_answering(suffix, ACCEPTED_SHAPES[(name, shape)]), [name]))[
        name
    ]
    assert not is_error, text
    assert "invalid_response" not in text, text


# --- a report reads as evidence only when `clinicallyReviewed` is exactly true ---------------

ABSENT = object()
REVIEWED_VALUES = [ABSENT, True, False, "false", "False", "true", "no", 1, 0, 1.0, None, "", [0]]


def _reviewed(value, kind: str) -> dict:
    case_set = {"id": "s", "version": "1"}
    if value is not ABSENT:
        case_set["clinicallyReviewed"] = value
    return REPORT_ANSWER | {"scoringContract": kind, "caseSet": case_set}


@pytest.mark.parametrize("kind", ["claims", "coding"])
@pytest.mark.parametrize(
    "value", REVIEWED_VALUES, ids=lambda v: "absent" if v is ABSENT else repr(v)
)
async def test_a_report_shows_no_rehearsal_banner_only_when_clinically_reviewed_is_true(
    value, kind
):
    """Whatever the API sends as `clinicallyReviewed`, the report is either a tool error or
    carries the REHEARSAL banner, unless the value is exactly true. A value that is not a bool
    is refused outright, so it never reaches the renderer's truthiness test."""
    is_error, text = (
        await call_tools(_answering("report", _reviewed(value, kind)), ["get_exam_report"])
    )["get_exam_report"]
    banner = tools.CODING_REHEARSAL if kind == "coding" else tools.REHEARSAL
    if value is True:
        assert not is_error and banner not in text, text
        assert "\nResult: PASS" in text, text
    elif value is False or value is ABSENT:
        assert not is_error, text
        assert banner in text and "\nResult (REHEARSAL - not evidence): PASS" in text, text
    else:
        assert is_error, text
        assert "invalid_response (200): unexpected exam report shape" in text, text
        assert "PASS" not in text and banner not in text, text


def test_a_clinically_reviewed_string_false_is_refused_never_a_pass_without_the_banner():
    """The regression this guards: `"clinicallyReviewed": "false"` is truthy, so a client that
    let it through made the tool print `Result: PASS` with no REHEARSAL banner, an unsigned
    result presented as evidence. The client refuses it before any text is rendered."""
    body = _reviewed("false", "claims")

    class PassThrough:
        """Answers like a client that checks the report's containers but not this value."""

        def exam_report(self, run_id):
            return copy.deepcopy(body)

    unchecked = tools.get_exam_report(PassThrough(), run_id=12)
    assert "\nResult: PASS" in unchecked and tools.REHEARSAL not in unchecked, unchecked

    with pytest.raises(OrinyxApiError) as refused:
        _read("get_exam_report", body)
    assert (refused.value.status, refused.value.code) == (200, "invalid_response")
    assert str(refused.value) == "invalid_response (200): unexpected exam report shape"

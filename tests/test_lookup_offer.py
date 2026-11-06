"""start_a_test offers the label and monograph lookups only to an account the API lets read them.

Over the real OrinyxClient with an httpx.MockTransport standing in for the API (no network),
through the MCP call path. The mock admits each account type to each route the way the API's
own guards do today:

- the verification list admits clinician, quality_lead, admin and developer accounts;
- the label, monograph and document lookup routes admit clinician, quality_lead, admin and
  developer accounts, and not product (vendor) accounts;
- a product (vendor) account reaches the exam list and not the verification list.

Proven here:

- a developer account can check claims and is offered all five lookup tools;
- an account that can check claims but whose lookup read is refused (401 or 403, for example
  an API that does not admit it) is not offered the lookups and is told so in one sentence;
- clinician, quality_lead and admin accounts are still offered the lookups, and their menus
  read byte for byte as before;
- a product account's menu is unchanged and it is not asked the extra read;
- the extra read is one GET of the monograph list with `limit=1` and nothing else;
- when that read fails for any reason but 401 or 403, start_a_test is a tool error carrying
  the reason, the same as a failure on its other two reads: no lookup is offered and none is
  refused in words.
"""

import httpx
import pytest
from orinyx_mcp.client import OrinyxApiError, OrinyxClient

from tests.test_clean_errors import (
    CREDENTIAL_REFUSED_TEXT,
    MENU_EXAM_NEEDS_PRODUCT,
    MENU_EXAM_NONE_OPEN,
    MENU_EXAM_OPEN,
    MENU_LOOKUP_PRODUCT,
    MENU_LOOKUP_TESTER,
    MENU_QUICK_CHECK_PRODUCT,
    MENU_QUICK_CHECK_TESTER,
    REFUSALS,
    Handler,
    _html_gateway_page,
    _no_runs,
    _open_exams,
    _unreachable,
    assert_no_traceback,
    call_tools,
    menu,
    refusing,
)

# The lookup paragraph for an account that can check claims but not read label text. Written
# out here rather than imported, so a change to the wording fails this file.
MENU_LOOKUP_NOT_THIS_ACCOUNT = (
    "  Not available to this account. Ask the Orinyx operator if you need FDA label or "
    "monograph text."
)
LOOKUP_TOOLS = (
    "find_fda_label",
    "read_fda_label_section",
    "find_otc_monographs",
    "get_otc_monograph",
    "read_otc_monograph_section",
)
VERIFY, EXAMS, LOOKUPS = "/v1/verifications", "/v1/benchmark-runs", "/v1/monographs"


def engine(verifications: Handler, exams: Handler, lookups: Handler, seen: list) -> Handler:
    """An API that answers start_a_test's reads by route and records every request."""
    routes = {VERIFY: verifications, EXAMS: exams, LOOKUPS: lookups}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path not in routes:
            raise AssertionError(f"start_a_test asked an unexpected route: {request.url.path}")
        return routes[request.url.path](request)

    return handler


# account type -> (verification list, open exam list, lookup read, the whole menu).
ACCOUNTS: dict[str, tuple[Handler, Handler, Handler, str]] = {
    "clinician": (
        _no_runs,
        refusing(403),
        _no_runs,
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_NEEDS_PRODUCT, MENU_LOOKUP_TESTER),
    ),
    "quality_lead": (
        _no_runs,
        _open_exams,
        _no_runs,
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_OPEN, MENU_LOOKUP_TESTER),
    ),
    "admin": (
        _no_runs,
        _no_runs,
        _no_runs,
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_NONE_OPEN, MENU_LOOKUP_TESTER),
    ),
    # The lookup read answers a developer 200 since the API admitted developer accounts to the
    # five lookup routes (2026-11-05), so the menu offers the lookups.
    "developer": (
        _no_runs,
        refusing(403),
        _no_runs,
        menu(MENU_QUICK_CHECK_TESTER, MENU_EXAM_NEEDS_PRODUCT, MENU_LOOKUP_TESTER),
    ),
    "product": (
        refusing(403),
        _open_exams,
        refusing(403),
        menu(MENU_QUICK_CHECK_PRODUCT, MENU_EXAM_OPEN, MENU_LOOKUP_PRODUCT),
    ),
}


async def start_a_test(verifications: Handler, exams: Handler, lookups: Handler):
    seen: list[httpx.Request] = []
    handler = engine(verifications, exams, lookups, seen)
    is_error, text = (await call_tools(handler, ["start_a_test"]))["start_a_test"]
    return is_error, text, seen


@pytest.mark.parametrize("account", sorted(ACCOUNTS))
async def test_each_account_type_reads_its_whole_menu(account):
    verifications, exams, lookups, expected = ACCOUNTS[account]
    is_error, text, seen = await start_a_test(verifications, exams, lookups)
    assert not is_error, text
    assert text == expected


async def test_a_developer_is_offered_every_lookup_tool():
    is_error, text, _ = await start_a_test(*ACCOUNTS["developer"][:3])
    assert not is_error, text
    for name in LOOKUP_TOOLS:
        assert name in text, name
    assert MENU_LOOKUP_NOT_THIS_ACCOUNT not in text
    assert MENU_LOOKUP_PRODUCT + "\n" not in text  # a developer is not a product account


@pytest.mark.parametrize("account", ["clinician", "quality_lead", "admin"])
async def test_a_clinical_account_is_offered_every_lookup_tool(account):
    is_error, text, _ = await start_a_test(*ACCOUNTS[account][:3])
    assert not is_error, text
    for name in LOOKUP_TOOLS:
        assert name in text, name
    assert MENU_LOOKUP_NOT_THIS_ACCOUNT not in text


@pytest.mark.parametrize("account", ["clinician", "quality_lead", "admin", "developer"])
async def test_the_extra_read_is_one_list_get_with_the_same_credential(account):
    _, _, seen = await start_a_test(*ACCOUNTS[account][:3])
    assert [request.url.path for request in seen] == [VERIFY, EXAMS, LOOKUPS]
    probe = seen[-1]
    assert probe.method == "GET"
    assert dict(probe.url.params) == {"limit": "1"}
    assert probe.content == b""
    assert probe.headers["authorization"] == seen[0].headers["authorization"]


async def test_a_product_account_is_not_asked_the_extra_read():
    _, _, seen = await start_a_test(*ACCOUNTS["product"][:3])
    assert [request.url.path for request in seen] == [VERIFY, EXAMS]


# The lookup read refused outright (401) or not cleared (403): not offered, as can_verify reads
# the same two statuses. No account type the API knows is refused the read while it can check
# claims, but the sentence stays the answer for any credential that is (for example the hosted
# MCP in front of an API that does not admit developer accounts to the lookups).
@pytest.mark.parametrize("status", [401, 403])
async def test_a_refused_lookup_read_is_answered_with_the_sentence(status):
    verifications, exams, _, _ = ACCOUNTS["developer"]
    is_error, text, _ = await start_a_test(verifications, exams, refusing(status))
    assert not is_error, text
    assert text == menu(
        MENU_QUICK_CHECK_TESTER, MENU_EXAM_NEEDS_PRODUCT, MENU_LOOKUP_NOT_THIS_ACCOUNT
    )
    assert text != CREDENTIAL_REFUSED_TEXT


# Every other failure of the lookup read: (handler, the reason the caller must see).
LOOKUP_READ_FAILURES: dict[str, tuple[Handler, str]] = {
    str(status): (refusing(status), f"{code} ({status}): {message}")
    for status, (code, message) in REFUSALS.items()
    if status not in (401, 403)
}
LOOKUP_READ_FAILURES["transport_error"] = (_unreachable, "connection refused")
LOOKUP_READ_FAILURES["non_json_error_page"] = (_html_gateway_page, "Bad gateway")


@pytest.mark.parametrize("failure", sorted(LOOKUP_READ_FAILURES))
@pytest.mark.parametrize("exams", ["no-product", "open-exams"])
async def test_an_unavailable_lookup_read_is_a_tool_error_not_a_guess(failure, exams):
    lookups, reason = LOOKUP_READ_FAILURES[failure]
    exam_list = refusing(403) if exams == "no-product" else _open_exams
    is_error, text, _ = await start_a_test(_no_runs, exam_list, lookups)
    assert is_error, text
    assert reason in text
    for fragment in (*LOOKUP_TOOLS, MENU_LOOKUP_NOT_THIS_ACCOUNT, CREDENTIAL_REFUSED_TEXT):
        assert fragment not in text, fragment
    assert_no_traceback(text)


def _read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out waiting for the answer", request=request)


def _connect_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("timed out connecting", request=request)


# The lookup read timing out (the client's own timeout, as opposed to a refused connection):
# (handler, the reason the caller must see).
LOOKUP_READ_TIMEOUTS: dict[str, tuple[Handler, str]] = {
    "read_timeout": (_read_timeout, "transport_error: timed out waiting for the answer"),
    "connect_timeout": (_connect_timeout, "transport_error: timed out connecting"),
}


@pytest.mark.parametrize("timeout", sorted(LOOKUP_READ_TIMEOUTS))
@pytest.mark.parametrize("exams", ["no-product", "open-exams"])
async def test_a_timed_out_lookup_read_is_a_tool_error_carrying_the_reason(timeout, exams):
    lookups, reason = LOOKUP_READ_TIMEOUTS[timeout]
    exam_list = refusing(403) if exams == "no-product" else _open_exams
    is_error, text, seen = await start_a_test(_no_runs, exam_list, lookups)
    assert is_error, text
    assert reason in text
    for fragment in (*LOOKUP_TOOLS, MENU_LOOKUP_NOT_THIS_ACCOUNT, CREDENTIAL_REFUSED_TEXT):
        assert fragment not in text, fragment
    assert_no_traceback(text)
    assert [request.url.path for request in seen] == [VERIFY, EXAMS, LOOKUPS]


# --- the client method ---------------------------------------------------------------------


def _client(handler: Handler) -> OrinyxClient:
    return OrinyxClient(
        "https://orinyx.example", "ork_live_test", transport=httpx.MockTransport(handler)
    )


def test_can_read_labels_reads_the_monograph_list_and_folds_401_and_403_into_false():
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["call"] = (request.method, request.url.path, dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    assert _client(ok).can_read_labels() is True
    assert seen["call"] == ("GET", LOOKUPS, {"limit": "1"})
    assert _client(refusing(401)).can_read_labels() is False
    assert _client(refusing(403)).can_read_labels() is False
    for status in (404, 422, 429, 503):
        with pytest.raises(OrinyxApiError) as excinfo:
            _client(refusing(status)).can_read_labels()
        assert excinfo.value.status == status
    with pytest.raises(OrinyxApiError) as excinfo:
        _client(_unreachable).can_read_labels()
    assert excinfo.value.code == "transport_error"

"""Regression cases, MCP side: the cases that the free client can carry
on its own (fake clients and httpx.MockTransport, never the engine, never the network).

Cases already covered by other tests (in test_text.py, test_client.py, test_tools.py and
test_http.py) are not repeated here. This file pins the engine's one-drug-per-order refusal
wording through the client, interaction-flag passthrough, the transport failure on the client
itself, the structured-result contract the MCP does not carry yet (xfail strict until
structured results ship), and rendering determinism."""

import json

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxApiError, OrinyxClient
from orinyx_mcp.text import render_run_table, render_run_text

from tests.test_text import RUN
from tests.test_tools import FakeClient

ONE_ORDER_TWO_DRUGS = "Warfarin 5 mg by mouth daily and ibuprofen 800 mg by mouth three times daily"
TWO_ORDERS = ["Warfarin 5 mg by mouth daily", "ibuprofen 800 mg by mouth three times daily"]
ONE_DRUG_PER_ORDER_MESSAGE = (
    "Order 1: One drug per order; this order names several (Warfarin, ibuprofen)."
)


def _client(handler) -> OrinyxClient:
    return OrinyxClient(
        "https://orinyx.example", "ork_live_test", transport=httpx.MockTransport(handler)
    )


# --- the engine's 422 reaches the agent with the engine's words ----------------------------------


def test_the_engines_one_drug_per_order_refusal_is_passed_through_verbatim():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        error = {"code": "validation_failed", "message": ONE_DRUG_PER_ORDER_MESSAGE, "details": []}
        return httpx.Response(422, json={"error": error})

    with pytest.raises(OrinyxApiError) as caught:
        _client(handler).verify_orders([ONE_ORDER_TWO_DRUGS])
    assert seen[0]["orders"] == [ONE_ORDER_TWO_DRUGS]
    assert (caught.value.status, caught.value.code) == (422, "validation_failed")
    assert caught.value.message == ONE_DRUG_PER_ORDER_MESSAGE
    assert str(caught.value) == f"validation_failed (422): {ONE_DRUG_PER_ORDER_MESSAGE}"


def test_a_pydantic_422_keeps_its_field_details():
    def handler(request: httpx.Request) -> httpx.Response:
        envelope = {
            "error": {
                "code": "validation_failed",
                "message": "Request validation failed.",
                "details": [{"field": "orders", "message": "List should have at least 1 item"}],
            }
        }
        return httpx.Response(422, json=envelope)

    with pytest.raises(OrinyxApiError) as caught:
        _client(handler).verify_orders([])
    assert caught.value.status == 422
    assert [d["field"] for d in caught.value.details] == ["orders"]


# --- two orders, interaction checking on ---------------------------------------------------------


def test_check_interactions_true_reaches_the_api_call_with_both_orders():
    client = FakeClient()
    tools.verify_order_text(client, orders=TWO_ORDERS, check_interactions=True)
    assert client.calls == [
        (
            "verify_orders",
            TWO_ORDERS,
            {"tool_name": None, "tool_version": None, "check_interactions": True},
        )
    ]


# --- source retrieval failure (the API itself is unreachable) ------------------------------------


def test_an_unreachable_api_is_a_typed_transport_error_without_the_bearer():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(OrinyxApiError) as caught:
        _client(handler).verify_orders(TWO_ORDERS)
    assert (caught.value.status, caught.value.code) == (0, "transport_error")
    assert "connection refused" in caught.value.message
    assert "ork_live_test" not in str(caught.value)


def test_a_5xx_from_the_api_is_an_api_error_not_a_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream label source unavailable")

    with pytest.raises(OrinyxApiError) as caught:
        _client(handler).verify_orders(TWO_ORDERS)
    assert caught.value.status == 503


# --- structured result beside the text -----------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="verify_order_text returns Markdown text only; no "
    "structuredContent carries the engine JSON beside it yet",
)
def test_verify_order_text_carries_the_engine_json_as_structured_content():
    result = tools.verify_order_text(FakeClient(), orders=TWO_ORDERS)
    assert not isinstance(result, str)
    assert result["structuredContent"]["runId"] == RUN["runId"]
    assert [v["verdict"] for v in result["structuredContent"]["verdicts"]] == [
        v["verdict"] for v in RUN["verdicts"]
    ]


def test_today_the_tool_returns_text_that_names_the_run_id():
    result = tools.verify_order_text(FakeClient(), orders=TWO_ORDERS)
    assert isinstance(result, str) and RUN["runId"] in result


# --- repeated identical input --------------------------------------------------------------------


def test_rendering_the_same_run_twice_is_byte_identical():
    assert render_run_table(RUN) == render_run_table(RUN)
    assert render_run_text(RUN) == render_run_text(RUN)
    first = tools.verify_order_text(FakeClient(), orders=TWO_ORDERS, check_interactions=True)
    second = tools.verify_order_text(FakeClient(), orders=TWO_ORDERS, check_interactions=True)
    assert first == second

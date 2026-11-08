"""Items 10/11 — the one HTTP client the MCP server and the CLI share. It speaks only to
the REST API (never the engine), sends the API key as a bearer, validates every response
before using a field, and turns the error envelope into a typed exception."""

import json

import httpx
import pytest
from orinyx_mcp.client import ExportFile, OrinyxApiError, OrinyxClient

RUN_JSON = {
    "runId": "0d8b1c6e-3f2a-4b0e-9c21-9d8e2f1a7b55",
    "toolName": "acme-scribe",
    "toolVersion": "1.0",
    "createdAt": None,
    "aggregate": {"total": 1, "supported": 0, "contradicted": 1, "abstain": 0},
    "verdicts": [
        {
            "verdictId": 1,
            "assertionId": 1,
            "rawText": "warfarin 20 mg daily",
            "drug": "warfarin",
            "rxcui": "11289",
            "claimType": "dose_range",
            "verdict": "contradicted",
            "severity": "moderate",
            "explanation": "too much",
            "severityReason": "Rated Moderate because ...",
            "citation": {"source": "openFDA", "section": "§2", "citation": "c", "url": "u"},
            "matchedRuleId": 5,
            "structuredValue": {"dose": 20, "unit": "mg"},
        }
    ],
}


def _client(handler) -> OrinyxClient:
    return OrinyxClient(
        "https://orinyx.example", "ork_live_test", transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("mode", ["hosted_mcp", "operator"])
def test_operator_opens_an_explicit_entry_mode(mode):
    def handler(request):
        assert request.url.path == "/v1/vendors/3/benchmark-runs"
        assert json.loads(request.content)["entryMode"] == mode
        return httpx.Response(201, json={"id": 12, "entryMode": mode})

    with _client(handler) as client:
        assert client.open_exam(3, "s", "1", entry_mode=mode)["entryMode"] == mode


def test_unknown_entry_modes_do_not_send_a_request():
    def handler(request):
        pytest.fail("invalid mode must not reach the API")

    with _client(handler) as client, pytest.raises(ValueError, match="entry_mode"):
        client.open_exam(3, "s", "1", entry_mode="mixed")


def test_verify_orders_posts_the_text_unchanged_and_counts_unreadable_as_flagged():
    seen = {}
    unreadable = {
        "runId": RUN_JSON["runId"],
        "aggregate": {"total": 1, "supported": 0, "contradicted": 0, "abstain": 0, "unreadable": 1},
        "verdicts": [
            {
                "rawText": "wafarin 5 mb by intramuscular injection",
                "drug": "wafarin",
                "claimType": "dose_range",
                "verdict": "unreadable",
                "severity": "none",
                "explanation": "The order cannot be read as written: ...",
                "unreadableFacets": [{"facet": "drug", "value": "wafarin", "reason": "r"}],
                "suggestions": [{"facet": "drug", "value": "wafarin", "candidates": ["warfarin"]}],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json=unreadable)

    result = _client(handler).verify_orders(["wafarin 5 mb by intramuscular injection"])
    assert seen["path"] == "/v1/verifications/orders"
    assert seen["body"] == {
        "orders": ["wafarin 5 mb by intramuscular injection"],
        "checkInteractions": False,
    }
    assert result.flagged == 1  # an order that cannot be read is not "clean"
    assert result.verdicts[0].unreadable_facets[0]["facet"] == "drug"
    assert result.verdicts[0].suggestions[0]["candidates"] == ["warfarin"]


def test_verify_posts_claims_with_the_bearer_and_tool_identity():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json=RUN_JSON)

    result = _client(handler).verify(
        [
            {
                "rawText": "warfarin 20 mg daily",
                "drug": "warfarin",
                "claimType": "dose_range",
                "structuredValue": {"dose": 20, "unit": "mg"},
            }
        ],
        tool_name="acme-scribe",
        tool_version="1.0",
    )
    assert seen["auth"] == "Bearer ork_live_test" and seen["path"] == "/v1/verifications"
    assert seen["body"]["toolName"] == "acme-scribe" and seen["body"]["toolVersion"] == "1.0"
    assert seen["body"]["checkInteractions"] is False
    assert result.run_id == RUN_JSON["runId"] and result.flagged == 1
    assert result.verdicts[0].severity == "moderate"
    assert result.raw["verdicts"][0]["severityReason"].startswith("Rated Moderate")


def test_get_run_and_accuracy_hit_the_right_paths():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accuracy"):
            return httpx.Response(
                200,
                json={
                    "runId": RUN_JSON["runId"],
                    "tallyVersion": 1,
                    "totalFlags": 1,
                    "unflaggedTotal": 0,
                    "reviewed": False,
                    "accuracy": None,
                },
            )
        return httpx.Response(200, json=RUN_JSON)

    client = _client(handler)
    assert client.get_run(RUN_JSON["runId"]).flagged == 1
    acc = client.accuracy(RUN_JSON["runId"])
    assert acc["reviewed"] is False and acc["accuracy"] is None


def test_export_returns_bytes_with_the_media_type():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/report.pdf")
        return httpx.Response(
            200,
            content=b"%PDF-1.4 fake",
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="orinyx-report-x.pdf"',
            },
        )

    file = _client(handler).export(RUN_JSON["runId"], "report.pdf")
    assert isinstance(file, ExportFile)
    assert file.content.startswith(b"%PDF") and file.media_type == "application/pdf"
    assert file.filename == "orinyx-report-x.pdf"


def test_error_envelope_becomes_a_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        envelope = {
            "error": {"code": "conflict", "message": "Run comparison is not enabled", "details": []}
        }
        return httpx.Response(409, json=envelope)

    with pytest.raises(OrinyxApiError) as excinfo:
        _client(handler).get_run(RUN_JSON["runId"])
    assert excinfo.value.status == 409 and excinfo.value.code == "conflict"
    assert "not enabled" in str(excinfo.value)


def test_unexpected_response_shape_is_refused():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"surprise": True})

    with pytest.raises(OrinyxApiError) as excinfo:
        _client(handler).get_run(RUN_JSON["runId"])
    assert excinfo.value.code == "invalid_response"


def test_nothing_in_the_package_imports_the_engine():
    """This repository is a CLIENT of the Orinyx API. The engine (`app`) is proprietary and
    must never be imported here, even when it happens to be installed beside this package."""
    import importlib
    import sys

    for name in ("client", "text", "tools", "server", "cli", "config", "http"):
        importlib.import_module(f"orinyx_mcp.{name}")
    assert not any(m == "app" or m.startswith("app.") for m in sys.modules)
    import orinyx_mcp.client as mod

    assert "orinyx_mcp" in mod.__file__


def test_run_ids_are_validated_before_they_reach_a_url():
    """A prompt-injected agent must not steer the operator's key to another endpoint."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=RUN_JSON)

    client = _client(handler)
    for bad in ("../audit/export?x=", "abc", "0d8b1c6e-3f2a-4b0e-9c21-9d8e2f1a7b55/../x"):
        with pytest.raises(ValueError):
            client.get_run(bad)
        with pytest.raises(ValueError):
            client.export(bad, "csv")
    assert calls == []


def test_plain_http_is_refused_except_loopback():
    with pytest.raises(ValueError, match="https"):
        OrinyxClient("http://orinyx.example", "ork_live_test")
    OrinyxClient("http://127.0.0.1:8000", "ork_live_test").close()
    OrinyxClient("http://localhost:8000", "ork_live_test").close()


def test_content_type_is_checked():
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"<html>login</html>", headers={"content-type": "text/html"}
        )

    with pytest.raises(OrinyxApiError) as excinfo:
        _client(html).get_run(RUN_JSON["runId"])
    assert excinfo.value.code == "invalid_response"
    with pytest.raises(OrinyxApiError) as excinfo:
        _client(html).export(RUN_JSON["runId"], "csv")
    assert excinfo.value.code == "invalid_response"


def test_invalid_response_errors_do_not_echo_response_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"runId": "x", "secret": "do-not-leak", "verdicts": "nope"})

    with pytest.raises(OrinyxApiError) as excinfo:
        _client(handler).get_run(RUN_JSON["runId"])
    assert "do-not-leak" not in str(excinfo.value)


def _refusing(status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"error": {"code": "refused", "message": f"status {status}", "details": []}}
        return httpx.Response(status, json=body)

    return handler


def test_can_verify_reads_the_verification_list_and_folds_401_and_403_into_false():
    """A documented client method: a credential that reaches the verification surface is True,
    a refused (401) or not-cleared (403) one is False, and every other failure raises."""
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen["call"] = (request.method, request.url.path, dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    assert _client(ok).can_verify() is True
    assert seen["call"] == ("GET", "/v1/verifications", {"limit": "1"})
    assert _client(_refusing(401)).can_verify() is False
    assert _client(_refusing(403)).can_verify() is False
    for status in (404, 422, 429, 503):
        with pytest.raises(OrinyxApiError) as excinfo:
            _client(_refusing(status)).can_verify()
        assert excinfo.value.status == status

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(OrinyxApiError) as excinfo:
        _client(unreachable).can_verify()
    assert excinfo.value.code == "transport_error"

"""MCP tool handlers are thin functions over OrinyxClient, tested with a fake
client. The MCP runtime itself is optional (`pip install mcp`); its import is isolated so
these tests run without it, and the server factory test skips when it is absent."""

import base64

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import ExportFile, VerificationResult

from tests.test_client import CONTEXT_JSON
from tests.test_text import ACCURACY, RUN


class FakeClient:
    def __init__(self):
        self.calls = []

    def verify(self, claims, **kwargs):
        self.calls.append(("verify", claims, kwargs))
        return VerificationResult.from_json(RUN)

    def verify_orders(self, orders, **kwargs):
        self.calls.append(("verify_orders", orders, kwargs))
        return VerificationResult.from_json(RUN)

    def get_run(self, run_id):
        self.calls.append(("get_run", run_id))
        return VerificationResult.from_json(RUN)

    def accuracy(self, run_id):
        self.calls.append(("accuracy", run_id))
        return ACCURACY

    def export(self, run_id, fmt):
        self.calls.append(("export", run_id, fmt))
        media_type = "text/csv" if fmt == "csv" else "application/pdf"
        return ExportFile(filename=f"orinyx-{fmt}", media_type=media_type, content=b"data")


def test_verify_medications_returns_a_table_with_flags():
    client = FakeClient()
    text = tools.verify_medications(
        client,
        claims=[
            {
                "rawText": "warfarin 20 mg daily",
                "drug": "warfarin",
                "claimType": "dose_range",
                "structuredValue": {"dose": 20, "unit": "mg"},
            }
        ],
        tool_name="acme-scribe",
        tool_version="1.4.2",
    )
    assert client.calls[0][0] == "verify"
    assert client.calls[0][2] == {
        "tool_name": "acme-scribe",
        "tool_version": "1.4.2",
        "check_interactions": False,
    }
    assert "| 1 | warfarin 20 mg daily | dose | FLAGGED | MODERATE |" in text
    assert "Orinyx flags; the clinician decides." in text
    assert "ACCURACY" not in text  # a fresh run has no physician review


def test_get_verification_includes_accuracy_when_reviewed():
    text = tools.get_verification(FakeClient(), run_id=RUN["runId"])
    assert "ACCURACY (physician review)" in text and "Severity corrections 1" in text


def test_get_accuracy_is_text_too():
    text = tools.get_accuracy(FakeClient(), run_id=RUN["runId"])
    assert "False-flag rate 0.0% (0 of 1 flags;" in text


def test_export_verification_returns_a_base64_blob_with_mime_type():
    blob = tools.export_verification(FakeClient(), run_id=RUN["runId"], fmt="csv")
    assert blob["mimeType"] == "text/csv" and blob["name"] == "orinyx-csv"
    assert base64.b64decode(blob["blob"]) == b"data"
    with pytest.raises(ValueError):
        tools.export_verification(FakeClient(), run_id=RUN["runId"], fmt="docx")


def test_server_factory_builds_when_the_mcp_package_is_installed():
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server, shared

    server = build_server(shared(FakeClient()))
    assert server is not None and callable(getattr(server, "run", None))
    registered = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"verify_medications", "get_verification", "get_accuracy", "export_verification"} <= (
        registered
    )


def test_tool_text_carries_the_full_run_id_an_agent_needs_for_the_other_tools():
    """Local end-to-end check 2026-10-05: the header shows 8 characters, and the only UUID in
    the text was a label's SPL set id, so a client could not read the run back."""
    client = FakeClient()
    text = tools.verify_medications(client, claims=[{"drug": "warfarin"}])
    assert f"Run id: {RUN['runId']}" in text
    assert f"Run id: {RUN['runId']}" in tools.get_verification(client, run_id=RUN["runId"])


def test_an_api_refusal_reaches_the_agent_with_its_reason_not_as_a_crash():
    pytest.importorskip("mcp")
    import asyncio

    from orinyx_mcp.client import OrinyxApiError
    from orinyx_mcp.server import build_server, shared

    class Refusing(FakeClient):
        def get_run(self, run_id):
            raise OrinyxApiError(404, "not_found", "No verification run with that id.")

    server = build_server(shared(Refusing()))
    with pytest.raises(Exception) as caught:  # noqa: PT011 - the SDK's ToolError moved in 2.x
        asyncio.run(server.call_tool("get_verification", {"run_id": RUN["runId"]}))
    assert type(caught.value).__name__ == "ToolError"
    assert "not_found (404): No verification run with that id." in str(caught.value)
    with pytest.raises(Exception) as caught:  # noqa: PT011
        asyncio.run(server.call_tool("export_verification", {"run_id": RUN["runId"], "fmt": "x"}))
    assert type(caught.value).__name__ == "ToolError" and "unknown format" in str(caught.value)


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("verify_medications", {"claims": []}),
        ("verify_order_text", {"orders": ["warfarin 5 mg"]}),
        ("get_verification", {"run_id": RUN["runId"]}),
    ],
)
async def test_malformed_context_reaches_the_agent_as_a_sanitized_tool_error(tool, arguments):
    pytest.importorskip("mcp")
    from orinyx_mcp.client import OrinyxClient
    from orinyx_mcp.server import build_server, shared

    data = {**RUN, "contextNotEvaluated": {**CONTEXT_JSON, "fields": 5}}
    with OrinyxClient(
        "https://orinyx.example",
        "synthetic",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data)),
    ) as client:
        server = build_server(shared(client))
        with pytest.raises(Exception) as caught:  # noqa: PT011 - the SDK's ToolError moved in 2.x
            await server.call_tool(tool, arguments)
    assert type(caught.value).__name__ == "ToolError"
    assert "invalid_response (200): unexpected run shape (fields: contextNotEvaluated)" in str(
        caught.value
    )
    assert CONTEXT_JSON["note"] not in str(caught.value)


def test_verify_order_text_passes_the_orders_through_unchanged():
    client = FakeClient()
    orders = ["wafarin 5 mb by intramuscular injection"]
    text = tools.verify_order_text(client, orders=orders, tool_name="acme-scribe")
    assert client.calls == [
        (
            "verify_orders",
            orders,
            {"tool_name": "acme-scribe", "tool_version": None, "check_interactions": False},
        )
    ]
    assert "| # | Claim | Part | Result |" in text
    assert RUN["runId"] in text


def test_what_a_calling_agent_is_told_about_verdicts_and_data():
    """Outside testers' agents read these strings and nothing else."""
    pytest.importorskip("mcp")
    from orinyx_mcp.server import INSTRUCTIONS, build_server, shared

    assert "treat it as unchecked, never as safe" in INSTRUCTIONS
    assert "not that the order is appropriate" in INSTRUCTIONS
    assert "synthetic test data only" in INSTRUCTIONS
    assert "never answer in its place" in INSTRUCTIONS
    assert "'unreadable' means the order cannot be read as written" in INSTRUCTIONS
    # Tester finding 2026-10-06: an agent suggested "warfarin 5 mg" and added unit reasons
    # Orinyx never returned. The only corrections an agent may repeat are Orinyx's own.
    assert "Never write a corrected, completed or re-spelled order yourself" in INSTRUCTIONS
    assert "never add a reason Orinyx did not return" in INSTRUCTIONS
    assert "only the suggestions Orinyx returned, word for word" in INSTRUCTIONS
    assert "does not address it" not in INSTRUCTIONS  # abstain has many causes
    server = build_server(shared(FakeClient()))
    verify = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "verify_medications"
    )
    assert "synthetic" in verify.description and "stored" in verify.description
    assert "verify_order_text" in verify.description
    order_text = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "verify_order_text"
    )
    assert "never correct, complete or re-spell" in order_text.description
    assert "synthetic" in order_text.description
    submit = next(
        tool for tool in server._tool_manager.list_tools() if tool.name == "submit_exam_answers"
    )
    # Tool descriptions are what a product reads at tools/list: the denial shape lives there.
    assert "{condition, asserted: false}" in submit.description


def _check_icons(icons) -> None:
    assert icons, "the server declared no icon"
    first = icons[0]
    assert first.mime_type == "image/svg+xml" and first.sizes == ["any"]
    prefix = "data:image/svg+xml;base64,"
    assert first.src.startswith(prefix)
    svg = base64.b64decode(first.src[len(prefix) :], validate=True).decode("utf-8")
    assert svg.lstrip().startswith("<svg") and "<title" in svg and "Orinyx</title>" in svg
    assert 'viewBox="0 0 1024 1024"' in svg and "#4FC3E8" in svg
    for icon in icons[1:]:
        assert icon.mime_type == "image/png" and icon.src.startswith("data:image/png;base64,")
        png = base64.b64decode(icon.src.split(",", 1)[1], validate=True)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        width = int.from_bytes(png[16:20], "big")
        assert icon.sizes == [f"{width}x{width}"]


async def test_initialize_declares_the_orinyx_star_icon_vector_first():
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    async with Client(build_server(shared(FakeClient())), mode="legacy") as client:
        _check_icons(client.server_info.icons)
        assert client.server_info.name == "orinyx"


async def test_the_gateway_server_declares_the_same_icon():
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.gateway import Gateway, GatewayConfig
    from orinyx_mcp.server import build_server

    config = GatewayConfig(
        url="https://other.example/mcp", tools=frozenset({"search"}), token="t", name="Acme"
    )
    server = build_server(lambda: None, gateway=Gateway(config))
    assert type(server).__name__ == "GatewayServer"
    async with Client(server, mode="legacy") as client:
        _check_icons(client.server_info.icons)

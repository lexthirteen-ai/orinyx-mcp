"""Sources card contract as seen by a connected MCP client."""

from copy import deepcopy

import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import VerificationResult

from tests.test_text import RUN
from tests.test_tools import FakeClient

URI = "ui://orinyx/sources-card"
MIME_TYPE = "text/html;profile=mcp-app"


class VerificationClient(FakeClient):
    def __init__(self, run):
        super().__init__()
        self.run = run

    def verify(self, claims, **kwargs):
        return VerificationResult.from_json(self.run)

    def get_run(self, run_id):
        return VerificationResult.from_json(self.run)


async def test_sources_card_resource_is_discoverable_and_has_no_network_origins():
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import NOT_FOR_CLINICAL_USE, build_server, shared

    async with Client(build_server(shared(FakeClient())), mode="legacy") as client:
        listed = (await client.list_tools()).tools
        linked = {tool.name: tool for tool in listed if (tool.meta or {}).get("ui")}
        assert set(linked) == {"verify_medications", "get_verification"}
        for tool in linked.values():
            assert tool.meta["ui"] == {"resourceUri": URI}
            assert tool.description.startswith(NOT_FOR_CLINICAL_USE)
        resource = next(r for r in (await client.list_resources()).resources if str(r.uri) == URI)
        assert resource.mime_type == MIME_TYPE
        (page,) = (await client.read_resource(URI)).contents
        assert page.mime_type == MIME_TYPE
        assert page.meta["ui"]["csp"] == {"connectDomains": [], "resourceDomains": []}


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("verify_medications", {"claims": []}),
        ("get_verification", {"run_id": RUN["runId"]}),
    ],
)
@pytest.mark.parametrize("cited", [True, False])
async def test_result_keeps_text_and_copies_only_attached_citations(name, arguments, cited):
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    run = deepcopy(RUN)
    primary, secondary, abstain = run["verdicts"]
    missing_url = {
        **deepcopy(secondary),
        "citation": {"source": "FDA", "section": "Warnings", "citation": "Label without a URL"},
    }
    duplicate = deepcopy(primary)
    abstain["citation"] = {
        "source": "DailyMed",
        "section": "Indications",
        "sourceId": "label-2",
        "citation": "<b>Prescribing information</b>",
        "url": "https://example.org/label#indications",
    }
    # Deliberately different from the text renderer's severity grouping. Raw claims, explanations
    # and run-level data must never supply extra links.
    run["verdicts"] = [abstain, secondary, primary, missing_url, duplicate]
    primary["explanation"] = "See https://example.org/uncited"
    secondary["citation"]["url"] = "http://example.org/legacy"
    if not cited:
        for verdict in run["verdicts"]:
            verdict["citation"] = None

    stub = VerificationClient(run)
    text = getattr(tools, name)(stub, **arguments)
    async with Client(build_server(shared(stub)), mode="legacy") as client:
        result = await client.call_tool(name, arguments)

    assert not result.is_error
    assert [block.text for block in result.content] == [text]
    assert result.structured_content == {"result": text}
    assert result.meta["ui"]["resourceUri"] == URI
    citations = result.meta["orinyx/sources"]
    if cited:
        assert citations == [
            abstain["citation"],
            {**secondary["citation"], "sourceId": None},
            primary["citation"],
            {**missing_url["citation"], "sourceId": None, "url": None},
            duplicate["citation"],
        ]
    else:
        assert citations == []

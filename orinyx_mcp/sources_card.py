"""Read-only MCP App resource and verification citation payload."""

from importlib import resources

from mcp.server.apps import Apps, ResourceCsp
from mcp.types import CallToolResult, TextContent

from orinyx_mcp.client import VerificationResult

SOURCES_URI = "ui://orinyx/sources-card"
SOURCES_UI_META = {"ui": {"resourceUri": SOURCES_URI}}


def sources_app() -> Apps:
    app = Apps()
    html = resources.files("orinyx_mcp").joinpath("assets/sources-card.html").read_text("utf-8")
    app.add_html_resource(
        SOURCES_URI,
        html,
        name="Cited sources",
        csp=ResourceCsp(connect_domains=[], resource_domains=[]),
    )
    return app


def with_sources(text: str, result: VerificationResult) -> CallToolResult:
    citations = [
        verdict.citation.model_dump(by_alias=True)
        for verdict in result.verdicts
        if verdict.citation is not None
    ]
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content={"result": text},
        _meta={**SOURCES_UI_META, "orinyx/sources": citations},
    )

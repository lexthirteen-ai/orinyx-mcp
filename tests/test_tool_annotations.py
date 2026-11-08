"""Every tool's title and behaviour hints as an MCP client reads them from tools/list (CHA-117).

Claude's connector directory requires a human-readable title and the applicable hints on each
tool. The expected values are written out here, not read from annotations.py, so a changed
hint fails this test until someone changes it here too, on purpose.
"""

import pytest

from tests.test_clean_errors import api_client, refusing

# name: (title, readOnlyHint, destructiveHint, idempotentHint); openWorldHint is false for all.
DEFAULT_TOOLS = {
    "verify_medications": ("Verify medication claims", False, False, False),
    "verify_order_text": ("Verify medication orders as written", False, False, False),
    "get_verification": ("Read a verification run", True, False, True),
    "get_accuracy": ("Read physician-review accuracy", True, False, True),
    "export_verification": ("Export a verification run", False, False, False),
    "find_otc_monographs": ("Find FDA OTC monographs", True, False, True),
    "get_otc_monograph": ("Read an FDA OTC monograph summary", True, False, True),
    "read_otc_monograph_section": ("Read FDA OTC monograph text", True, False, True),
    "find_fda_label": ("Find an FDA prescribing label", True, False, True),
    "read_fda_label_section": ("Read an FDA label section", True, False, True),
    "start_a_test": ("Choose a test", True, False, True),
    "get_next_exam_case": ("Get the next exam case", False, False, False),
    "get_exam_cases": ("Get every exam case", False, False, False),
    "submit_exam_answers": ("Submit exam answers", False, False, False),
    "finish_exam": ("Finish an exam", False, True, False),
    "get_exam_report": ("Read an exam report", True, False, True),
}
ARENA_TOOLS = {
    "start_arena_challenge": ("Start an Arena challenge", False, False, True),
    "submit_arena_answer": ("Submit an Arena answer", False, False, True),
    "start_arena_rematch": ("Start an Arena rematch", False, False, True),
    "get_arena_battle": ("Read an Arena battle", True, False, True),
    "get_arena_report": ("Read an Arena report", True, False, True),
}


async def _listed() -> dict[str, dict]:
    """tools/list through an in-memory MCP client, as the JSON a client receives."""
    pytest.importorskip("mcp")
    from mcp import Client
    from orinyx_mcp.server import build_server, shared

    client = api_client(refusing(503))
    try:
        async with Client(build_server(shared(client)), mode="legacy") as mcp_client:
            tools = (await mcp_client.list_tools()).tools
    finally:
        client.close()
    return {tool.name: tool.model_dump(by_alias=True, exclude_none=True) for tool in tools}


def _expected(table: dict) -> dict[str, dict]:
    return {
        name: {
            "title": title,
            "annotations": {
                "readOnlyHint": read_only,
                "destructiveHint": destructive,
                "idempotentHint": idempotent,
                "openWorldHint": False,
            },
        }
        for name, (title, read_only, destructive, idempotent) in table.items()
    }


def _metadata(listed: dict[str, dict]) -> dict[str, dict]:
    return {
        name: {"title": tool.get("title"), "annotations": tool.get("annotations")}
        for name, tool in listed.items()
    }


async def test_default_tools_list_carries_every_title_and_hint(monkeypatch):
    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    assert _metadata(await _listed()) == _expected(DEFAULT_TOOLS)


async def test_arena_tools_carry_their_titles_and_hints_when_enabled(monkeypatch):
    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    monkeypatch.setenv("ORINYX_ARENA_URL", "https://arena.orinyx.example")
    assert _metadata(await _listed()) == _expected(DEFAULT_TOOLS | ARENA_TOOLS)


def test_metadata_table_names_only_registered_tools():
    """A renamed or removed tool cannot leave a stale row behind."""
    pytest.importorskip("mcp")
    from orinyx_mcp.annotations import TOOL_METADATA

    assert set(TOOL_METADATA) == set(DEFAULT_TOOLS) | set(ARENA_TOOLS)


async def test_titles_are_human_readable_and_distinct(monkeypatch):
    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    monkeypatch.setenv("ORINYX_ARENA_URL", "https://arena.orinyx.example")
    titles = [tool["title"] for tool in (await _listed()).values()]
    assert len(set(titles)) == len(titles)
    assert all("_" not in title and title[0].isupper() for title in titles)

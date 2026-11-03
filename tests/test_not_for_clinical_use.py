"""Gate B15: the not-for-clinical-use statement, worded by the owner on 2026-10-31,
opens the server INSTRUCTIONS and every tool description, sits on the README's first screen and
in the release notes. Each is pinned to the exact text, so a later edit cannot drop or soften it."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

TOOL_TEXT = (
    "Not for clinical use. Orinyx checks medication claims against cited FDA label text for "
    "testing and evaluation only. Do not use its results to diagnose, treat, prescribe or make "
    "patient care decisions. Use synthetic test data only."
)
README_TEXT = (
    "Not for clinical use. Orinyx is a testing and evaluation tool that checks medication "
    "claims against cited FDA label text. It does not give medical advice, and its results must "
    'not be used for diagnosis, treatment or prescribing decisions. A "supported" result means '
    "one claim matches the cited label text, not that an order is safe or appropriate. Submit "
    "synthetic test data only, never real patient information."
)
NOTES_TEXT = (
    "This release is not for clinical use. Use it for testing and evaluation with synthetic data "
    "only. Results are not medical advice and must not guide patient care."
)
TOOL_COUNT = 16


def test_the_statement_is_the_constant():
    from orinyx_mcp.server import NOT_FOR_CLINICAL_USE

    assert NOT_FOR_CLINICAL_USE == TOOL_TEXT


def test_instructions_open_with_the_statement():
    from orinyx_mcp.server import INSTRUCTIONS

    assert INSTRUCTIONS.startswith(TOOL_TEXT + " ")


ARENA_TOOL_COUNT = 5


def _descriptions(server):
    return {tool.name: tool.description for tool in server._tool_manager.list_tools()}


def _assert_all_open_with_the_statement(descriptions):
    for name, description in descriptions.items():
        assert description.startswith(TOOL_TEXT), name
        # The statement is a prefix, never the whole description: each tool still says what it does.
        assert len(description) > len(TOOL_TEXT) + 1, name


def test_every_tool_description_opens_with_the_statement(monkeypatch):
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server

    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    descriptions = _descriptions(build_server(lambda: None))
    assert len(descriptions) == TOOL_COUNT, sorted(descriptions)
    _assert_all_open_with_the_statement(descriptions)


def test_arena_tools_open_with_the_statement_too(monkeypatch):
    """arena.py registers through its own function; the guard sits on the server, not the
    decorator, so that path is covered as well."""
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server

    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    descriptions = _descriptions(build_server(lambda: None))
    assert len(descriptions) == TOOL_COUNT + ARENA_TOOL_COUNT, sorted(descriptions)
    _assert_all_open_with_the_statement(descriptions)


def test_a_tool_registered_later_cannot_omit_the_statement(monkeypatch):
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server

    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    server = build_server(lambda: None)

    @server.tool()
    def later_tool() -> str:
        """Does a later thing."""
        return ""

    @server.tool(description="An explicit description.")
    def explicit_tool() -> str:
        return ""

    @server.tool(description=TOOL_TEXT + " Already opens with it.")
    def already_tool() -> str:
        return ""

    descriptions = _descriptions(server)
    assert descriptions["later_tool"] == TOOL_TEXT + " Does a later thing."
    assert descriptions["explicit_tool"] == TOOL_TEXT + " An explicit description."
    assert descriptions["already_tool"] == TOOL_TEXT + " Already opens with it."


def test_readme_first_screen_carries_the_statement():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    first_screen = text.split("\n## ", 1)[0]
    assert README_TEXT in first_screen


def test_release_notes_carry_the_statement():
    text = (ROOT / "docs" / "RELEASE_NOTES_2026-11-02.md").read_text(encoding="utf-8")
    head = text.split("\n## ", 1)[0]
    assert NOTES_TEXT in head

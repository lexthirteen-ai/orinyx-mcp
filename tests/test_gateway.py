"""The gateway to another MCP server: only the allowlist is offered, every tool and answer
says where it came from, an outage never hides Orinyx's own tools, and the caller's Orinyx
credential never leaves for the other server."""

import contextlib
import logging

import pytest

pytest.importorskip("mcp")

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool  # noqa: E402
from orinyx_mcp import gateway as gw  # noqa: E402
from orinyx_mcp.gateway import Gateway, GatewayConfig  # noqa: E402

from tests.test_http import GOOD, RecordingClient, _auth, _remote, _rpc  # noqa: E402

TOKEN = "downstream-service-token-0123456789"
SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


def _config(**overrides) -> GatewayConfig:
    values = {
        "url": "https://other.example/mcp",
        "tools": frozenset({"search"}),
        "token": TOKEN,
        "name": "Acme Search",
    }
    return GatewayConfig(**(values | overrides))


class FakeSession:
    """The other server: two tools across two pages, one of them not allowlisted."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self, params=None):
        if params is None:
            page = [Tool(name="search", description="Search Acme.", input_schema=SCHEMA)]
            return ListToolsResult(tools=page, next_cursor="2")
        return ListToolsResult(tools=[Tool(name="delete_all", input_schema={"type": "object"})])

    async def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return CallToolResult(content=[TextContent(type="text", text=f"found {arguments['q']}")])


def _connected(session: FakeSession, opened: list | None = None):
    @contextlib.asynccontextmanager
    async def connect():
        if opened is not None:
            opened.append(1)
        yield session

    return connect


def _down(grouped: bool = False):
    @contextlib.asynccontextmanager
    async def connect():
        exc = ConnectionError(f"https://other.example/mcp refused Bearer {TOKEN}")
        raise ExceptionGroup("unhandled errors in a TaskGroup", [exc]) if grouped else exc
        yield  # pragma: no cover

    return connect


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_only_allowlisted_tools_are_offered_renamed_labelled_and_schema_intact():
    tools = await Gateway(_config(), connect=_connected(FakeSession())).tools()
    assert [tool.name for tool in tools] == ["ext__search"]
    assert tools[0].description.startswith("[From Acme Search, an external service, not Orinyx.")
    assert tools[0].description.endswith("Search Acme.")
    assert tools[0].input_schema == SCHEMA


async def test_the_list_is_cached_then_refreshed():
    clock, opened = Clock(), []
    gateway = Gateway(_config(), connect=_connected(FakeSession(), opened), clock=clock)
    await gateway.tools()
    await gateway.tools()
    assert len(opened) == 1
    clock.now += gw.LIST_TTL_SECONDS + 1
    await gateway.tools()
    assert len(opened) == 2


async def test_a_call_is_relayed_and_headed_with_where_it_came_from():
    session = FakeSession()
    result = await Gateway(_config(), connect=_connected(session)).call("ext__search", {"q": "x"})
    assert not result.is_error
    assert [part.text for part in result.content] == [
        "From Acme Search, not from Orinyx:",
        "found x",
    ]
    assert session.calls == [("search", {"q": "x"})]


async def test_a_tool_off_the_allowlist_is_refused_even_though_the_other_server_has_it():
    session = FakeSession()
    result = await Gateway(_config(), connect=_connected(session)).call("ext__delete_all", {})
    assert result.is_error and "Unknown tool" in result.content[0].text
    assert session.calls == []


async def test_an_outage_lists_nothing_briefly_and_reads_as_an_outage(caplog):
    clock = Clock()
    gateway = Gateway(_config(), connect=_down(), clock=clock)
    with caplog.at_level(logging.WARNING, logger="orinyx_mcp.gateway"):
        assert await gateway.tools() == []
        result = await gateway.call("ext__search", {"q": "x"})
    assert result.is_error
    assert result.content[0].text == "Acme Search could not be reached: ConnectionError"
    assert TOKEN not in caplog.text and TOKEN not in repr(gateway.config)
    gateway._connect = _connected(FakeSession())
    assert await gateway.tools() == []  # the failure is remembered for a moment
    clock.now += gw.FAILURE_TTL_SECONDS + 1
    assert [tool.name for tool in await gateway.tools()] == ["ext__search"]


async def test_an_outage_names_the_real_failure_not_the_sdks_wrapper():
    result = await Gateway(_config(), connect=_down(grouped=True)).call("ext__search", {})
    assert result.content[0].text == "Acme Search could not be reached: ConnectionError"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": "http://other.example/mcp"}, "https"),
        ({"tools": frozenset()}, "at least one tool"),
        ({"tools": frozenset({"bad name"})}, "not tool names"),
        ({"prefix": "Ext_"}, "PREFIX"),
    ],
)
def test_a_bad_configuration_is_refused(overrides, message):
    with pytest.raises(ValueError, match=message):
        _config(**overrides)


def test_the_environment_turns_it_on_or_leaves_it_off():
    assert GatewayConfig.from_env({}) is None
    config = GatewayConfig.from_env(
        {
            "DOWNSTREAM_MCP_URL": "http://localhost:9000/mcp",
            "DOWNSTREAM_MCP_TOOLS": " echo , search ,",
        }
    )
    assert config.tools == {"echo", "search"} and config.prefix == "ext"
    assert config.token is None and config.label == "localhost"


async def test_a_connector_lists_both_and_routes_each_call_to_its_owner():
    session = FakeSession()
    gateway = Gateway(_config(), connect=_connected(session))
    async with _remote(gateway=gateway) as remote:
        listed = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(GOOD))
        tools = {tool["name"]: tool for tool in listed.json()["result"]["tools"]}
        assert {"verify_medications", "ext__search"} <= set(tools)
        assert "ext__delete_all" not in tools
        assert tools["ext__search"]["inputSchema"] == SCHEMA

        call = _rpc("tools/call", {"name": "ext__search", "arguments": {"q": "warfarin"}})
        result = (await remote.post("/mcp", json=call, headers=_auth(GOOD))).json()["result"]
        assert not result.get("isError")
        assert result["content"][1]["text"] == "found warfarin"
        assert RecordingClient.built == []  # Orinyx's API was not involved

        call = _rpc("tools/call", {"name": "get_verification", "arguments": {"run_id": "r"}})
        await remote.post("/mcp", json=call, headers=_auth(GOOD))
        assert [credential for credential, _ in RecordingClient.built] == [GOOD]
        assert session.calls == [("search", {"q": "warfarin"})]


async def test_the_callers_orinyx_credential_never_reaches_the_other_server(monkeypatch):
    import httpx2

    built: list[dict] = []

    class Recording:
        def __init__(self, **kwargs) -> None:
            built.append(kwargs)

        async def __aenter__(self):
            raise ConnectionError("stop here")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(httpx2, "AsyncClient", Recording)
    async with _remote(gateway=Gateway(_config())) as remote:
        call = _rpc("tools/call", {"name": "ext__search", "arguments": {"q": "x"}})
        result = (await remote.post("/mcp", json=call, headers=_auth(GOOD))).json()["result"]
    assert result["isError"]
    assert built and all(
        kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"} for kwargs in built
    )
    assert GOOD not in repr(built)


def test_the_instructions_name_the_other_service_only_when_connected():
    from orinyx_mcp.server import INSTRUCTIONS, build_server

    plain = build_server(lambda: None)
    joined = build_server(lambda: None, gateway=Gateway(_config()))
    assert plain.instructions == INSTRUCTIONS
    assert "ext__ come from Acme Search" in joined.instructions


def test_a_prefix_that_would_shadow_an_orinyx_tool_is_refused(monkeypatch):
    from orinyx_mcp.server import build_server

    gateway = Gateway(_config())
    monkeypatch.setattr(gateway, "owns", lambda name: name == "start_a_test")
    with pytest.raises(ValueError, match="collides"):
        build_server(lambda: None, gateway=gateway)

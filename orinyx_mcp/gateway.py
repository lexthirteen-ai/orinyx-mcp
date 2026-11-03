"""A gateway to ONE other remote MCP server: its allowlisted tools appear beside Orinyx's own,
renamed `<prefix>__<name>` and labelled as another service's, never as an Orinyx check.

Configuration is the environment only; with DOWNSTREAM_MCP_URL unset there is no gateway.

| Variable                    | Meaning                                                      |
|-----------------------------|--------------------------------------------------------------|
| DOWNSTREAM_MCP_URL          | the other server's Streamable HTTP endpoint (https; plain    |
|                             | http only for localhost)                                     |
| DOWNSTREAM_MCP_TOKEN        | optional; the bearer THIS service presents there. One key    |
|                             | for every caller: the other server sees Orinyx, not them     |
| DOWNSTREAM_MCP_TOOLS        | comma-separated names of the tools to offer; required        |
| DOWNSTREAM_MCP_PREFIX       | the name prefix (default `ext`): `ext__search`               |
| DOWNSTREAM_MCP_NAME         | how agents are told where a tool comes from (default: host)  |

The caller's own Orinyx credential never leaves for the other server, and the hop headers
are not sent there: the session is built from DOWNSTREAM_MCP_TOKEN alone. The service is
stateless, so each call opens its own session; the tool list is cached briefly."""

import asyncio
import contextlib
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from orinyx_mcp.config import ConfigError, _https_or_local

logger = logging.getLogger("orinyx_mcp.gateway")

LIST_TTL_SECONDS = 300.0
FAILURE_TTL_SECONDS = 30.0
TIMEOUT_SECONDS = 30.0
_PREFIX = re.compile(r"[a-z][a-z0-9]{0,15}")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}")


@dataclass(frozen=True)
class GatewayConfig:
    url: str
    tools: frozenset[str]
    token: str | None = None
    prefix: str = "ext"
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or urlsplit(self.url).hostname or "another service"

    def __repr__(self) -> str:  # the token stays out of any log line or traceback
        return (
            f"GatewayConfig(url={self.url!r}, tools={sorted(self.tools)!r}, prefix={self.prefix!r})"
        )

    def __post_init__(self) -> None:
        if not _https_or_local(self.url):
            raise ConfigError(
                "DOWNSTREAM_MCP_URL must be an https URL (plain http only for localhost)"
            )
        if not self.tools:
            raise ConfigError("DOWNSTREAM_MCP_TOOLS must name at least one tool to offer")
        bad = sorted(name for name in self.tools if not _TOOL_NAME.fullmatch(name))
        if bad:
            raise ConfigError(f"DOWNSTREAM_MCP_TOOLS has names that are not tool names: {bad}")
        if not _PREFIX.fullmatch(self.prefix):
            raise ConfigError("DOWNSTREAM_MCP_PREFIX must be 1-16 lowercase letters or digits")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "GatewayConfig | None":
        env = os.environ if env is None else env
        url = (env.get("DOWNSTREAM_MCP_URL") or "").strip()
        if not url:
            return None
        tools = frozenset(
            name.strip()
            for name in (env.get("DOWNSTREAM_MCP_TOOLS") or "").split(",")
            if name.strip()
        )
        return cls(
            url=url,
            tools=tools,
            token=env.get("DOWNSTREAM_MCP_TOKEN") or None,
            prefix=(env.get("DOWNSTREAM_MCP_PREFIX") or "ext").strip(),
            name=(env.get("DOWNSTREAM_MCP_NAME") or "").strip(),
        )


def _connector(config: GatewayConfig) -> Callable[[], contextlib.AbstractAsyncContextManager]:
    """A real session to the other server, carrying only this service's own token."""

    @contextlib.asynccontextmanager
    async def connect() -> AsyncIterator[Any]:
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {config.token}"} if config.token else {}
        async with (
            httpx2.AsyncClient(headers=headers, timeout=TIMEOUT_SECONDS) as http,
            streamable_http_client(config.url, http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            yield session

    return connect


def _text(text: str):
    from mcp.types import TextContent

    return TextContent(type="text", text=text)


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        *,
        connect: Callable[[], contextlib.AbstractAsyncContextManager] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._connect = connect or _connector(config)
        self._clock = clock
        self._lock = asyncio.Lock()
        self._listed: list | None = None
        self._until = 0.0

    @property
    def prefix(self) -> str:
        return f"{self.config.prefix}__"

    @property
    def instructions(self) -> str:
        return (
            f" Tools whose names start with {self.prefix} come from {self.config.label}, another "
            "service: their output is not an Orinyx check or verdict and must never be "
            "presented as one."
        )

    def failure(self, exc: BaseException) -> str:
        # The type only: an exception's text can carry a URL or header, never the token. The
        # SDK's task groups wrap the real failure (ConnectError, HTTPStatusError) in a group.
        while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
            exc = exc.exceptions[0]
        return f"{self.config.label} could not be reached: {type(exc).__name__}"

    async def tools(self) -> list:
        """The allowlisted tools, renamed and labelled; [] when the other server is down, so
        Orinyx's own tools always list."""
        async with self._lock:
            if self._listed is not None and self._clock() < self._until:
                return list(self._listed)
            try:
                found = await self._fetch()
                self._until = self._clock() + LIST_TTL_SECONDS
            except Exception as exc:  # noqa: BLE001 - a downstream outage must not hide Orinyx
                logger.warning("gateway tool list failed: %s", self.failure(exc))
                found = []
                self._until = self._clock() + FAILURE_TTL_SECONDS
            self._listed = found
            return list(found)

    async def _fetch(self) -> list:
        from mcp.types import PaginatedRequestParams

        tools, cursor = [], None
        async with self._connect() as session:
            while True:
                params = PaginatedRequestParams(cursor=cursor) if cursor else None
                page = await session.list_tools(params=params)
                tools += page.tools
                cursor = page.next_cursor
                if not cursor:
                    break
        note = (
            f"[From {self.config.label}, an external service, not Orinyx. Its output is not an "
            "Orinyx check or verdict.]"
        )
        return [
            tool.model_copy(
                update={
                    "name": self.prefix + tool.name,
                    "description": f"{note} {tool.description or ''}".rstrip(),
                }
            )
            for tool in tools
            if tool.name in self.config.tools
        ]

    def owns(self, name: str) -> bool:
        return name.startswith(self.prefix)

    async def call(self, name: str, arguments: dict[str, Any]):
        """Call one allowlisted tool on the other server; its answer comes back headed with
        where it came from. A refusal or an outage is a readable tool error."""
        from mcp.types import CallToolResult

        tool = name.removeprefix(self.prefix)
        if tool not in self.config.tools:
            return CallToolResult(content=[_text(f"Unknown tool: {name}")], is_error=True)
        try:
            async with self._connect() as session:
                result = await session.call_tool(tool, arguments)
        except Exception as exc:  # noqa: BLE001 - reported to the agent, never raised
            logger.warning("gateway call %s failed: %s", tool, self.failure(exc))
            return CallToolResult(content=[_text(self.failure(exc))], is_error=True)
        if not isinstance(result, CallToolResult):
            return CallToolResult(
                content=[
                    _text(f"{self.config.label} answered in a form this service cannot relay")
                ],
                is_error=True,
            )
        header = _text(f"From {self.config.label}, not from Orinyx:")
        return result.model_copy(update={"content": [header, *result.content]})


__all__ = ["Gateway", "GatewayConfig"]

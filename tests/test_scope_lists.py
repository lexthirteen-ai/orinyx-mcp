"""Two lists of scopes, different on purpose.

The network server advertises six scopes in its protected-resource document: everything a
sign-in through a connector may be granted. A sign-in from the command line asks for four:
verification and Arena, never the two exam scopes. Both lists are called `SCOPES`, in two
modules, so a tidy-up that merged them would either give the CLI the exam scopes or hide them
from connectors. This file pins each list, the difference between them, and where each is used.
"""

import httpx
import pytest
from orinyx_mcp import credentials, login
from orinyx_mcp import http as mcp_http
from orinyx_mcp.config import Config

CLI_SIGN_IN = {"verify:read", "verify:write", "arena:read", "arena:write"}
EXAMS = {"benchmark:read", "benchmark:write"}


def test_a_cli_sign_in_asks_for_exactly_these_four():
    assert set(credentials.SCOPES) == CLI_SIGN_IN
    assert len(credentials.SCOPES) == len(CLI_SIGN_IN)


def test_the_network_server_advertises_exactly_these_six():
    assert set(mcp_http.SCOPES) == CLI_SIGN_IN | EXAMS
    assert len(mcp_http.SCOPES) == len(CLI_SIGN_IN | EXAMS)


def test_the_two_lists_differ_by_exactly_the_two_exam_scopes():
    assert set(mcp_http.SCOPES) - set(credentials.SCOPES) == EXAMS
    assert set(credentials.SCOPES) - set(mcp_http.SCOPES) == set()


def test_the_sign_in_module_uses_the_cli_list_and_not_the_network_servers():
    assert login.SCOPES is credentials.SCOPES
    assert login.SCOPES is not mcp_http.SCOPES


async def test_the_network_server_publishes_its_own_six():
    """The document a connector reads before sign-in, served by the real application."""
    pytest.importorskip("mcp")
    config = Config(
        public_url="https://mcp.example",
        api_url="https://api.example",
        issuer_url="https://api.example",
        hop_secret="synthetic-hop-" * 4,
    )
    refuse = httpx.MockTransport(lambda request: httpx.Response(401))
    async with httpx.AsyncClient(transport=refuse) as api:
        wrapped, app = mcp_http.build_app(config, client_for=lambda: None, http=api)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=wrapped)
            async with httpx.AsyncClient(transport=transport, base_url=config.origin) as remote:
                document = await remote.get("/.well-known/oauth-protected-resource/mcp")
    assert document.status_code == 200
    assert document.json()["scopes_supported"] == list(mcp_http.SCOPES)

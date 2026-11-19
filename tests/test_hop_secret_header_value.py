"""A hop secret the server starts with is one it can send.

`ORINYX_HOP_SECRET` travels to the API as the value of one HTTP header, on every request this
service makes there. A value no header can carry (a line break or a NUL inside it, a space or a
tab at either end) used to pass start-up: the service reported healthy and then admitted nobody,
because the HTTP library refused to write the request. Start-up refuses such a value and names
the setting. The other half is proved over a real connection on 127.0.0.1: a secret start-up
accepts arrives at the API unchanged. Every value here is synthetic.
"""

import http.server
import json
import os
import string
import threading
from dataclasses import replace

import httpx
import pytest
from orinyx_mcp import http as mcp_http
from orinyx_mcp.config import Config, ConfigError

BASE = {"MCP_PUBLIC_URL": "https://mcp.example", "ORINYX_API_URL": "https://api.example"}
BODY = "synthetic-hop-" * 4
# Written out rather than imported, so a change to the wording fails here.
REFUSED = (
    "ORINYX_HOP_SECRET must not contain a line break or a NUL, or begin or end with a space or tab"
)
UNSENDABLE = {
    "a trailing line feed": BODY + "\n",
    "a trailing carriage return and line feed": BODY + "\r\n",
    "a line feed inside": BODY + "\n" + BODY,
    "a carriage return inside": BODY + "\r" + BODY,
    "a form feed inside": BODY + "\x0c" + BODY,
    "a vertical tab inside": BODY + "\x0b" + BODY,
    "a NUL inside": BODY + "\x00" + BODY,
    "a leading space": " " + BODY,
    "a trailing space": BODY + " ",
    "a leading tab": "\t" + BODY,
    "a trailing tab": BODY + "\t",
    "nothing but spaces": " " * 40,
}
SENDABLE = {
    "letters, digits and hyphens": BODY,
    "a space inside": BODY + " " + BODY,
    "a tab inside": BODY + "\t" + BODY,
    "every ASCII symbol": BODY + string.punctuation,
}


@pytest.mark.parametrize("case", list(UNSENDABLE))
def test_a_secret_no_header_can_carry_is_refused_at_start_up(case):
    with pytest.raises(ConfigError) as caught:
        Config.from_env(BASE | {"ORINYX_HOP_SECRET": UNSENDABLE[case]})
    assert str(caught.value) == REFUSED


def test_a_config_built_directly_refuses_it_too():
    config = Config.from_env(BASE | {"ORINYX_HOP_SECRET": BODY})
    with pytest.raises(ConfigError) as caught:
        replace(config, hop_secret=BODY + "\n")
    assert str(caught.value) == REFUSED


def test_the_server_prints_one_line_and_builds_nothing(monkeypatch, capsys):
    """`orinyx-mcp` with a secret that ends in a pasted line break: exit 1 and one line that
    names the setting and repeats no part of its value. Nothing is built or served."""

    def must_not_build(*args, **kwargs):
        raise AssertionError("the application must not be built with this hop secret")

    monkeypatch.setattr(mcp_http, "build_app", must_not_build)
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)
    for name, value in (BASE | {"ORINYX_HOP_SECRET": BODY + "\n"}).items():
        monkeypatch.setenv(name, value)
    assert mcp_http.serve([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", REFUSED + "\n")


class _Api(http.server.BaseHTTPRequestHandler):
    """Stands in for the API's credential check on 127.0.0.1 and records the hop header."""

    received: list[str | None] = []

    def do_GET(self):
        type(self).received.append(self.headers.get(mcp_http.LOOPBACK_HEADER))
        body = json.dumps(
            {
                "active": True,
                "credentialType": "api_key",
                "scopes": ["verify:read"],
                "subject": "synthetic",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def api():
    _Api.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("case", list(SENDABLE))
async def test_a_secret_start_up_accepts_reaches_the_api_unchanged(case, api):
    """The credential check this service makes for every caller, over a real connection: the
    HTTP library writes the header, and the API reads the same value."""
    pytest.importorskip("mcp")
    secret = SENDABLE[case]
    config = Config.from_env(BASE | {"ORINYX_API_URL": api, "ORINYX_HOP_SECRET": secret})
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        verifier = mcp_http.IntrospectionVerifier(
            config.api_url,
            config.resource,
            client,
            extra_headers=lambda: mcp_http.caller_headers(config),
        )
        access = await verifier.verify_token("ork_live_" + "x")
    assert access is not None
    assert _Api.received == [secret]

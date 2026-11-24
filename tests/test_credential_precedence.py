"""Which credential a request carries, and where a saved sign-in may go.

1. `ORINYX_API_KEY` wins. With a key in the environment, the commands that send data and the
   stdio server use the key and never open the keychain, even when it holds a sign-in. With no
   `ORINYX_API_URL`, the key goes to the default origin.
2. A saved sign-in belongs to one API origin. With no key, the keychain is asked only about the
   origin in `ORINYX_API_URL` (or the default origin when none is set); a sign-in saved for any
   other origin is never offered.
3. The network server never reads the sign-in store. Its REST clients carry the caller's own
   credential and no token provider.

The keychain here is a stand-in that records every call made to it. All values are synthetic.
"""

import ast
import os
from pathlib import Path

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from orinyx_mcp import __main__ as stdio
from orinyx_mcp import cli, credentials
from orinyx_mcp import http as mcp_http
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.config import Config
from orinyx_mcp.credentials import LoginRecord, SavedLogin

API = "https://api.example"
ELSEWHERE = "https://other.example"
KEY = "synthetic-key"
RUN_ID = "11111111-2222-4333-8444-555555555555"
MISSING = "Set ORINYX_API_URL and ORINYX_API_KEY in the environment.\n"
# One argument list per command that sends data. None of them gets as far as a request.
DATA_COMMANDS = [
    ["verify", "--file", "unused.json"],
    ["get", RUN_ID],
    ["accuracy", RUN_ID],
    ["export", RUN_ID, "--out", "unused.csv"],
    ["observe", "unused.txt"],
]


class Keychain:
    """Stands in for the OS keychain: a dict, and a list of every lookup made."""

    def __init__(self):
        self.data = {}
        self.lookups = []

    def __call__(self):
        return self

    def get_password(self, service, account):
        self.lookups.append(account)
        return self.data.get((service, account))

    def hold(self, origin):
        record = LoginRecord(
            resource=origin,
            client=OAuthClientInformationFull(
                client_id="client-a",
                redirect_uris=["http://127.0.0.1:9876/callback"],
                token_endpoint_auth_method="none",
            ),
            tokens=OAuthToken(
                access_token="ork_oat_" + "a",
                refresh_token="ork_ort_" + "r",
                scope="verify:read verify:write",
                expires_in=3600,
            ),
            expires_at=0,
        )
        self.data["orinyx-cli", origin] = record.model_dump_json()


@pytest.fixture
def keychain(monkeypatch, tmp_path):
    fake = Keychain()
    monkeypatch.setattr(credentials, "_native_keyring", fake)
    monkeypatch.setattr(credentials.Path, "home", lambda: tmp_path)
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)
    return fake


class _Built(Exception):
    """Raised by the stand-in client factory: the test stops where a client would be built."""


def _recording_factory(built):
    def factory(url, key, **kwargs):
        built.append((url, key, kwargs))
        raise _Built

    return factory


def _must_not_build(*args, **kwargs):
    raise AssertionError("no client may be built here")


# --- 1. the key wins ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", DATA_COMMANDS, ids=[argv[0] for argv in DATA_COMMANDS])
def test_with_a_key_the_cli_uses_it_and_never_opens_the_keychain(argv, keychain, monkeypatch):
    keychain.hold(API)
    monkeypatch.setenv("ORINYX_API_URL", API)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    built = []
    with pytest.raises(_Built):
        cli.main(argv, client_factory=_recording_factory(built))
    assert built == [(API, KEY, {})]
    assert keychain.lookups == []


def test_with_a_key_the_stdio_server_uses_it_and_never_opens_the_keychain(
    keychain, monkeypatch, capsys
):
    from orinyx_mcp import client as client_module
    from orinyx_mcp import server

    keychain.hold(API)
    monkeypatch.setenv("ORINYX_API_URL", API)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    built = []

    class Client(OrinyxClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append((args, kwargs, self))

    class Server:
        def run(self):
            pass

    monkeypatch.setattr(client_module, "OrinyxClient", Client)
    monkeypatch.setattr(server, "build_server", lambda *args, **kwargs: Server())
    assert stdio.main([]) == 0
    [(args, kwargs, client)] = built
    assert (args, kwargs) == ((API, KEY), {})
    assert client._token_provider is None
    assert client._http.headers["Authorization"] == f"Bearer {KEY}"
    assert keychain.lookups == []
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("argv", DATA_COMMANDS, ids=[argv[0] for argv in DATA_COMMANDS])
def test_with_a_key_and_no_url_the_cli_uses_the_default_api(argv, keychain, monkeypatch):
    keychain.hold(credentials.DEFAULT_API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    built = []
    with pytest.raises(_Built):
        cli.main(argv, client_factory=_recording_factory(built))
    assert built == [(credentials.DEFAULT_API_URL, KEY, {})]
    assert keychain.lookups == []


def test_with_a_key_and_no_url_the_stdio_server_uses_the_default_api(keychain, monkeypatch, capsys):
    from orinyx_mcp import client as client_module
    from orinyx_mcp import server

    keychain.hold(credentials.DEFAULT_API_URL)
    monkeypatch.setenv("ORINYX_API_KEY", KEY)
    built = []

    class Client(OrinyxClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            built.append((args, kwargs, self))

    class Server:
        def run(self):
            pass

    monkeypatch.setattr(client_module, "OrinyxClient", Client)
    monkeypatch.setattr(server, "build_server", lambda *args, **kwargs: Server())
    assert stdio.main([]) == 0
    [(args, kwargs, client)] = built
    assert (args, kwargs) == ((credentials.DEFAULT_API_URL, KEY), {})
    assert client._token_provider is None
    assert keychain.lookups == []
    assert capsys.readouterr().out == ""


# --- 2. a saved sign-in belongs to one origin --------------------------------------------------


def test_without_a_key_the_cli_uses_the_sign_in_saved_for_the_configured_origin(
    keychain, monkeypatch
):
    """The control for the refusals below: the same keychain, asked about the origin it holds."""
    keychain.hold(API)
    keychain.hold(credentials.DEFAULT_API_URL)
    monkeypatch.setenv("ORINYX_API_URL", API)
    built = []
    with pytest.raises(_Built):
        cli.main(["get", RUN_ID], client_factory=_recording_factory(built))
    [(url, key, kwargs)] = built
    assert (url, key, list(kwargs)) == (API, "", ["token_provider"])
    assert isinstance(kwargs["token_provider"], SavedLogin)
    assert kwargs["token_provider"].store.resource == API
    assert keychain.lookups == [API]


@pytest.mark.parametrize("argv", DATA_COMMANDS, ids=[argv[0] for argv in DATA_COMMANDS])
def test_a_sign_in_saved_for_another_origin_is_never_offered_by_the_cli(
    argv, keychain, monkeypatch, capsys
):
    keychain.hold(API)
    keychain.hold(credentials.DEFAULT_API_URL)
    monkeypatch.setenv("ORINYX_API_URL", ELSEWHERE)
    assert cli.main(argv, client_factory=_must_not_build) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", MISSING)
    assert keychain.lookups == [ELSEWHERE]


def test_a_sign_in_saved_for_another_origin_is_never_offered_by_the_stdio_server(
    keychain, monkeypatch, capsys
):
    from orinyx_mcp import client as client_module

    keychain.hold(API)
    keychain.hold(credentials.DEFAULT_API_URL)
    monkeypatch.setenv("ORINYX_API_URL", ELSEWHERE)
    monkeypatch.setattr(client_module, "OrinyxClient", _must_not_build)
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", MISSING)
    assert keychain.lookups == [ELSEWHERE]


def test_with_no_url_only_the_default_origin_is_looked_up(keychain, capsys):
    keychain.hold(API)
    assert cli.main(["get", RUN_ID], client_factory=_must_not_build) == 1
    assert stdio.main([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", MISSING * 2)
    assert keychain.lookups == [credentials.DEFAULT_API_URL] * 2


# --- 3. the network server never reads the store -----------------------------------------------


def test_the_network_server_module_never_names_the_sign_in_store():
    tree = ast.parse(Path(mcp_http.__file__).read_text(encoding="utf-8"))
    imported, names = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.keyword):
            names.add(node.arg)
    assert "orinyx_mcp.client" in imported  # the module was read
    for module in imported:
        assert module not in ("orinyx_mcp.credentials", "orinyx_mcp.login"), module
        assert module.split(".")[0] != "keyring", module
    assert not names & {"token_provider", "saved_login", "SavedLogin", "CredentialStore"}


def test_the_network_servers_clients_carry_the_callers_credential_and_no_token_provider(
    keychain, monkeypatch
):
    from orinyx_mcp import contract

    keychain.hold(API)
    caller = "ork_live_" + "caller"
    monkeypatch.setattr(mcp_http, "caller_credential", lambda: caller)
    monkeypatch.setattr(contract, "check_in_background", lambda client: None)
    config = Config(
        public_url="https://mcp.example",
        api_url=API,
        issuer_url=API,
        hop_secret="synthetic-hop-" * 4,
    )
    sent = []

    def handler(request):
        sent.append(request.headers["Authorization"])
        return httpx.Response(200, json={"data": []})

    pool = mcp_http.ClientPool(config, transport=httpx.MockTransport(handler))
    assert isinstance(mcp_http.client_factory(config), mcp_http.ClientPool)
    view = pool()
    try:
        assert view._token_provider is None
        view.labels("warfarin")
    finally:
        view.close()
        pool.close()
    assert sent == [f"Bearer {caller}"]
    assert keychain.lookups == []

"""Native OAuth runs against synthetic wire responses and a real loopback callback."""

import base64
import hashlib
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from orinyx_mcp import cli, credentials, login
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.credentials import AuthError, CredentialStore, LoginRecord, SavedLogin
from pydantic import AnyUrl

API = "https://api.example"
ACCESS = "ork_oat_a"
REFRESH = "ork_ort_r"


@pytest.fixture
def store(monkeypatch, tmp_path):
    data = {}

    class Backend:
        def get_password(self, service, account):
            return data.get((service, account))

        def set_password(self, service, account, value):
            data[service, account] = value

        def delete_password(self, service, account):
            data.pop((service, account), None)

    monkeypatch.setattr(credentials, "_native_keyring", Backend)
    monkeypatch.setattr(credentials.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("ORINYX_API_KEY", raising=False)
    monkeypatch.setenv("ORINYX_API_URL", API)
    return CredentialStore(API)


def record(*, expires_at=0, resource=API):
    return LoginRecord(
        resource=resource,
        client=OAuthClientInformationFull(
            client_id="client-a",
            redirect_uris=["http://127.0.0.1:9876/callback"],
            token_endpoint_auth_method="none",
        ),
        tokens=OAuthToken(
            access_token=ACCESS,
            refresh_token=REFRESH,
            scope="verify:read arena:write",
            expires_in=3600,
        ),
        expires_at=expires_at,
    )


@pytest.mark.parametrize("no_browser", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def test_login_pkce_resource_callback_and_logout(store, monkeypatch, capsys, no_browser, pending):
    seen = {}
    requests = []
    occupied = login.Callback("other") if pending else None
    if occupied:
        saved = record()
        saved.client.redirect_uris = [AnyUrl(occupied.uri)]
        saved.tokens = None
        saved.revocation_token = REFRESH
        store.save(saved)

    def respond(request):
        requests.append(request)
        if request.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(
                200,
                json={
                    "issuer": API,
                    "authorization_endpoint": API + "/authorize",
                    "token_endpoint": API + "/token",
                    "registration_endpoint": API + "/register",
                    "revocation_endpoint": API + "/revoke",
                    "response_types_supported": ["code"],
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if request.url.path == "/register":
            body = json.loads(request.content)
            assert body["scope"] == " ".join(credentials.SCOPES)
            return httpx.Response(201, json=body | {"client_id": "client-a"})
        form = parse_qs(request.content.decode())
        if request.url.path == "/token":
            assert form["resource"] == [API]
            if form["grant_type"] == ["authorization_code"]:
                digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
                challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                assert challenge == seen["code_challenge"][0]
                assert form["redirect_uri"] == seen["redirect_uri"]
            return httpx.Response(200, json=record().tokens.model_dump())
        assert request.url.path == "/revoke"
        assert form["token"] == [REFRESH]
        return httpx.Response(200)

    session_type = login.OAuthSession
    monkeypatch.setattr(
        login, "OAuthSession", lambda url: session_type(url, transport=httpx.MockTransport(respond))
    )
    browser_threads = []

    def open_browser(url):
        seen.update(parse_qs(urlsplit(url).query))
        assert seen["resource"] == [API]
        assert seen["code_challenge_method"] == ["S256"]
        thread = threading.Thread(
            target=lambda: httpx.get(
                seen["redirect_uri"][0], params={"code": "code-a", "state": seen["state"][0]}
            )
        )
        thread.start()
        browser_threads.append(thread)
        return True

    def print_url(value, **kwargs):
        print(value, **kwargs)
        if no_browser:
            open_browser(value.removeprefix("Sign in on this device: "))

    monkeypatch.setattr(login, "print", print_url, raising=False)
    monkeypatch.setattr(
        login.webbrowser,
        "open",
        (lambda _: pytest.fail("--no-browser opened a browser")) if no_browser else open_browser,
    )
    try:
        assert cli.main(["login", "--no-browser"] if no_browser else ["login"]) == 0
    finally:
        if occupied:
            occupied.close()
    for thread in browser_threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    saved = store.load()
    assert saved.tokens.access_token == ACCESS
    assert saved.revocation_token is None
    assert saved.expires_at > time.time()
    assert cli.main(["status", "--json"]) == 0
    assert cli.main(["logout"]) == 0
    assert store.load() is None
    captured = capsys.readouterr()
    assert ACCESS not in captured.out + captured.err
    assert REFRESH not in captured.out + captured.err
    assert sum(request.url.path == "/revoke" for request in requests) == (2 if pending else 1)


def test_refresh_is_lazy_and_shared_between_client_views(store, monkeypatch):
    store.save(record())
    refreshed = []

    class Session:
        def __init__(self, url):
            assert url == API

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def refresh(self, old, tokens):
            assert store.load().tokens is None
            assert tokens.refresh_token == REFRESH
            refreshed.append(True)
            fresh = record(expires_at=time.time() + 3600)
            fresh.tokens.access_token = "ork_oat_b"
            return fresh

    monkeypatch.setattr(login, "OAuthSession", Session)
    sent = []

    def respond(request):
        sent.append(request.headers["Authorization"])
        return httpx.Response(200, json={})

    with OrinyxClient(
        API, "", token_provider=SavedLogin(store), transport=httpx.MockTransport(respond)
    ) as client:
        assert refreshed == []
        client._request("POST", "/v1/example")
        with client.bound({"X-Request-ID": "request-a"}) as view:
            view._request("GET", "/v1/example")
    assert refreshed == [True]
    assert sent == ["Bearer ork_oat_b", "Bearer ork_oat_b"]


def test_two_threads_do_not_replay_the_refresh_token(store, monkeypatch):
    store.save(record())
    calls = []

    class Session:
        def __init__(self, url):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def refresh(self, old, previous):
            calls.append(previous.refresh_token)
            time.sleep(0.05)
            return record(expires_at=time.time() + 3600)

    monkeypatch.setattr(login, "OAuthSession", Session)
    tokens = []
    threads = [
        threading.Thread(target=lambda: tokens.append(SavedLogin(store)())) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert tokens == [ACCESS, ACCESS]
    assert calls == [REFRESH]


def test_failed_refresh_is_not_retried_or_sent_to_api(store, monkeypatch):
    store.save(record())
    monkeypatch.setattr(login.OAuthSession, "__enter__", lambda self: self)
    monkeypatch.setattr(login.OAuthSession, "__exit__", lambda *args: None)

    def fail(*args):
        raise AuthError("Sign in again.")

    monkeypatch.setattr(login.OAuthSession, "refresh", fail)
    with pytest.raises(AuthError):
        SavedLogin(store)()
    assert store.load().tokens is None
    with pytest.raises(AuthError, match="No saved login"):
        SavedLogin(store)()
    assert store.load().revocation_token == REFRESH
    revoked = []
    monkeypatch.setattr(login.OAuthSession, "revoke", lambda _, record: revoked.append(record))
    login.logout(API)
    assert revoked[0].revocation_token == REFRESH and revoked[0].tokens is None
    assert store.load() is None


def test_key_precedence_does_not_read_login(monkeypatch, capsys):
    monkeypatch.setenv("ORINYX_API_URL", API)
    monkeypatch.setenv("ORINYX_API_KEY", "key-a")
    monkeypatch.setattr(credentials, "saved_login", lambda url: pytest.fail("read saved login"))
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["credentialSource"] == "environment"


@pytest.mark.parametrize(
    "value", ["http://remote.example", "https://u:p@api.example", API + "/v1", API + "?key=x"]
)
def test_login_resource_is_an_explicit_secure_origin(value):
    with pytest.raises(AuthError):
        credentials.resource_url(value)


def test_untrusted_metadata_endpoint_is_refused():
    with login.OAuthSession(API) as session:
        with pytest.raises(AuthError):
            session.endpoint("https://other.example/token")


def test_wrong_callback_state_does_not_complete_signin():
    callback = login.Callback("state-a")
    thread = threading.Thread(target=callback.server.handle_request)
    try:
        thread.start()
        response = httpx.get(callback.uri, params={"code": "code-a", "state": "wrong"})
        thread.join(timeout=5)
        assert response.status_code == 400
        assert callback.code is None
        with pytest.raises(AuthError, match="timed out"):
            callback.wait(timeout=0)
    finally:
        callback.close()


def test_storage_failure_never_falls_back_to_plaintext(store, monkeypatch):
    monkeypatch.setattr(credentials, "_native_keyring", lambda: None)
    with pytest.raises(AuthError, match="No plaintext fallback"):
        store.save(record())


def test_offline_logout_removes_local_credentials_but_reports_revocation_gap(store, monkeypatch):
    store.save(record())

    def fail(*args):
        raise AuthError("unavailable")

    monkeypatch.setattr(login.OAuthSession, "revoke", fail)
    with pytest.raises(AuthError, match="revocation was not confirmed"):
        login.logout(API)
    assert store.load() is None


def test_record_repr_and_corrupt_storage_do_not_disclose_tokens(store, monkeypatch):
    original = record()
    assert ACCESS not in repr(original)
    assert REFRESH not in repr(original)
    store.save(original)
    backend = credentials._native_keyring()
    backend.set_password("orinyx-cli", API, "invalid " + REFRESH)
    with pytest.raises(AuthError) as error:
        store.load()
    assert REFRESH not in str(error.value)


def test_revocation_does_not_read_the_response_body():
    class LargeBody(httpx.SyncByteStream):
        def __iter__(self):
            pytest.fail("Revocation must never buffer an unused response body")

    def respond(request):
        assert request.url.path == "/revoke"
        return httpx.Response(200, stream=LargeBody())

    with login.OAuthSession(API, transport=httpx.MockTransport(respond)) as session:
        monkey_metadata = type("Metadata", (), {"revocation_endpoint": API + "/revoke"})()
        session._metadata = monkey_metadata
        session.revoke(record())


def test_failed_keychain_deletion_is_not_reported_as_success(store, monkeypatch):
    from keyring.errors import PasswordDeleteError

    store.save(record())
    monkeypatch.setattr(login.OAuthSession, "revoke", lambda *_: None)
    backend_type = credentials._native_keyring

    def locked(*_):
        raise PasswordDeleteError(REFRESH)

    monkeypatch.setattr(backend_type, "delete_password", locked)
    with pytest.raises(AuthError) as error:
        login.logout(API)
    assert REFRESH not in str(error.value)
    assert store.load() is not None


@pytest.mark.parametrize(
    "result",
    [
        "error=access_denied",
        "code=a&code=b",
        "code=a&error=x",
        "code=a&iss=https://evil.example",
        "code=a&state=duplicate",
    ],
)
def test_callback_rejects_denial_ambiguity_and_wrong_issuer(result):
    callback = login.Callback("expected", issuer=API)
    responses = []
    thread = threading.Thread(
        target=lambda: responses.append(
            httpx.get(f"{callback.uri}?state=expected&{result}", trust_env=False)
        )
    )
    try:
        thread.start()
        callback.server.handle_request()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert responses[0].status_code == (200 if result == "error=access_denied" else 400)
        with pytest.raises(AuthError):
            callback.wait(timeout=0)
    finally:
        callback.close()


def test_callback_timeout_and_wrong_path_are_safe():
    callback = login.Callback("expected", issuer=API)
    responses = []
    thread = threading.Thread(
        target=lambda: responses.append(
            httpx.get(callback.uri.replace("/callback", "/wrong"), trust_env=False)
        )
    )
    try:
        thread.start()
        callback.server.handle_request()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert responses[0].status_code == 400
        with pytest.raises(AuthError, match="timed out"):
            callback.wait(timeout=0)
    finally:
        callback.close()


def test_stdio_uses_saved_provider_without_network_during_startup(store, monkeypatch, capsys):
    from orinyx_mcp import __main__ as stdio
    from orinyx_mcp import client as client_module
    from orinyx_mcp import server

    store.save(record())
    captured = []
    monkeypatch.setattr(login.OAuthSession, "refresh", lambda *_: pytest.fail("startup refresh"))

    class Server:
        def run(self):
            pass

    class Client(OrinyxClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(self)

    def build(factory, **kwargs):
        return Server()

    monkeypatch.setattr(client_module, "OrinyxClient", Client)
    monkeypatch.setattr(server, "build_server", build)
    assert stdio.main([]) == 0
    assert len(captured) == 1 and isinstance(captured[0]._token_provider, SavedLogin)
    captured[0].close()
    assert capsys.readouterr().out == ""

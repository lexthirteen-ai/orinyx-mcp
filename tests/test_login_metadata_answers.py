"""How `orinyx login` reads the sign-in server's metadata and its registration answer.

Before it opens the browser, the CLI fetches one document from the API's own origin
(`/.well-known/oauth-authorization-server`) and registers itself as a public client. Both
answers arrive over the network, so neither is trusted further than this:

- the document is asked for once, and no redirect is followed;
- it comes with a success status, as `application/json`, in at most 64 KB, and is a JSON object;
- its issuer is the API's origin;
- it offers S256 and names an authorization, token, registration and revocation endpoint;
- each of those is on the API's own origin and scheme, with no user info, query or fragment:
  a document that sends the token exchange anywhere else is refused;
- the registration answer is for a public client: no client secret, no secret-based method,
  a client id, and exactly the redirect this device asked for. These four are this package's
  own checks, so they are proved twice: with the SDK's model, and with a model that checks
  nothing.

A mock transport stands in for the server and records every request, so "no redirect is
followed" is counted, not assumed. Nothing is sent anywhere.
"""

import json
import types

import httpx
import pytest
from orinyx_mcp import credentials, login
from orinyx_mcp.credentials import AuthError

API = "https://api.example"
WELL_KNOWN = API + "/.well-known/oauth-authorization-server"
REDIRECT = "http://127.0.0.1:9876/callback"
ENDPOINTS = (
    "authorization_endpoint",
    "token_endpoint",
    "registration_endpoint",
    "revocation_endpoint",
)
LIMIT = 65536


def document(**changes) -> bytes:
    body = {
        "issuer": API,
        "authorization_endpoint": API + "/authorize",
        "token_endpoint": API + "/token",
        "registration_endpoint": API + "/register",
        "revocation_endpoint": API + "/revoke",
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
    }
    body.update(changes)
    return json.dumps({name: value for name, value in body.items() if value is not None}).encode()


def of_size(size: int) -> bytes:
    """A well-formed document of exactly `size` bytes."""
    return document(padding="x" * (size - len(document(padding=""))))


def served(content: bytes, status: int = 200, content_type="application/json", **headers):
    """How the server answers: a function that builds a fresh response for each request."""
    if content_type is not None:
        headers = {"content-type": content_type} | headers
    return lambda: httpx.Response(status, content=content, headers=headers)


def fetch(answer):
    """Ask a session for the metadata while the server gives `answer` to every request.
    Returns (the metadata or the AuthError raised, every URL requested)."""
    seen = []

    def respond(request):
        seen.append(str(request.url))
        return answer()

    with login.OAuthSession(API, transport=httpx.MockTransport(respond)) as session:
        try:
            return session.metadata(), seen
        except AuthError as refusal:
            return refusal, seen


# --- the document as a whole -------------------------------------------------------------------

ELSEWHERE = "https://other.example/.well-known/oauth-authorization-server"
ANSWERS_REFUSED = {
    "a redirect to another origin": served(document(), 302, location=ELSEWHERE),
    "a redirect within the API's origin": served(document(), 307, location=API + "/moved"),
    "a 404": served(document(), 404),
    "a 500": served(document(), 500),
    "served as text/html": served(document(), content_type="text/html"),
    "served with no content type": served(document(), content_type=None),
    "one byte over 64 KB": served(of_size(LIMIT + 1)),
    "a JSON list": served(b"[" + document() + b"]"),
    "not JSON": served(b"<html></html>"),
}


def test_a_well_formed_document_is_asked_for_once_at_the_apis_own_origin():
    metadata, seen = fetch(served(document()))
    assert str(metadata.token_endpoint) == API + "/token"
    assert seen == [WELL_KNOWN]


def test_a_document_of_exactly_64_kb_is_read():
    assert len(of_size(LIMIT)) == LIMIT
    metadata, _ = fetch(served(of_size(LIMIT)))
    assert str(metadata.token_endpoint) == API + "/token"


@pytest.mark.parametrize("case", list(ANSWERS_REFUSED))
def test_any_other_answer_is_refused_and_nothing_is_followed(case):
    refusal, seen = fetch(ANSWERS_REFUSED[case])
    assert isinstance(refusal, AuthError)
    assert seen == [WELL_KNOWN]


# --- what the document says --------------------------------------------------------------------

PLAIN_HTTP = API.replace("https://", "http://")
USER_INFO = API.replace("://", "://user:" + "synthetic" + "@")
CONTENTS_REFUSED = {
    "an issuer on another origin": {"issuer": "https://other.example"},
    "an issuer with a path": {"issuer": API + "/tenant"},
    "an issuer over plain http": {"issuer": PLAIN_HTTP},
    "no S256": {"code_challenge_methods_supported": ["plain"]},
    "no challenge methods": {"code_challenge_methods_supported": None},
}
ENDPOINT_PROBLEMS = {
    "on another origin": "https://other.example/endpoint",
    "on another port": API + ":8443/endpoint",
    "over plain http": PLAIN_HTTP + "/endpoint",
    "with user info": USER_INFO + "/endpoint",
    "with a query": API + "/endpoint?next=elsewhere",
    "with a fragment": API + "/endpoint#fragment",
    "missing": None,
}


@pytest.mark.parametrize("case", list(CONTENTS_REFUSED))
def test_a_document_that_does_not_describe_this_api_is_refused(case):
    refusal, seen = fetch(served(document(**CONTENTS_REFUSED[case])))
    assert isinstance(refusal, AuthError)
    assert seen == [WELL_KNOWN]


def test_an_issuer_with_a_trailing_slash_is_the_same_origin():
    metadata, _ = fetch(served(document(issuer=API + "/")))
    assert str(metadata.token_endpoint) == API + "/token"


@pytest.mark.parametrize("problem", list(ENDPOINT_PROBLEMS))
@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_endpoint_must_be_on_the_apis_own_origin(endpoint, problem):
    refusal, seen = fetch(served(document(**{endpoint: ENDPOINT_PROBLEMS[problem]})))
    assert isinstance(refusal, AuthError)
    assert seen == [WELL_KNOWN]


# --- the registration answer -------------------------------------------------------------------

REGISTRATIONS_REFUSED = {
    "a client secret": {"client_secret": "synthetic-secret"},
    "a secret-based method": {"token_endpoint_auth_method": "client_secret_post"},
    "another redirect": {"redirect_uris": ["http://127.0.0.1:1/callback"]},
    "a second redirect beside the right one": {
        "redirect_uris": [REDIRECT, "https://other.example/callback"]
    },
    "no client id": {"client_id": None},
}


def register(answer: dict):
    """Register against a server that echoes the request and then applies `answer`.
    Returns (the client or the AuthError raised, the JSON body of each registration request)."""
    asked = []

    def respond(request):
        if str(request.url) == WELL_KNOWN:
            return served(document())()
        assert str(request.url) == API + "/register"
        asked.append(json.loads(request.content))
        body = asked[-1] | {"client_id": "client-a"} | answer
        return httpx.Response(201, json={k: v for k, v in body.items() if v is not None})

    with login.OAuthSession(API, transport=httpx.MockTransport(respond)) as session:
        try:
            return session.register(REDIRECT), asked
        except AuthError as refusal:
            return refusal, asked


class _ChecksNothing:
    """Stands in for the SDK's registration model with every check of its own taken out, so a
    refusal seen through it is this package's."""

    @staticmethod
    def model_validate(answer):
        return types.SimpleNamespace(
            client_id=answer.get("client_id"),
            client_secret=answer.get("client_secret"),
            token_endpoint_auth_method=answer.get("token_endpoint_auth_method"),
            redirect_uris=answer.get("redirect_uris"),
        )


@pytest.fixture(params=["the SDK's model", "a model that checks nothing"])
def registration_model(request, monkeypatch):
    if request.param == "a model that checks nothing":
        monkeypatch.setattr(login, "OAuthClientInformationFull", _ChecksNothing)


def test_the_cli_registers_as_a_public_client_with_one_loopback_redirect(registration_model):
    client, [asked] = register({})
    assert client.client_id == "client-a"
    assert asked["token_endpoint_auth_method"] == "none"
    assert asked["redirect_uris"] == [REDIRECT]
    assert asked["scope"] == " ".join(credentials.SCOPES)
    assert "client_secret" not in asked


@pytest.mark.parametrize("case", list(REGISTRATIONS_REFUSED))
def test_a_registration_answer_that_is_not_this_public_client_is_refused(case, registration_model):
    refusal, _ = register(REGISTRATIONS_REFUSED[case])
    assert isinstance(refusal, AuthError)
    assert "synthetic-secret" not in str(refusal)

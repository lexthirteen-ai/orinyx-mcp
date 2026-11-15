"""What `orinyx login` accepts from the token endpoint.

After the browser returns, and again at every refresh, the CLI trades a code or a refresh token
for a pair of tokens. It keeps the answer only when all of this holds, and otherwise refuses it
with one sentence that shows no part of the answer:

- the access token is a sign-in token and the refresh token is a refresh token, by prefix: an
  API key is accepted in neither place;
- a refresh token is present;
- the granted scopes are named, and each is one of the four a CLI sign-in asks for;
- the lifetime is given, and is between one second and one hour;
- a refresh never comes back with more scope than the sign-in it renews.

The token endpoint is a mock transport: nothing is sent anywhere. All tokens are synthetic and
assembled from pieces, so this file holds no token-shaped string.
"""

import time

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from orinyx_mcp import credentials, login
from orinyx_mcp.credentials import AuthError, LoginRecord

API = "https://api.example"
ACCESS = "ork_oat_" + "b"
REFRESH = "ork_ort_" + "s"

REFUSED = {
    "an API key where the access token belongs": {"access_token": "ork_live_" + "x"},
    "a refresh token where the access token belongs": {"access_token": "ork_ort_" + "x"},
    "an access token with no prefix": {"access_token": "synthetic-access"},
    "an access token where the refresh token belongs": {"refresh_token": "ork_oat_" + "x"},
    "an API key where the refresh token belongs": {"refresh_token": "ork_live_" + "x"},
    "an empty refresh token": {"refresh_token": ""},
    "no refresh token": {"refresh_token": None},
    "an exam scope beside a sign-in scope": {"scope": "verify:read benchmark:read"},
    "a scope this package does not know": {"scope": "verify:read admin"},
    "an empty scope": {"scope": ""},
    "no scope": {"scope": None},
    "a lifetime one second over an hour": {"expires_in": 3601},
    "a lifetime of zero": {"expires_in": 0},
    "a negative lifetime": {"expires_in": -1},
    "no lifetime": {"expires_in": None},
}
ACCEPTED = {
    "as issued": {},
    "a lifetime of exactly an hour": {"expires_in": 3600},
    "a lifetime of one second": {"expires_in": 1},
    "one scope": {"scope": "verify:read"},
    "all four sign-in scopes": {"scope": " ".join(credentials.SCOPES)},
}


def answer(**changes) -> dict:
    body = {
        "access_token": ACCESS,
        "refresh_token": REFRESH,
        "token_type": "Bearer",
        "scope": "verify:read verify:write",
        "expires_in": 3600,
    }
    body.update(changes)
    return {name: value for name, value in body.items() if value is not None}


def session(body: dict) -> login.OAuthSession:
    """A sign-in session whose token endpoint answers `body`."""

    def respond(request):
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
        assert request.url.path == "/token"
        return httpx.Response(200, json=body)

    return login.OAuthSession(API, transport=httpx.MockTransport(respond))


def record(scope: str = "verify:read verify:write") -> LoginRecord:
    return LoginRecord(
        resource=API,
        client=OAuthClientInformationFull(
            client_id="client-a",
            redirect_uris=["http://127.0.0.1:9876/callback"],
            token_endpoint_auth_method="none",
        ),
        tokens=OAuthToken(
            access_token="ork_oat_" + "a",
            refresh_token="ork_ort_" + "r",
            scope=scope,
            expires_in=3600,
        ),
        expires_at=0,
    )


@pytest.mark.parametrize("case", list(ACCEPTED))
def test_a_well_formed_answer_is_kept(case):
    body = answer(**ACCEPTED[case])
    before = time.time()
    with session(body) as oauth:
        kept = oauth.tokens(record(), {"grant_type": "authorization_code"})
    assert kept.tokens.access_token == ACCESS and kept.tokens.refresh_token == REFRESH
    assert set(kept.tokens.scope.split()) <= set(credentials.SCOPES)
    assert before + body["expires_in"] <= kept.expires_at <= time.time() + body["expires_in"]
    assert kept.revocation_token is None


@pytest.mark.parametrize("case", list(REFUSED))
def test_any_other_answer_is_refused_and_no_part_of_it_is_shown(case):
    body = answer(**REFUSED[case])
    with session(body) as oauth:
        with pytest.raises(AuthError) as caught:
            oauth.tokens(record(), {"grant_type": "authorization_code"})
    message = str(caught.value)
    for name in ("access_token", "refresh_token"):
        assert not body.get(name) or body[name] not in message
    # Raised `from None`: the parser's own error, which can quote the answer, is not chained on.
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_a_refresh_cannot_come_back_with_more_scope_than_the_sign_in_had():
    narrow = record(scope="verify:read")
    with session(answer(scope="verify:read verify:write")) as oauth:
        with pytest.raises(AuthError, match="widen"):
            oauth.refresh(narrow, narrow.tokens)


@pytest.mark.parametrize("scope", ["verify:read verify:write", "verify:read"])
def test_a_refresh_with_the_same_or_less_scope_is_kept(scope):
    wide = record(scope="verify:read verify:write")
    with session(answer(scope=scope)) as oauth:
        kept = oauth.refresh(wide, wide.tokens)
    assert kept.tokens.access_token == ACCESS and kept.tokens.scope == scope


def test_the_sign_in_checks_scopes_against_its_own_four():
    """Not against the longer list the network server advertises, which holds the exam scopes."""
    assert login.SCOPES is credentials.SCOPES

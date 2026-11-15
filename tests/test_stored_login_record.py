"""What the CLI accepts back from the keychain.

A saved sign-in is one JSON record in the OS keychain, filed under the API origin it belongs
to. Other software running as the same user can write there too, so a record is read as
untrusted input and used only when all of this holds:

- it is at most 64 KB, and is a well-formed record;
- it names the origin it was looked up under;
- the redirect it registered is this device's loopback callback: plain http, `127.0.0.1`, a
  port, the path `/callback`, and no user info, query or fragment.

Any other record is refused with one fixed sentence that shows no part of it, and the commands
that send data then behave as if no sign-in were saved. The keychain here is a stand-in, and
every token is synthetic and assembled from pieces.
"""

import json

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from orinyx_mcp import cli, credentials
from orinyx_mcp.credentials import AuthError, CredentialStore, LoginRecord

API = "https://api.example"
ACCESS = "ork_oat_" + "a"
REFRESH = "ork_ort_" + "r"
REDIRECT = "http://127.0.0.1:9876/callback"
LIMIT = 65536
RUN_ID = "11111111-2222-4333-8444-555555555555"
MISSING = "Set ORINYX_API_URL and ORINYX_API_KEY in the environment.\n"


def stored(*, resource: str = API, redirects=(REDIRECT,), client_name: str | None = None) -> str:
    """The text of a saved sign-in, as the keychain would hold it."""
    record = LoginRecord(
        resource=API,
        client=OAuthClientInformationFull(
            client_id="client-a",
            redirect_uris=[REDIRECT],
            token_endpoint_auth_method="none",
            client_name=client_name,
        ),
        tokens=OAuthToken(
            access_token=ACCESS,
            refresh_token=REFRESH,
            scope="verify:read verify:write",
            expires_in=3600,
        ),
        expires_at=0,
    )
    # Changed as text, after the model has had its say, so each case is stored exactly as
    # written here.
    data = json.loads(record.model_dump_json())
    data["resource"] = resource
    data["client"]["redirect_uris"] = list(redirects)
    return json.dumps(data)


def of_length(length: int) -> str:
    """A well-formed record of exactly `length` characters, padded in the client's name."""
    return stored(client_name="x" * (length - len(stored(client_name="x")) + 1))


REFUSED = {
    "a record for another origin": stored(resource="https://other.example"),
    "a redirect on another host": stored(redirects=["http://attacker.example:9876/callback"]),
    "a redirect to localhost by name": stored(redirects=["http://localhost:9876/callback"]),
    "a redirect over https": stored(redirects=["https://127.0.0.1:9876/callback"]),
    "a redirect without a port": stored(redirects=["http://127.0.0.1/callback"]),
    "a redirect to another path": stored(redirects=["http://127.0.0.1:9876/other"]),
    "a redirect with user info": stored(redirects=["http://user@127.0.0.1:9876/callback"]),
    "a redirect with a query": stored(redirects=[REDIRECT + "?next=elsewhere"]),
    "a redirect with a fragment": stored(redirects=[REDIRECT + "#fragment"]),
    "a wrong redirect before the right one": stored(
        redirects=["http://attacker.example:9876/callback", REDIRECT]
    ),
    "no redirect": stored(redirects=[]),
    "one character over 64 KB": of_length(LIMIT + 1),
    "an object that is not a record": json.dumps({"refresh_token": REFRESH}),
    "text that is not JSON": "invalid " + REFRESH,
}
ACCEPTED = {
    "as saved": stored(),
    "exactly 64 KB": of_length(LIMIT),
    "the lowest port": stored(redirects=["http://127.0.0.1:1/callback"]),
    "the highest port": stored(redirects=["http://127.0.0.1:65535/callback"]),
}


@pytest.fixture
def keychain(monkeypatch, tmp_path):
    """A dict standing in for the OS keychain, and a temporary home directory."""
    data = {}

    class Backend:
        def get_password(self, service, account):
            return data.get((service, account))

    monkeypatch.setattr(credentials, "_native_keyring", Backend)
    monkeypatch.setattr(credentials.Path, "home", lambda: tmp_path)
    return data


@pytest.mark.parametrize("case", list(ACCEPTED))
def test_a_well_formed_record_for_this_origin_is_read(case, keychain):
    keychain["orinyx-cli", API] = ACCEPTED[case]
    record = CredentialStore(API).load()
    assert record.resource == API
    assert record.tokens.access_token == ACCESS and record.tokens.refresh_token == REFRESH
    assert credentials.saved_login(API) is not None


def test_the_two_sizes_are_what_they_say():
    assert len(of_length(LIMIT)) == LIMIT and len(of_length(LIMIT + 1)) == LIMIT + 1


@pytest.mark.parametrize("case", list(REFUSED))
def test_any_other_record_is_refused_and_no_part_of_it_is_shown(case, keychain):
    keychain["orinyx-cli", API] = REFUSED[case]
    with pytest.raises(AuthError) as caught:
        CredentialStore(API).load()
    message = str(caught.value)
    assert ACCESS not in message and REFRESH not in message
    # Raised `from None`: the parser's own error, which quotes its input, is not chained on.
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert credentials.saved_login(API) is None


def test_with_a_refused_record_the_cli_behaves_as_if_no_sign_in_were_saved(
    keychain, monkeypatch, capsys
):
    def must_not_build(*args, **kwargs):
        raise AssertionError("no client may be built from a refused record")

    keychain["orinyx-cli", API] = REFUSED["a record for another origin"]
    monkeypatch.setenv("ORINYX_API_URL", API)
    assert cli.main(["get", RUN_ID], client_factory=must_not_build) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", MISSING)

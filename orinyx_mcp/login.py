"""Browser-based native-app OAuth, using the MCP SDK's PKCE and wire models."""

import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from mcp.client.auth.oauth2 import PKCEParameters
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken

from orinyx_mcp.credentials import (
    SCOPES,
    AuthError,
    CredentialStore,
    LoginRecord,
    resource_url,
)


class Callback:
    def __init__(self, state: str, port: int = 0, issuer: str | None = None):
        self.state = state
        self.code: str | None = None
        self.denied = False
        callback = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, format: str, *args):
                pass

            def do_GET(self):
                parts = urlsplit(self.path)
                try:
                    params = parse_qs(parts.query, max_num_fields=10)
                except ValueError:
                    params = {}
                valid = (
                    len(self.path) < 8192
                    and parts.path == "/callback"
                    and not parts.scheme
                    and self.headers.get("Host") == f"127.0.0.1:{callback.server.server_port}"
                    and params.get("state") == [callback.state]
                    and ("code" in params) != ("error" in params)
                    and len(params.get("code", params.get("error", []))) == 1
                    and ("iss" not in params or params["iss"] == [issuer])
                )
                self.send_response(200 if valid else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'none'")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(b"Return to the terminal." if valid else b"Invalid callback.")
                if valid:
                    callback.denied = "error" in params
                    callback.code = params.get("code", [None])[0]

        class Server(HTTPServer):
            def handle_error(self, request, client_address):
                pass

        self.server = Server(("127.0.0.1", port), Handler)
        self.server.timeout = 0.5

    @property
    def uri(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/callback"

    def wait(self, timeout: float = 180) -> str:
        deadline = time.monotonic() + timeout
        while not self.code and not self.denied and time.monotonic() < deadline:
            self.server.handle_request()
        if self.denied:
            raise AuthError("Sign-in was denied. No login was saved.")
        if not self.code:
            raise AuthError("Sign-in timed out. Run orinyx login again.")
        return self.code

    def close(self):
        self.server.server_close()


class OAuthSession:
    def __init__(self, resource: str, *, transport=None):
        self.resource = resource_url(resource)
        self.http = httpx.Client(timeout=30, follow_redirects=False, transport=transport)
        self._metadata: OAuthMetadata | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def endpoint(self, url) -> str:
        try:
            parts = urlsplit(str(url))
            origin = resource_url(f"{parts.scheme}://{parts.netloc}")
            if origin != self.resource or parts.query or parts.fragment or parts.username:
                raise ValueError
            return str(url)
        except (AuthError, ValueError):
            raise AuthError("OAuth metadata names an untrusted endpoint.") from None

    def request(self, method: str, url: str, **kwargs) -> dict:
        try:
            with self.http.stream(method, self.endpoint(url), **kwargs) as response:
                if not response.is_success:
                    raise AuthError("OAuth request was refused. Run orinyx login again if needed.")
                if response.headers.get("content-type", "").split(";")[0] != "application/json":
                    raise AuthError("OAuth server returned an invalid response.")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise AuthError("OAuth response was too large.")
                import json

                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except (httpx.HTTPError, ValueError):
            raise AuthError(
                "OAuth request failed. No server response or credential is shown."
            ) from None

    def metadata(self) -> OAuthMetadata:
        if self._metadata is None:
            try:
                metadata = OAuthMetadata.model_validate(
                    self.request("GET", f"{self.resource}/.well-known/oauth-authorization-server")
                )
                if resource_url(str(metadata.issuer)) != self.resource:
                    raise ValueError
                if "S256" not in (metadata.code_challenge_methods_supported or []):
                    raise ValueError
                for endpoint in (
                    metadata.authorization_endpoint,
                    metadata.token_endpoint,
                    metadata.registration_endpoint,
                    metadata.revocation_endpoint,
                ):
                    if endpoint is None:
                        raise ValueError
                    self.endpoint(endpoint)
                self._metadata = metadata
            except ValueError:
                raise AuthError("The API does not advertise compatible OAuth login.") from None
        return self._metadata

    def register(self, redirect: str) -> OAuthClientInformationFull:
        try:
            client = OAuthClientInformationFull.model_validate(
                self.request(
                    "POST",
                    str(self.metadata().registration_endpoint),
                    json={
                        "client_name": "Orinyx CLI",
                        "redirect_uris": [redirect],
                        "token_endpoint_auth_method": "none",
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "scope": " ".join(SCOPES),
                    },
                )
            )
            if client.token_endpoint_auth_method != "none" or client.client_secret:
                raise ValueError
            if not client.client_id or [str(uri) for uri in client.redirect_uris or []] != [
                redirect
            ]:
                raise ValueError
            return client
        except ValueError:
            raise AuthError("The API returned an invalid public-client registration.") from None

    def tokens(self, record: LoginRecord, data: dict) -> LoginRecord:
        try:
            tokens = OAuthToken.model_validate(
                self.request("POST", str(self.metadata().token_endpoint), data=data)
            )
            granted = set((tokens.scope or "").split())
            if (
                not tokens.access_token.startswith("ork_oat_")
                or not (tokens.refresh_token or "").startswith("ork_ort_")
                or not granted
                or not granted <= set(SCOPES)
                or tokens.expires_in is None
                or not 0 < tokens.expires_in <= 3600
            ):
                raise ValueError
            return record.model_copy(
                update={
                    "tokens": tokens,
                    "expires_at": time.time() + tokens.expires_in,
                    "revocation_token": None,
                }
            )
        except ValueError:
            raise AuthError("The API returned invalid or overbroad login credentials.") from None

    def refresh(self, record: LoginRecord, previous: OAuthToken) -> LoginRecord:
        refreshed = self.tokens(
            record,
            {
                "grant_type": "refresh_token",
                "client_id": record.client.client_id,
                "refresh_token": previous.refresh_token,
                "resource": self.resource,
            },
        )
        if refreshed.tokens is None or not set((refreshed.tokens.scope or "").split()) <= set(
            (previous.scope or "").split()
        ):
            raise AuthError("Refresh attempted to widen the login scopes. Sign in again.")
        return refreshed

    def revoke(self, record: LoginRecord) -> None:
        token = record.tokens.refresh_token if record.tokens else record.revocation_token
        if token is None:
            return
        try:
            with self.http.stream(
                "POST",
                self.endpoint(self.metadata().revocation_endpoint),
                data={
                    "token": token,
                    "token_type_hint": "refresh_token",
                    "client_id": record.client.client_id,
                    # The pinned server SDK requires this field even for public clients.
                    "client_secret": "",
                },
            ) as response:
                if not response.is_success:
                    raise AuthError("Server revocation failed.")
        except httpx.HTTPError:
            raise AuthError("Server revocation failed.") from None


def login(url: str, *, no_browser: bool = False) -> None:
    store = CredentialStore(url)
    with store.locked():
        record = store.load()
        if record and record.tokens:
            raise AuthError("A login is already saved. Run orinyx logout before signing in again.")
        previous_record = record
        state = secrets.token_urlsafe(32)
        port = urlsplit(str((record.client.redirect_uris or [""])[0])).port if record else 0
        try:
            callback = Callback(state, port=port or 0, issuer=store.resource)
        except OSError:
            callback = Callback(state, issuer=store.resource)
            record = None
        try:
            with OAuthSession(store.resource) as session:
                if previous_record and previous_record.revocation_token:
                    session.revoke(previous_record)
                    previous_record.revocation_token = None
                    store.save(previous_record)
                if record is None:
                    record = LoginRecord(
                        resource=store.resource, client=session.register(callback.uri)
                    )
                store.save(record)
                pkce = PKCEParameters.generate()
                authorize = (
                    str(session.metadata().authorization_endpoint)
                    + "?"
                    + urlencode(
                        {
                            "response_type": "code",
                            "client_id": record.client.client_id,
                            "redirect_uri": callback.uri,
                            "state": state,
                            "code_challenge": pkce.code_challenge,
                            "code_challenge_method": "S256",
                            "scope": " ".join(SCOPES),
                            "resource": store.resource,
                        }
                    )
                )
                print(f"Sign in on this device: {authorize}", file=sys.stderr)
                if not no_browser:
                    try:
                        webbrowser.open(authorize)
                    except webbrowser.Error:
                        pass
                code = callback.wait()
                record = session.tokens(
                    record,
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "code_verifier": pkce.code_verifier,
                        "redirect_uri": callback.uri,
                        "client_id": record.client.client_id,
                        "resource": store.resource,
                    },
                )
                try:
                    store.save(record)
                except AuthError:
                    session.revoke(record)
                    raise
        finally:
            callback.close()


def logout(url: str) -> None:
    store = CredentialStore(url)
    failed = False
    with store.locked():
        record = store.load()
        try:
            if record and (record.tokens or record.revocation_token):
                with OAuthSession(store.resource) as session:
                    session.revoke(record)
        except AuthError:
            failed = True
        finally:
            if record is not None:
                store.delete()
    if failed:
        raise AuthError(
            "Local login removed; server revocation was not confirmed. "
            "End sessions in your account."
        )

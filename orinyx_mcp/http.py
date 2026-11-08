"""The Orinyx MCP server over the network (Streamable HTTP), as its own service.

An agent on another device connects to `https://<this host>/mcp`. Who gets in is decided by
the Orinyx API, never here: the bearer an agent presents (an `ork_live_*` key or an
`ork_oat_*` sign-in token issued by the API) is handed to `GET /v1/auth/credential`, which
describes it or refuses it. Every tool call then becomes an ordinary REST request to the API
carrying the CALLER'S OWN credential, so tenancy, scopes, the per-client rate limit, the
access log and the chain of custody are enforced by the API's one existing path, not
re-implemented here. This process holds no database, no service credential and no key of
its own.

The transport is stateless with JSON replies (one replica holds no MCP session state).
`Host` is checked against the public URL, so a rebinding page cannot drive a tester's local
browser at it. Sign-in lives at the API (`ORINYX_ISSUER_URL`); this service publishes only
the RFC 9728 document that points agents there.
"""

import contextlib
import contextvars
import hashlib
import ipaddress
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from orinyx_mcp import __version__
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.config import ROUTE_LABEL, Config, ConfigError

logger = logging.getLogger("orinyx_mcp")

# Every scope the engine's sign-in can grant. A connector requests exactly what this lists and
# the engine narrows the grant to what was requested, so a scope missing here can never be
# granted through a connector (the Arena scopes were missing until 2026-10-22: every
# start_arena_challenge was 403 "granted: verify:read, verify:write"). The engine still
# decides by role which of these an account receives.
SCOPES = (
    "verify:read",
    "verify:write",
    "benchmark:read",
    "benchmark:write",
    "arena:read",
    "arena:write",
)
CREDENTIAL_PATH = "/v1/auth/credential"
# Headers of the hop into the API: the shared secret the API recognises the hop by, the
# address of the agent that called this service (honoured by the API only on a recognised
# hop) and the request id, for correlating the two access logs.
LOOPBACK_HEADER = "x-orinyx-loopback"
CLIENT_IP_HEADER = "x-orinyx-client-ip"
REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CREDENTIAL_PREFIXES = ("ork_live_", "ork_oat_")

# Per-request facts the SDK does not pass to a token verifier or a tool: set by the
# attribution wrapper around the inner application.
_request_info: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "orinyx_mcp_request", default=None
)


class CredentialInfo(BaseModel):
    """What the API says about a bearer (`CredentialRead`). Unknown keys are ignored."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    active: bool = True
    credential_type: str
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    resource: str | None = None
    subject: str
    client_id: str | None = None
    role: str | None = None
    org_slug: str | None = None


@dataclass
class _Cached:
    access: Any
    until: float


class IntrospectionVerifier:
    """A bearer the API vouches for right now, or nothing. What the bearer may DO is decided
    by the API per REST route; this decides only who may speak MCP.

    A positive answer is cached briefly (keyed by the token's SHA-256, bounded), so
    `initialize` and `tools/list` do not cost one API call each; a refusal is never cached.
    A revoked token can therefore still list tools for at most `ttl` seconds, but every
    tool call reaches the API live and is refused there."""

    def __init__(
        self,
        api_url: str,
        resource: str,
        http: httpx.AsyncClient | None = None,
        *,
        ttl: float = 30.0,
        max_entries: int = 256,
        clock: Callable[[], float] = time.monotonic,
        extra_headers: Callable[[], dict[str, str]] | None = None,
    ) -> None:
        self._api = api_url.rstrip("/")
        self._resource = resource.rstrip("/")
        self.http = http
        # The hop headers (secret, the caller's address, the request id), so the API's
        # access log attributes the credential check to the agent, not to this Machine.
        self._extra_headers = extra_headers or dict
        self._ttl, self._max, self._clock = ttl, max_entries, clock
        self._cache: dict[str, _Cached] = {}

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        if not token or not token.startswith(_CREDENTIAL_PREFIXES):
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        hit = self._cache.get(digest)
        if hit is not None:
            if hit.until > now:
                return hit.access
            del self._cache[digest]
        if self.http is None:
            raise RuntimeError("the verifier's HTTP client is opened by the application lifespan")
        try:
            response = await self.http.get(
                self._api + CREDENTIAL_PATH,
                headers={
                    **self._extra_headers(),
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            # The API is unreachable: nobody is admitted, nothing is assumed. Logged without
            # the token so an operator can see it in the service's logs.
            logger.warning("credential check failed: %s %s", type(exc).__name__, self._api)
            return None
        if response.status_code != 200:
            return None
        try:
            info = CredentialInfo.model_validate(response.json())
        except (ValueError, ValidationError):
            return None
        if not info.active:
            return None
        if info.resource is not None and info.resource.rstrip("/") != self._resource:
            return None  # a sign-in token for another MCP endpoint
        expires = int(info.expires_at.timestamp()) if info.expires_at is not None else None
        access = AccessToken(
            token=token,
            client_id=info.client_id or f"{info.credential_type}:{info.subject}",
            scopes=list(info.scopes),
            expires_at=expires,
            resource=info.resource,
            subject=info.subject,
            claims={
                "credentialType": info.credential_type,
                "role": info.role,
                "orgSlug": info.org_slug,
            },
        )
        until = now + self._ttl
        if expires is not None:
            until = min(until, now + max(0.0, expires - time.time()))
        if len(self._cache) >= self._max:
            self._cache.pop(next(iter(self._cache)))
        self._cache[digest] = _Cached(access, until)
        return access


def caller_credential() -> str:
    """The bearer the current MCP request was admitted with."""
    from mcp.server.auth.middleware.auth_context import get_access_token

    access = get_access_token()
    if access is None:  # unreachable behind RequireAuthMiddleware; never fall back to a default
        raise ValueError("no authenticated caller on this request")
    return access.token


def caller_headers(config: Config) -> dict[str, str]:
    """What the hop into the API carries besides the credential. The caller's address is
    forwarded only with the secret: without it the API would not honour it anyway."""
    info = _request_info.get() or {}
    headers: dict[str, str] = {}
    if info.get("request_id"):
        headers[REQUEST_ID_HEADER] = info["request_id"]
    if config.hop_secret:
        headers[LOOPBACK_HEADER] = config.hop_secret
        if info.get("client_ip"):
            headers[CLIENT_IP_HEADER] = info["client_ip"]
    return headers


class ClientPool:
    """REST clients for the tool calls, one pooled connection per caller credential.

    A caller's client is reused across that caller's calls and never handed to another
    credential: the pool is keyed by a hash of the credential. Each call gets a `bound` view
    carrying its own request id and forwarded address; closing the view releases it. Idle
    clients beyond `max_idle` are closed oldest first; one in use is never closed."""

    def __init__(self, config: Config, *, max_idle: int = 256, transport=None):
        self._config = config
        self._max_idle = max_idle
        self._transport = transport
        self._lock = threading.Lock()
        self._clients: OrderedDict[str, list] = OrderedDict()  # key -> [client, users]
        # The engine-owned lists read from the API (orinyx_mcp.contract), shared by every
        # pooled client and checked once, by the first.
        self._contract_cache: dict = {}
        self._checked = False

    def __call__(self) -> OrinyxClient:
        credential = caller_credential()
        headers = caller_headers(self._config)
        key = hashlib.sha256(credential.encode("utf-8", "surrogatepass")).hexdigest()
        check = False
        with self._lock:
            entry = self._clients.pop(key, None)
            if entry is None:
                entry = [
                    OrinyxClient(
                        self._config.api_url,
                        credential,
                        allow_http=self._config.api_allow_http,
                        transport=self._transport,
                    ),
                    0,
                ]
                entry[0]._contract_cache = self._contract_cache
                check, self._checked = not self._checked, True
            entry[1] += 1
            self._clients[key] = entry
            evicted = self._over_cap()
        for client in evicted:
            client.close()
        if check:
            from orinyx_mcp.contract import check_in_background

            check_in_background(entry[0])
        return entry[0].bound(headers, release=lambda: self._release(entry))

    def _release(self, entry: list) -> None:
        with self._lock:
            entry[1] -= 1
            evicted = self._over_cap() if entry[1] == 0 else []
        for client in evicted:
            client.close()

    def _over_cap(self) -> list[OrinyxClient]:
        """Under the lock: remove the oldest idle clients beyond `max_idle` and return them,
        to be closed outside it. A client in use is never among them."""
        idle = [key for key, (_, users) in self._clients.items() if users == 0]
        excess = len(idle) - self._max_idle
        return [self._clients.pop(key)[0] for key in idle[: max(excess, 0)]]

    def __len__(self) -> int:
        return len(self._clients)

    def close(self) -> None:
        with self._lock:
            clients = [client for client, _ in self._clients.values()]
            self._clients.clear()
        for client in clients:
            client.close()


def client_factory(config: Config) -> ClientPool:
    """The REST clients for the tool calls: each carries the calling agent's own credential,
    over a connection pooled per credential."""
    return ClientPool(config)


def _address(value: str | None) -> str | None:
    if not value or "%" in value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    mapped = getattr(address, "ipv4_mapped", None)
    return str(mapped or address)


def _peer_address(scope: dict, config: Config) -> str | None:
    """The agent's address as the API should see it: the header the trusted proxy sets to
    the caller's address when configured (Fly: `fly-client-ip`), else the rightmost
    X-Forwarded-For entry behind exactly one trusted proxy, else the socket peer."""
    headers = dict(scope.get("headers") or [])
    if config.trusted_client_ip_header:
        raw = headers.get(config.trusted_client_ip_header.encode(), b"")
        named = _address(raw.decode("latin-1"))
        if named is not None:
            return named
    if config.trust_proxy_forwarded_for:
        # Behind a proxy the socket peer IS the proxy, so a garbage entry means no address.
        forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1").rsplit(",", 1)[-1]
        return _address(forwarded)
    return _address(scope["client"][0]) if scope.get("client") else None


def _request_id(scope: dict) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"x-request-id":
            presented = value.decode("latin-1")
            if _REQUEST_ID_RE.match(presented):
                return presented
    return uuid.uuid4().hex


class _Attribution:
    """Pure ASGI around the SDK's application: records who is calling for the hop headers,
    labels the request, and presents the exact-path route to the inner application the way
    the mount would."""

    def __init__(self, app, config: Config) -> None:
        self._app, self._config = app, config

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state["route_label"] = ROUTE_LABEL
        root = scope.get("root_path", "")
        if scope.get("path") == root + ROUTE_LABEL and not root.endswith(ROUTE_LABEL):
            path = root + ROUTE_LABEL + "/"
            scope = dict(scope, root_path=root + ROUTE_LABEL, path=path, raw_path=path.encode())
        info = {"request_id": _request_id(scope)}
        peer = _peer_address(scope, self._config)
        if peer:
            info["client_ip"] = peer
        token = _request_info.set(info)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_info.reset(token)


class _Headers:
    """Response headers on everything this service serves."""

    def __init__(self, app, *, hsts: bool) -> None:
        self._app, self._hsts = app, hsts

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"cache-control", b"no-store"))
                headers.append((b"referrer-policy", b"no-referrer"))
                if self._hsts:
                    headers.append(
                        (b"strict-transport-security", b"max-age=63072000; includeSubDomains")
                    )
                message = dict(message, headers=headers)
            await send(message)

        await self._app(scope, receive, send_with_headers)


def build_app(
    config: Config,
    *,
    client_for: Callable[[], OrinyxClient] | None = None,
    verifier=None,
    http: httpx.AsyncClient | None = None,
    gateway=None,
):
    """The ASGI application: `/mcp` (and `/mcp/`: both must ANSWER, since a mount alone
    redirects the bare path and behind a TLS proxy that redirect names http), the
    protected-resource document at the origin, and `/health`."""
    if not config.hop_secret:
        raise ConfigError(
            "Hosted MCP requires ORINYX_HOP_SECRET; no public REST fallback is allowed"
        )

    from mcp.server.auth.routes import create_protected_resource_routes
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.transport_security import TransportSecuritySettings
    from pydantic import AnyHttpUrl
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    from orinyx_mcp.server import build_server

    parts = urlsplit(config.public_url)
    verifier = verifier or IntrospectionVerifier(
        config.api_url, config.resource, http, extra_headers=lambda: caller_headers(config)
    )
    if client_for is None:
        client_for = client_factory(config)
    server = build_server(
        client_for,
        auth=AuthSettings(
            issuer_url=config.issuer_url,
            # The 401 challenge names the protected-resource document below, where an
            # agent given only the URL finds the sign-in.
            resource_server_url=config.resource,
            # The verifier checks a sign-in token's resource itself; a key has none.
            validate_token_resource=False,
        ),
        token_verifier=verifier,
        gateway=gateway,
    )
    inner = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[parts.netloc],
            allowed_origins=[config.origin],
        ),
        host=parts.hostname,
    )
    endpoint = _Attribution(inner, config)

    async def health(request):
        return JSONResponse(
            {
                "status": "ok",
                "service": "orinyx-mcp",
                "version": __version__,
                "commitSha": os.environ.get("ORINYX_COMMIT_SHA") or None,
            }
        )

    routes = [
        Route("/health", endpoint=health, methods=["GET"]),
        Route(ROUTE_LABEL, endpoint=endpoint, methods=None),
        Mount(ROUTE_LABEL, app=endpoint),
    ]
    routes += create_protected_resource_routes(
        resource_url=AnyHttpUrl(config.resource),
        authorization_servers=[AnyHttpUrl(config.issuer_url)],
        scopes_supported=list(SCOPES),
        resource_name="Orinyx",
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        owned = isinstance(verifier, IntrospectionVerifier) and verifier.http is None
        if owned:
            verifier.http = httpx.AsyncClient(timeout=10.0)
        try:
            async with server.session_manager.run():
                yield
        finally:
            if owned:
                await verifier.http.aclose()
                verifier.http = None
            close = getattr(client_for, "close", None)
            if close is not None:
                close()

    app = Starlette(routes=routes, lifespan=lifespan)
    return _Headers(app, hsts=parts.scheme == "https"), app


def dual_stack_socket(port: int):
    """One listening socket for both address families. asyncio marks an AF_INET6 server
    socket IPv6-only, so `host="::"` would drop IPv4, which is how Fly's edge and its health
    check reach the Machine; `0.0.0.0` would drop IPv6, Fly's private network."""
    import socket

    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", port))
    sock.listen(2048)
    return sock


# What the server prints when it cannot start for a reason other than a refused setting.
_NOT_STARTED = (
    "The server could not start ({}). No setting's value is shown; a malformed URL is the "
    "usual cause: check MCP_PUBLIC_URL, ORINYX_API_URL, ORINYX_ISSUER_URL, DOWNSTREAM_MCP_URL "
    "and ORINYX_ARENA_URL."
)


# The only argument lists `orinyx-mcp` takes. The line names no argument it was given.
_USAGE = "usage: orinyx-mcp | orinyx-mcp stdio | orinyx-mcp --version"


def _run_as_the_command() -> bool:
    """True when the program running is the `orinyx-mcp` console script. The script pip, uv
    and pipx write imports this function into `__main__` and calls it with no argument, so
    only then is `sys.argv` this command's own. An in-process caller (a test runner, or
    `python -m orinyx_mcp serve`) does not hand its command line to the server."""
    return getattr(sys.modules.get("__main__"), "serve", None) is serve


def serve(argv: list[str] | None = None) -> int:
    """The `orinyx-mcp` command. With no argument: the network server, configured from the
    environment. `orinyx-mcp stdio`: the stdio server, the same code as `python -m
    orinyx_mcp`. `orinyx-mcp --version`: the version on stdout. Any other argument list is
    a usage error (exit 1) and starts nothing."""
    if argv is None:
        argv = sys.argv[1:] if _run_as_the_command() else []
    if argv == ["stdio"]:
        from orinyx_mcp.__main__ import main

        return main([])
    if argv == ["--version"]:
        print(__version__)
        return 0
    if argv:
        print(_USAGE, file=sys.stderr)
        return 1
    import uvicorn

    from orinyx_mcp.gateway import Gateway, GatewayConfig

    # Starting up reads every URL setting. Only this package's own refusals are printed: any
    # other error here (pydantic, urllib, httpx) can quote a URL with its password, in its
    # message or in a chained one, so it is one fixed line and never a traceback.
    try:
        config = Config.from_env()
        downstream = GatewayConfig.from_env()
        wrapped, _ = build_app(config, gateway=Gateway(downstream) if downstream else None)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(_NOT_STARTED.format(type(exc).__name__), file=sys.stderr)
        return 1
    server = uvicorn.Server(uvicorn.Config(wrapped, port=config.port, log_level="info"))
    server.run(sockets=[dual_stack_socket(config.port)])
    return 0


__all__ = [
    "CLIENT_IP_HEADER",
    "CREDENTIAL_PATH",
    "LOOPBACK_HEADER",
    "REQUEST_ID_HEADER",
    "SCOPES",
    "IntrospectionVerifier",
    "build_app",
    "caller_credential",
    "caller_headers",
    "ClientPool",
    "client_factory",
    "serve",
]

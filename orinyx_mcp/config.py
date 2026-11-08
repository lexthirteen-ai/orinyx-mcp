"""Configuration of the network server, from the environment only.

| Variable                    | Meaning                                                      |
|-----------------------------|--------------------------------------------------------------|
| MCP_PUBLIC_URL              | the https origin agents connect to; `/mcp` is served there   |
| ORINYX_API_URL              | the Orinyx API this service calls on the caller's behalf     |
| ORINYX_ISSUER_URL           | the Orinyx sign-in origin named in the resource metadata     |
|                             | (defaults to ORINYX_API_URL when that is https)              |
| ORINYX_HOP_SECRET           | required for hosted MCP; shared with the API for private     |
|                             | backend authentication (at least 32 ASCII characters)        |
| ORINYX_API_ALLOW_HTTP       | `true` only for a private network trusted end to end         |
| TRUST_PROXY_FORWARDED_FOR   | `true` behind exactly one proxy (the host's edge)            |
| TRUSTED_CLIENT_IP_HEADER    | a header that proxy sets to the caller's address (Fly:       |
|                             | `fly-client-ip`); wins over X-Forwarded-For when present     |
| PORT                        | listening port (default 8000)                                |
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

ROUTE_LABEL = "/mcp"
MIN_SECRET_CHARS = 32
_TRUE = ("1", "true", "yes", "on")


class ConfigError(ValueError):
    """A setting this package refused. The message names the variable and quotes no URL, key
    or secret (at most the tool names an operator listed), so an entry point may print it.
    Any other error met while reading the settings may quote a URL with its password, and is
    never printed."""


def split_config_url(value: str, setting: str):
    """Parse without exposing parser messages, and reject even empty userinfo."""
    try:
        parts = urlsplit(value)
    except ValueError:
        raise ConfigError(f"{setting} is malformed (its value is not shown)") from None
    if parts.username is not None or parts.password is not None:
        raise ConfigError(f"{setting} must not contain a username or password")
    return parts


def _https_or_local(url: str) -> bool:
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    return bool(parts.hostname) and (parts.scheme == "https" or (parts.scheme == "http" and local))


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True)
class Config:
    public_url: str
    api_url: str
    issuer_url: str
    hop_secret: str | None = None
    api_allow_http: bool = False
    trust_proxy_forwarded_for: bool = False
    trusted_client_ip_header: str | None = None
    port: int = 8000

    @property
    def origin(self) -> str:
        return _origin(self.public_url)

    @property
    def resource(self) -> str:
        """The RFC 8707 resource this service is: what the engine binds tokens to."""
        return f"{self.origin}{ROUTE_LABEL}"

    def __post_init__(self) -> None:
        split_config_url(self.api_url, "ORINYX_API_URL")
        split_config_url(self.issuer_url, "ORINYX_ISSUER_URL")
        if not _https_or_local(self.public_url):
            raise ConfigError("MCP_PUBLIC_URL must be an https URL (plain http only for localhost)")
        api_local = _https_or_local(self.api_url)
        if not api_local and not (self.api_allow_http and urlsplit(self.api_url).hostname):
            raise ConfigError(
                "ORINYX_API_URL must be https (plain http only for localhost, or with "
                "ORINYX_API_ALLOW_HTTP=true on a private network)"
            )
        if not _https_or_local(self.issuer_url):
            raise ConfigError("ORINYX_ISSUER_URL must be an https origin")
        if self.hop_secret is not None and len(self.hop_secret) < MIN_SECRET_CHARS:
            raise ConfigError(f"ORINYX_HOP_SECRET must be at least {MIN_SECRET_CHARS} characters")
        if self.hop_secret is not None and not self.hop_secret.isascii():
            raise ConfigError("ORINYX_HOP_SECRET must contain only ASCII characters")
        if not 0 < self.port < 65536:
            raise ConfigError("PORT must be a port number")
        if self.trusted_client_ip_header is not None and not re.fullmatch(
            r"[a-z0-9-]+", self.trusted_client_ip_header
        ):
            raise ConfigError("TRUSTED_CLIENT_IP_HEADER must be a header name")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        public_url = (env.get("MCP_PUBLIC_URL") or "").strip().rstrip("/")
        api_url = (env.get("ORINYX_API_URL") or "").strip().rstrip("/")
        if not public_url or not api_url:
            raise ConfigError("Set MCP_PUBLIC_URL and ORINYX_API_URL")
        split_config_url(api_url, "ORINYX_API_URL")
        issuer = (env.get("ORINYX_ISSUER_URL") or "").strip().rstrip("/")
        if issuer:
            split_config_url(issuer, "ORINYX_ISSUER_URL")
        else:
            issuer = _origin(api_url)
        secret = env.get("ORINYX_HOP_SECRET") or None
        try:
            port = int(env.get("PORT") or 8000)
        except ValueError as exc:
            raise ConfigError("PORT must be a number") from exc
        return cls(
            public_url=public_url,
            api_url=api_url,
            issuer_url=_origin(issuer),
            hop_secret=secret,
            api_allow_http=(env.get("ORINYX_API_ALLOW_HTTP") or "").lower() in _TRUE,
            trust_proxy_forwarded_for=(env.get("TRUST_PROXY_FORWARDED_FOR") or "").lower() in _TRUE,
            trusted_client_ip_header=(env.get("TRUSTED_CLIENT_IP_HEADER") or "").strip().lower()
            or None,
            port=port,
        )


__all__ = ["Config", "ConfigError", "MIN_SECRET_CHARS", "ROUTE_LABEL"]

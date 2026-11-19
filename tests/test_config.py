"""Configuration is the environment only, and it fails at boot, not at exploit time."""

import pytest
from orinyx_mcp.config import Config

BASE = {
    "MCP_PUBLIC_URL": "https://mcp.example",
    "ORINYX_API_URL": "https://api.example",
}


def test_the_public_url_must_be_https_unless_local():
    with pytest.raises(ValueError, match="MCP_PUBLIC_URL"):
        Config.from_env(BASE | {"MCP_PUBLIC_URL": "http://mcp.example"})
    local = Config.from_env(BASE | {"MCP_PUBLIC_URL": "http://localhost:8766/"})
    assert local.public_url == "http://localhost:8766" and local.resource.endswith("/mcp")


def test_plain_http_to_the_engine_needs_the_opt_in():
    private = {"ORINYX_API_URL": "http://orinyx-api.internal:8000"}
    with pytest.raises(ValueError, match="ORINYX_API_ALLOW_HTTP"):
        Config.from_env(BASE | private)
    with pytest.raises(ValueError, match="ORINYX_ISSUER_URL"):
        Config.from_env(BASE | private | {"ORINYX_API_ALLOW_HTTP": "true"})
    config = Config.from_env(
        BASE
        | private
        | {"ORINYX_API_ALLOW_HTTP": "true", "ORINYX_ISSUER_URL": "https://api.example/x"}
    )
    assert config.api_allow_http and config.issuer_url == "https://api.example"


def test_the_issuer_defaults_to_the_api_origin():
    config = Config.from_env(BASE | {"ORINYX_API_URL": "https://api.example/v1/"})
    assert config.issuer_url == "https://api.example"
    assert config.api_url == "https://api.example/v1"


def test_the_hop_secret_must_be_long_and_the_port_a_number():
    with pytest.raises(ValueError, match="ORINYX_HOP_SECRET"):
        Config.from_env(BASE | {"ORINYX_HOP_SECRET": "short"})
    with pytest.raises(ValueError, match="PORT"):
        Config.from_env(BASE | {"PORT": "eight"})
    config = Config.from_env(BASE | {"ORINYX_HOP_SECRET": "x" * 32, "PORT": "9000"})
    assert config.hop_secret == "x" * 32 and config.port == 9000
    assert Config.from_env(BASE).hop_secret is None


def test_both_urls_are_required():
    with pytest.raises(ValueError, match="MCP_PUBLIC_URL and ORINYX_API_URL"):
        Config.from_env({"MCP_PUBLIC_URL": "https://mcp.example"})


def test_hop_secret_must_be_ascii():
    with pytest.raises(ValueError, match="ASCII"):
        Config.from_env(BASE | {"ORINYX_HOP_SECRET": "\u00e9" * 32})


def test_the_trusted_client_ip_header_is_a_header_name():
    with pytest.raises(ValueError, match="TRUSTED_CLIENT_IP_HEADER"):
        Config.from_env(BASE | {"TRUSTED_CLIENT_IP_HEADER": "not a header"})
    config = Config.from_env(BASE | {"TRUSTED_CLIENT_IP_HEADER": "Fly-Client-IP"})
    assert config.trusted_client_ip_header == "fly-client-ip"
    assert Config.from_env(BASE).trusted_client_ip_header is None

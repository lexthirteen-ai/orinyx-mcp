"""Configured URL credentials never reach clients, metadata or startup logs."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from orinyx_mcp.arena import _spectator_origin
from orinyx_mcp.client import OrinyxClient
from orinyx_mcp.config import Config, ConfigError

BASE = {"MCP_PUBLIC_URL": "https://mcp.example", "ORINYX_API_URL": "https://api.example/v1"}
PASSWORD = "synthetic_password_userinfo"
USERINFO = ["user", f"user:{PASSWORD}", f":{PASSWORD}", "", ":", "user:", "us%65r:p%61ss"]


@pytest.mark.parametrize("userinfo", USERINFO)
@pytest.mark.parametrize("setting", ["ORINYX_API_URL", "ORINYX_ISSUER_URL", "ORINYX_ARENA_URL"])
def test_userinfo_is_refused_even_when_empty(setting, userinfo):
    value = f"https://{userinfo}@host.example"
    with pytest.raises(ConfigError) as caught:
        if setting == "ORINYX_ARENA_URL":
            _spectator_origin(value)
        else:
            Config.from_env(BASE | {setting: value})
    assert str(caught.value) == f"{setting} must not contain a username or password"
    assert value not in str(caught.value)
    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize("field", ["api_url", "issuer_url"])
def test_direct_config_also_refuses_userinfo(field):
    config = Config.from_env(BASE)
    with pytest.raises(ConfigError):
        replace(config, **{field: f"https://user:{PASSWORD}@host.example"})


@pytest.mark.parametrize("userinfo", USERINFO)
@pytest.mark.parametrize("allow_http", [False, True])
def test_direct_client_refuses_before_constructing_http_client(userinfo, allow_http):
    with patch("orinyx_mcp.client.httpx.Client") as factory:
        with pytest.raises(ConfigError, match="ORINYX_API_URL"):
            OrinyxClient(f"https://{userinfo}@host.example", "synthetic_key", allow_http=allow_http)
        factory.assert_not_called()


def test_api_credentials_cannot_become_public_issuer_metadata():
    from orinyx_mcp import http

    with patch.object(http, "build_app") as build:
        with pytest.raises(ConfigError, match="ORINYX_API_URL"):
            config = Config.from_env(
                BASE | {"ORINYX_API_URL": f"https://user:{PASSWORD}@api.example"}
            )
            http.build_app(config)
        build.assert_not_called()
    config = Config.from_env(BASE)
    assert config.issuer_url == "https://api.example"
    assert PASSWORD not in repr(config)


@pytest.mark.parametrize(
    "value",
    [
        f"https://us＃er:{PASSWORD}@host.example",
        f"https://user:{PASSWORD}@[broken",
    ],
)
@pytest.mark.parametrize("setting", ["ORINYX_API_URL", "ORINYX_ISSUER_URL", "ORINYX_ARENA_URL"])
def test_parser_failure_is_a_safe_config_error(setting, value):
    with pytest.raises(ConfigError) as caught:
        if setting == "ORINYX_ARENA_URL":
            _spectator_origin(value)
        else:
            Config.from_env(BASE | {setting: value})
    assert str(caught.value) == f"{setting} is malformed (its value is not shown)"
    assert caught.value.__suppress_context__
    assert PASSWORD not in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [
        f"https://us＃er:{PASSWORD}@arena.example",
        f"https://user:{PASSWORD}@[broken",
        f"https://user:{PASSWORD}@arena.example",
    ],
)
@pytest.mark.parametrize("mode", ["stdio", "serve", "cli"])
def test_process_refusal_has_no_traceback_or_credentials(value, mode):
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("ORINYX_", "MCP_", "DOWNSTREAM_MCP_"))
    }
    settings = {**BASE, "ORINYX_API_KEY": "synthetic_key"}
    if mode == "cli":
        settings["ORINYX_API_URL"] = value
        args = ["-m", "orinyx_mcp.cli", "verify", "--file", "unused.json"]
    else:
        settings.update(ORINYX_ARENA_ENABLED="true", ORINYX_ARENA_URL=value)
        args = ["-m", "orinyx_mcp", *(["serve"] if mode == "serve" else [])]
    result = subprocess.run(
        [sys.executable, *args],
        env=clean | settings,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert "Traceback" not in result.stderr
    assert PASSWORD not in result.stderr
    assert (
        "ORINYX_API_URL" in result.stderr if mode == "cli" else "ORINYX_ARENA_URL" in result.stderr
    )


@pytest.mark.parametrize(
    "origin", ["https://arena.example", "http://localhost", "http://127.0.0.1", "http://[::1]"]
)
def test_legitimate_arena_origins_remain_usable(origin):
    assert _spectator_origin(origin + "/") == origin


def test_issuer_normalization_and_api_paths_remain_usable():
    config = Config.from_env(BASE | {"ORINYX_ISSUER_URL": "https://id.example/path"})
    assert config.api_url == BASE["ORINYX_API_URL"]
    assert config.issuer_url == "https://id.example"

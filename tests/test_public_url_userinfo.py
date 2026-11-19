"""The public URL is published, so it never holds a username or a password.

`MCP_PUBLIC_URL` is what the network server tells every caller about itself. It is the
`resource` of the protected-resource document, which is served without a credential, and it is
named in the `WWW-Authenticate` challenge of every 401. A username or password inside it would
be handed to anyone who asks, so the server refuses to start with one, as it already does for
`ORINYX_API_URL` and `ORINYX_ISSUER_URL`. All values here are synthetic.
"""

import os
from dataclasses import replace

import pytest
from orinyx_mcp import http
from orinyx_mcp.config import Config, ConfigError

HOP_SECRET = "synthetic-hop-" * 4
BASE = {
    "MCP_PUBLIC_URL": "https://mcp.example",
    "ORINYX_API_URL": "https://api.example",
    "ORINYX_HOP_SECRET": HOP_SECRET,
}
PASSWORD = "synthetic" + "_password_" + "userinfo"
# Written out rather than imported, so a change to the wording fails here.
REFUSED = "MCP_PUBLIC_URL must not contain a username or password"
USERINFO = ["user", f"user:{PASSWORD}", f":{PASSWORD}", "", ":", "user:", "us%65r:p%61ss"]
# Every form of public URL the server accepts, the plain-http loopback forms included.
PUBLIC_URLS = [
    "https://{}mcp.example",
    "https://{}mcp.example:8443",
    "http://{}localhost:8766",
    "http://{}127.0.0.1:8766",
    "http://{}[::1]:8766",
]


@pytest.mark.parametrize("userinfo", USERINFO)
@pytest.mark.parametrize("form", PUBLIC_URLS)
def test_a_public_url_with_userinfo_is_refused_even_when_empty(form, userinfo):
    value = form.format(userinfo + "@")
    with pytest.raises(ConfigError) as caught:
        Config.from_env(BASE | {"MCP_PUBLIC_URL": value})
    assert str(caught.value) == REFUSED
    assert PASSWORD not in str(caught.value)


def test_a_config_built_directly_refuses_it_too():
    config = Config.from_env(BASE)
    with pytest.raises(ConfigError) as caught:
        replace(config, public_url=f"https://user:{PASSWORD}@mcp.example")
    assert str(caught.value) == REFUSED


@pytest.mark.parametrize("form", PUBLIC_URLS)
def test_the_same_public_urls_without_userinfo_remain_usable(form):
    url = form.format("")
    config = Config.from_env(BASE | {"MCP_PUBLIC_URL": url + "/"})
    assert config.public_url == url
    assert config.resource == url + "/mcp"


def test_the_server_prints_one_line_and_builds_nothing(monkeypatch, capsys):
    """`orinyx-mcp` with such a URL: exit 1, one line that names the setting and repeats no
    part of its value, and the application that would publish the URL is never built."""

    def must_not_build(*args, **kwargs):
        raise AssertionError("the application must not be built with this public URL")

    monkeypatch.setattr(http, "build_app", must_not_build)
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_")):
            monkeypatch.delenv(name)
    settings = BASE | {"MCP_PUBLIC_URL": f"https://user:{PASSWORD}@mcp.example"}
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    assert http.serve([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", REFUSED + "\n")

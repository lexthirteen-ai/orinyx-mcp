"""Keep the shortest hosted path and account-access help consistent with the Quickstart."""

from pathlib import Path

import pytest
from orinyx_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ["README.md", "docs/QUICKSTART.md"])
def test_hosted_steps_set_the_password_before_connecting(path):
    text = _read(path)
    signup = text.index("1. **Sign up**")
    end = text.index("\n\n", signup)
    steps = " ".join(text[signup:end].split())
    assert "2. **Open the welcome email**" in steps
    assert "set your password" in steps
    assert "link can be used once" in steps
    assert "3. **Add the connector**" in steps
    assert "in your client" in steps
    assert steps.index("set your password") < steps.index("3. **Add the connector**")
    assert "Sign in with your email and the password you set" in steps
    assert "10 minutes" in steps and "mailto:hello@orinyx.io" in steps


def test_key_renewal_uses_the_same_self_serve_setup_as_the_readme():
    text = _read("docs/TROUBLESHOOTING.md")
    row = next(line for line in text.splitlines() if line.startswith("| 401 "))
    assert "Mint a replacement through the [self-serve API](../README.md#get-an-api-key)" in row
    assert "or ask your operator" in row
    assert "update the client's `env`" in row
    assert "Alternatively use the hosted connector and sign in" in row
    assert "A self-serve account has no key" not in text
    setup = _read("README.md").split("### Get an API key\n", 1)[1].split("\n### ", 1)[0]
    assert "POST /v1/auth/api-keys/self" in setup


def test_troubleshooting_distinguishes_developer_and_product_access():
    text = _read("docs/TROUBLESHOOTING.md")
    row = next(line for line in text.splitlines() if line.startswith("| 403 "))
    assert "exam tools on a developer account" in row
    assert "verification and lookup tools on a product account" in row
    assert "Developer accounts can use the five FDA reference lookups" in row
    assert "exam or label tools on a developer account" not in text
    lookup_section = " ".join(text.split("## FDA reference access\n", 1)[1].split())
    for tool in (
        "find_fda_label",
        "read_fda_label_section",
        "find_otc_monographs",
        "get_otc_monograph",
        "read_otc_monograph_section",
    ):
        assert f"`{tool}`" in lookup_section
    assert "including free self-serve accounts" in lookup_section
    assert "reference text, not a verdict" in lookup_section
    assert "do not count against the free plan's monthly checks" in lookup_section
    assert "Product accounts cannot use these lookups" in lookup_section
    assert "remain staff-only" in lookup_section


def test_repository_release_is_not_presented_as_the_hosted_build():
    text = " ".join(_read("README.md").split())
    assert "reports its running build at `https://orinyx-mcp.fly.dev/health`" in text
    assert "releases/latest" in text
    assert "v0.1.4 is a documentation release" not in text


def test_the_first_verification_is_on_the_first_screen():
    readme = _read("README.md")
    head = readme.split("\n## ", 1)[0]
    assert len(head.splitlines()) <= 45
    assert "**Your first verification**" in head
    assert "`verify_order_text`" in head
    assert "docs/QUICKSTART.md#first-run" in head
    assert f"releases/tag/v{__version__}" in head

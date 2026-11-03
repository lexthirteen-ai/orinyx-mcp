"""No database, no engine: every test here drives the package with fakes."""

import pytest


@pytest.fixture(autouse=True)
def _no_engine_env(monkeypatch):
    for name in ("ORINYX_API_URL", "ORINYX_API_KEY", "MCP_PUBLIC_URL", "ORINYX_HOP_SECRET"):
        monkeypatch.delenv(name, raising=False)

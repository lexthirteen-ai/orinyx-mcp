"""`python -m orinyx_mcp` (or `orinyx-mcp stdio`): serve Orinyx tools over stdio to a local
MCP client. `python -m orinyx_mcp serve` (or the `orinyx-mcp` command): the network server.

Configuration uses ORINYX_API_URL and an explicit ORINYX_API_KEY, or the saved OAuth login
for that API origin. The network server never reads local logins.
The DOWNSTREAM_MCP_* variables connect another MCP
server's tools (`orinyx_mcp/gateway.py`)."""

import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["serve"]:
        from orinyx_mcp.http import serve

        return serve([])
    if args:
        print("usage: python -m orinyx_mcp [serve]", file=sys.stderr)
        return 1
    url = os.environ.get("ORINYX_API_URL")
    key = os.environ.get("ORINYX_API_KEY")
    from orinyx_mcp.credentials import DEFAULT_API_URL, AuthError, saved_login

    provider = None
    if not key:
        try:
            provider = saved_login(url or DEFAULT_API_URL)
        except AuthError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if provider:
            url = url or DEFAULT_API_URL
    if not url or (not key and provider is None):
        print("Set ORINYX_API_URL and ORINYX_API_KEY in the environment.", file=sys.stderr)
        return 1
    try:
        from orinyx_mcp.server import build_server, shared
    except ImportError:
        print('The MCP runtime is not installed: pip install "mcp>=2.3".', file=sys.stderr)
        return 1
    import httpx

    from orinyx_mcp.client import UNUSABLE_CONFIG, InsecureUrlError, OrinyxClient
    from orinyx_mcp.config import ConfigError
    from orinyx_mcp.gateway import Gateway, GatewayConfig

    try:
        downstream = GatewayConfig.from_env()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError:
        # urllib's own refusal quotes the URL, and a password in it.
        print("DOWNSTREAM_MCP_URL is malformed (its value is not shown).", file=sys.stderr)
        return 1
    gateway = Gateway(downstream) if downstream else None
    # stderr only: stdout is the MCP protocol stream.
    try:
        client = (
            OrinyxClient(url, key or "", token_provider=provider)
            if provider
            else OrinyxClient(url, key or "")
        )
    except (InsecureUrlError, ConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, httpx.InvalidURL):
        print(UNUSABLE_CONFIG, file=sys.stderr)
        return 1
    with client:
        try:
            server = build_server(shared(client, check_contract=True), gateway=gateway)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

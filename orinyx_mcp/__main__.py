"""`python -m orinyx_mcp` (or `orinyx-mcp stdio`): serve Orinyx tools over stdio to a local
MCP client. `python -m orinyx_mcp serve` (or the `orinyx-mcp` command): the network server.

Configuration is the environment only: ORINYX_API_URL (the running API) and
ORINYX_API_KEY (an ork_live_* key, minted per agent so each one has its own rate-limit
bucket and access-log identity). The DOWNSTREAM_MCP_* variables connect another MCP
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
    if not url or not key:
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
        client = OrinyxClient(url, key)
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

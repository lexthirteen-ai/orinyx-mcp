"""Check that another MCP server can be connected through the Orinyx gateway, without an
Orinyx key: the same connector, allowlist and labelling the service uses.

    export DOWNSTREAM_MCP_URL=https://<their host>/mcp
    export DOWNSTREAM_MCP_TOOLS=search,lookup
    export DOWNSTREAM_MCP_TOKEN=<their key>            # if their server wants one
    export DOWNSTREAM_MCP_NAME="Acme Search"
    python evals/gateway_check.py                                   # list what would be offered
    python evals/gateway_check.py --call search --args '{"q": "x"}' # and call one tool

It lists the tools as an agent would see them through Orinyx, reports allowlisted names the
other server does not offer, and with --call relays one call. Exit 0 when every step answered
as expected, 1 otherwise. The token is read from the environment and is never printed.
"""

import argparse
import asyncio
import json
import re
import sys

# What MCP hosts accept as a tool name; the gateway adds `<prefix>__` in front.
_CLIENT_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")


async def check(call: str | None, arguments: dict) -> int:
    from orinyx_mcp.gateway import Gateway, GatewayConfig

    config = GatewayConfig.from_env()
    if config is None:
        print("Set DOWNSTREAM_MCP_URL and DOWNSTREAM_MCP_TOOLS.", file=sys.stderr)
        return 1
    gateway = Gateway(config)
    failures: list[str] = []

    from mcp.types import PaginatedRequestParams

    offered, cursor = [], None
    try:
        async with gateway._connect() as session:  # one direct look, at the whole listing
            while True:
                params = PaginatedRequestParams(cursor=cursor) if cursor else None
                page = await session.list_tools(params=params)
                offered += [tool.name for tool in page.tools]
                cursor = page.next_cursor
                if not cursor:
                    break
    except Exception as exc:  # noqa: BLE001 - reported, with the type only (never the token)
        print(f"FAILED: {gateway.failure(exc)}", file=sys.stderr)
        return 1
    offered.sort()
    print(f"{config.label} offers {len(offered)} tools:", ", ".join(offered) or "none")

    tools = await gateway.tools()
    print(f"\nthrough Orinyx, an agent sees {len(tools)}:")
    for tool in tools:
        print(f"  {tool.name}\n    {tool.description}")
        if not _CLIENT_TOOL_NAME.fullmatch(tool.name):
            failures.append(
                f"{tool.name} is not a name MCP hosts accept (letters, digits, _ -, 64)"
            )
    missing = sorted(config.tools - set(offered))
    if missing:
        failures.append(f"allowlisted but not offered by {config.label}: {', '.join(missing)}")
    if not tools:
        failures.append("no tool would be offered")

    if call is not None:
        result = await gateway.call(gateway.prefix + call, arguments)
        print(f"\n--- {gateway.prefix}{call} ---")
        for part in result.content:
            print(getattr(part, "text", f"<{type(part).__name__}>"))
        if result.is_error:
            failures.append(f"{call} answered with an error")

    for failure in failures:
        print("FAILED:", failure, file=sys.stderr)
    print("\nresult:", "FAILED" if failures else "ok")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--call", help="an allowlisted tool to call (its own name, no prefix)")
    parser.add_argument("--args", default="{}", help="the call's arguments as a JSON object")
    args = parser.parse_args(argv)
    try:
        arguments = json.loads(args.args)
    except json.JSONDecodeError as exc:
        print(f"--args is not JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(arguments, dict):
        print("--args must be a JSON object", file=sys.stderr)
        return 1
    try:
        return asyncio.run(check(args.call, arguments))
    except ValueError as exc:  # a configuration the gateway refuses
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

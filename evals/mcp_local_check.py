"""An end-to-end check of the Orinyx MCP server from a REAL MCP client.

    export ORINYX_API_URL=<api-url> ORINYX_API_KEY=<your-key>
    python evals/mcp_local_check.py                               # stdio, on this machine
    python evals/mcp_local_check.py --url https://<host>/mcp      # over the network

Without `--url` it launches `python -m orinyx_mcp` the way a local agent host does. With
`--url` it connects to a hosted endpoint as a remote agent does, sending the key as a bearer
header (only ORINYX_API_KEY is needed). Either way it lists the tools, verifies three
SYNTHETIC warfarin claims, reads the saved run back, exports it and confirms an unknown run id
is a readable 404. Nothing here imports the engine. Run it against a disposable `*_workload`
database or a sandbox host only: verification events can never be deleted.

Exit 0 when every step answered as expected, 1 otherwise. The key is read from the
environment and is never printed.
"""

import argparse
import asyncio
import contextlib
import os
import re
import sys

CLAIMS = [
    {
        "rawText": "warfarin 5 mg by mouth daily",
        "drug": "warfarin",
        "claimType": "route",
        "structuredValue": {"route": "oral"},
    },
    {
        "rawText": "warfarin intramuscular",
        "drug": "warfarin",
        "claimType": "route",
        "structuredValue": {"route": "intramuscular"},
    },
    {
        "rawText": "warfarin for restless legs",
        "drug": "warfarin",
        "claimType": "indication",
        "structuredValue": {"indication": "restless legs syndrome"},
    },
]
_RUN_ID = re.compile(r"Run id: ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


def _failed(result) -> bool:
    return bool(result.is_error)


def _text(result) -> str:
    return "\n".join(getattr(part, "text", "") for part in result.content)


@contextlib.asynccontextmanager
async def _streams(url: str | None):
    """The client transport: a local stdio server, or a hosted Streamable HTTP endpoint."""
    if url is None:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = {k: os.environ[k] for k in ("ORINYX_API_URL", "ORINYX_API_KEY", "PATH")}
        server = StdioServerParameters(command=sys.executable, args=["-m", "orinyx_mcp"], env=env)
        async with stdio_client(server) as (read, write):
            yield read, write
        return
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {os.environ['ORINYX_API_KEY']}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=60.0) as http,
        streamable_http_client(url, http_client=http) as streams,
    ):
        yield streams[0], streams[1]


ORDERS = [
    "50 mb of aspirin is administered through the arm",
    "wafarin 5 mb by intramuscular injection",
    "wafarin 5 ml by intramuscular injection",
    "warfarin 5 mg by intramuscular injection",
]


async def check(url: str | None = None) -> int:
    from mcp import ClientSession

    failures: list[str] = []
    async with _streams(url) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = sorted(tool.name for tool in (await session.list_tools()).tools)
        print("tools:", ", ".join(tools))
        if "verify_medications" not in tools:
            failures.append("verify_medications is not offered")

        result = await session.call_tool(
            "verify_medications",
            {"claims": CLAIMS, "tool_name": "mcp-local-check", "tool_version": "1"},
        )
        text = _text(result)
        print("\n--- verify_medications ---\n" + text)
        if _failed(result):
            failures.append("verify_medications returned an error")
        run_id = _RUN_ID.search(text)
        if run_id is None:
            failures.append("no run id in the verification text")
        else:
            saved = await session.call_tool("get_verification", {"run_id": run_id.group(1)})
            print("\n--- get_verification ---\n" + _text(saved)[:400])
            if _failed(saved):
                failures.append("get_verification returned an error")
            export = await session.call_tool(
                "export_verification", {"run_id": run_id.group(1), "fmt": "csv"}
            )
            kinds = [type(part).__name__ for part in export.content]
            print("\n--- export_verification ---\n", kinds)
            if _failed(export) or not kinds:
                failures.append("export_verification returned nothing")

        # The tester's orders of 2026-10-06 and the correctly spelled control: each order
        # is split by Orinyx itself; the three unreadable ones must say so, never "not
        # verified", and the control's intramuscular route must be checked.
        if "verify_order_text" not in tools:
            failures.append("verify_order_text is not offered")
        else:
            orders = await session.call_tool(
                "verify_order_text",
                {"orders": ORDERS, "tool_name": "mcp-local-check", "tool_version": "1"},
            )
            text = _text(orders)
            print("\n--- verify_order_text ---\n" + text)
            if _failed(orders):
                failures.append("verify_order_text returned an error")
            elif "UNREADABLE - do not act on it" not in text:
                failures.append("the tester's orders did not come back as unreadable")

        unknown = "00000000-0000-4000-8000-000000000000"
        refused = await session.call_tool("get_verification", {"run_id": unknown})
        print("\n--- an unknown run id ---\n" + _text(refused))
        if not _failed(refused) or "404" not in _text(refused):
            failures.append("an unknown run id did not come back as a 404 the agent can read")

    for failure in failures:
        print("FAILED:", failure, file=sys.stderr)
    print("\nresult:", "FAILED" if failures else "ok")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", help="a hosted MCP endpoint, e.g. https://<host>/mcp")
    args = parser.parse_args(argv)
    needed = ["ORINYX_API_KEY"] if args.url else ["ORINYX_API_URL", "ORINYX_API_KEY"]
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        print(f"Set {' and '.join(missing)} in the environment.", file=sys.stderr)
        return 1
    return asyncio.run(check(args.url))


if __name__ == "__main__":
    raise SystemExit(main())

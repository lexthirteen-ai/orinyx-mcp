"""Clean-environment install check: an installed stdio server answers MCP and calls no API.

    python -I scripts/e2e_install_check.py --server <venv>/bin/orinyx-mcp --server-arg stdio \\
        --expected release/expected/<version>.json

    python -I scripts/e2e_install_check.py --server <venv>/bin/python \\
        --server-arg=-m --server-arg=orinyx_mcp --expected release/expected/<version>.json

A stub API on 127.0.0.1 records every request and answers 503. The server is started with
exactly three environment variables (PATH, ORINYX_API_URL pointing at the stub, and a
synthetic ORINYX_API_KEY), then asked for `initialize`, `tools/list` and `prompts/list`.
It fails (a `FAIL:` line each, exit 1) when:

* the server name is not `orinyx`;
* the tool set or the prompt set differs from the expected sets given in --expected;
* the synthetic key appears in anything the server sent back, or on its stderr;
* the server made any request to the stub API.

The whole handshake (start, `initialize`, `tools/list`, `prompts/list`) is bounded by
`--timeout` seconds (default 60); a server that does not answer in time is a failed check
(a `FAIL:` line, exit 1), never a hung run.

The expected sets are a JSON file, one per release: {"tools": [...], "prompts": [...]}.
Uses only the standard library and the `mcp` client the package itself depends on. No flag
takes a credential, and the key below is synthetic: it matches no real key.
"""

import argparse
import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

# Written in two pieces so the file holds no literal key-shaped string.
SYNTHETIC_KEY = "ork_" + "live_" + "e2e0synthetic0not0a0real0key0000"
SERVER_NAME = "orinyx"
DEFAULT_TIMEOUT = 60.0


@dataclass
class Observed:
    """What one run of the server showed."""

    server_name: str | None = None
    tools: set[str] = field(default_factory=set)
    prompts: set[str] = field(default_factory=set)
    outputs: list[str] = field(default_factory=list)  # everything the server sent back
    stderr: str = ""
    requests: list[str] = field(default_factory=list)  # what reached the stub API


def evaluate(observed: Observed, expected_tools: set[str], expected_prompts: set[str]) -> list[str]:
    """The failures, one line each. An empty list is a pass."""
    failures = []
    if observed.server_name != SERVER_NAME:
        failures.append(f"server name is {observed.server_name!r}, expected {SERVER_NAME!r}")
    if observed.tools != expected_tools:
        failures.append(
            f"tools differ: missing {sorted(expected_tools - observed.tools)}, "
            f"unexpected {sorted(observed.tools - expected_tools)}"
        )
    if observed.prompts != expected_prompts:
        failures.append(
            f"prompts differ: missing {sorted(expected_prompts - observed.prompts)}, "
            f"unexpected {sorted(observed.prompts - expected_prompts)}"
        )
    if any(SYNTHETIC_KEY in text for text in observed.outputs) or SYNTHETIC_KEY in observed.stderr:
        failures.append("the synthetic key appears in the server's output")
    if observed.requests:
        failures.append(f"the server called the API: {observed.requests}")
    return failures


class Stub(http.server.BaseHTTPRequestHandler):
    """Records the request line and answers 503 to everything."""

    seen: list[str] = []

    def _answer(self):
        type(self).seen.append(f"{self.command} {self.path}")
        body = json.dumps({"error": {"code": "stub", "message": "e2e stub"}}).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _answer

    def log_message(self, *args):
        pass


async def collect(server: str, server_args: list[str], api: str) -> Observed:
    """Start the server the way an agent host does and ask it the three questions."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # `env -i` so the server sees these three variables and nothing else; the SDK would
    # otherwise pass HOME, USER and others through.
    assignments = [
        f"PATH={os.environ.get('PATH', '')}",
        f"ORINYX_API_URL={api}",
        f"ORINYX_API_KEY={SYNTHETIC_KEY}",
    ]
    params = StdioServerParameters(command="env", args=["-i", *assignments, server, *server_args])
    observed = Observed()
    with tempfile.TemporaryFile("w+") as errlog:
        async with (
            stdio_client(params, errlog=errlog) as (read, write),
            ClientSession(read, write) as session,
        ):
            init = await session.initialize()
            tools = await session.list_tools()
            prompts = await session.list_prompts()
        errlog.seek(0)
        observed.stderr = errlog.read()
    observed.server_name = init.server_info.name
    observed.tools = {tool.name for tool in tools.tools}
    observed.prompts = {prompt.name for prompt in prompts.prompts}
    observed.outputs = [
        init.model_dump_json(),
        tools.model_dump_json(),
        prompts.model_dump_json(),
    ]
    return observed


def load_expected(path: Path) -> tuple[set[str], set[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data["tools"]), set(data["prompts"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--server", required=True, help="the installed server command")
    parser.add_argument(
        "--server-arg",
        action="append",
        default=[],
        help="an argument for the server; use --server-arg=-m for a value that starts with '-'",
    )
    parser.add_argument("--expected", type=Path, required=True, help="the release's expected sets")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"seconds allowed for the whole handshake (default {DEFAULT_TIMEOUT:g})",
    )
    args = parser.parse_args(argv)
    try:
        expected_tools, expected_prompts = load_expected(args.expected)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: expected sets cannot be read ({type(exc).__name__})")
        print("e2e install check: FAIL")
        return 1

    stub = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    Stub.seen = []
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{stub.server_address[1]}"
    try:
        observed = asyncio.run(
            asyncio.wait_for(collect(args.server, args.server_arg, api), args.timeout)
        )
        observed.requests = list(Stub.seen)
        failures = evaluate(observed, expected_tools, expected_prompts)
    except TimeoutError:
        failures = [f"the server did not complete the handshake within {args.timeout:g} seconds"]
    except Exception as exc:  # a server that does not start or answer is a failed check
        failures = [f"the server did not complete the handshake ({type(exc).__name__})"]
    finally:
        stub.shutdown()
    for failure in failures:
        print("FAIL:", failure)
    print("e2e install check:", "FAIL" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

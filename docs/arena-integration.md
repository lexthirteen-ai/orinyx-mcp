# Arena tools (off by default)

This describes code in this package that is off by default. The `orinyx_mcp/arena.py` adapter
defines five MCP tools for a supported host's active agent: `start_arena_challenge`,
`submit_arena_answer`, `get_arena_battle`, `get_arena_report`, and `start_arena_rematch`. The
agent receives a synthetic EGH-001 source packet, submits its own answer, inspects the
engine-owned result, and can start a linked rematch that preserves the prior battle. Start and
rematch return a compact browser spectator URL when a dashboard origin is configured. The MCP
does not launch an agent process or grade an answer locally. An answer receipt is not a
clinical verification result.

These tools register only with `ORINYX_ARENA_ENABLED=true`; without it, the server has none of
them. The dashboard is optional: without `ORINYX_ARENA_URL`, start and rematch return battle
IDs and packets without a `spectatorUrl`. If a browser view is available, set that variable to
its HTTPS origin (or a localhost HTTP origin for local testing); the browser needs an
authenticated dashboard session for the same organization. The engine must separately enable
its Arena API. Where these tools are registered, every account's tool list has them. The
spectator URL never contains a credential.

# Testing your MCP server through the Orinyx gateway

For a partner who runs an MCP server and wants its tools offered through the Orinyx connector.
Orinyx connects to your server, offers the tools you agree on beside its own (renamed
`ext__<your tool>`), and labels everything from your server as yours, not Orinyx's. The
design is under [How the gateway works](#how-the-gateway-works) below; the code is
`orinyx_mcp/gateway.py`.

**Synthetic data only, everywhere in these tests.** Never send real patient records, names,
dates or record numbers through either server.

There are four plans. Run them in order: each one needs the one before it to pass.

| Plan | Who runs it | Needs an Orinyx key | Time |
|---|---|---|---|
| A. Compatibility check | you | no | 10 min |
| B. Gateway check against your server | you | no | 15 min |
| C. End to end in an MCP client, on your machine | you | a tester key from Orinyx | 30 min |
| D. Hosted connector | you and Orinyx | a tester key from Orinyx | 30 min |

## What to send Orinyx first

1. Your server's endpoint URL (`https://…/mcp`).
2. The names of the tools you want offered. Nothing else is relayed.
3. How agents should be told where the tools come from, e.g. "Acme Search".
4. A key for Orinyx to use, sent by a secure channel, never in email or chat. It must be a
   **test** key for a test tenant: every Orinyx caller shares it, so your server sees Orinyx,
   not the individual agent.

## Plan A: compatibility check

Each line must be true. If one is not, stop and talk to Orinyx before going on.

- [ ] Your server speaks **Streamable HTTP**. SSE-only and stdio-only servers are not supported.
- [ ] It accepts a **static bearer key** in `Authorization: Bearer …`, or no key. A server that
      only allows an interactive OAuth sign-in cannot be connected.
- [ ] It works when **every call opens a new session**: the gateway runs `initialize` then one
      `tools/list` or `tools/call`, and closes the session. It keeps no session between calls.
- [ ] Each tool you want offered is named with **letters, digits, `_` or `-` only, at most 59
      characters**. Claude refuses tool names over 64 characters, and the gateway adds `ext__`.
      A dot is accepted by the gateway but not by Claude.
- [ ] Your tools answer with an ordinary tool result (text, image or embedded resources).
      Tools that pause to ask the user for input (elicitation, input-required results) are not
      relayed; the agent is told your server "answered in a form this service cannot relay".
- [ ] Your tools take nothing that is secret or per-user. Every Orinyx caller reaches your
      server with the same key.

## Plan B: gateway check against your server

This runs the gateway's own connection code against your server, with no Orinyx account.

```bash
git clone <orinyx-mcp repository> && cd orinyx-mcp
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock -e .
export DOWNSTREAM_MCP_URL=https://<your host>/mcp
export DOWNSTREAM_MCP_TOOLS=<tool>,<tool>
export DOWNSTREAM_MCP_TOKEN=<your test key>
export DOWNSTREAM_MCP_NAME="<your service name>"
python evals/gateway_check.py
python evals/gateway_check.py --call <tool> --args '<a JSON object of arguments>'
```

| # | Check | Pass when |
|---|---|---|
| B1 | The listing | `result: ok`. Every allowlisted tool is listed as `ext__<tool>`, and no tool you left off the list appears. |
| B2 | The labels | Each description starts `[From <your service name>, an external service, not Orinyx.` and then gives your own description. |
| B3 | A call | `--call` prints `From <your service name>, not from Orinyx:` and then your tool's real answer. |
| B4 | A wrong name in the list | Add a name your server does not have to `DOWNSTREAM_MCP_TOOLS`. The check fails with `allowlisted but not offered`. |
| B5 | A wrong key | Set `DOWNSTREAM_MCP_TOKEN=wrong`. The check fails with `could not be reached: …` and does not print the key. |
| B6 | Your server's logs | Every request carried `Authorization: Bearer <your test key>`. None carried a header starting `x-orinyx-`. |

## Plan C: end to end in an MCP client, on your machine

This runs Orinyx on your machine with your server connected, so a real agent sees both sets of
tools. Ask Orinyx for a **tester** API key (`ork_live_…`) and the API address.

Add this to Claude Code (`claude mcp add`) or Claude Desktop as a stdio server.
Command: `<path to>/.venv/bin/python -m orinyx_mcp`. Environment: `ORINYX_API_URL`,
`ORINYX_API_KEY` and the four `DOWNSTREAM_MCP_*` variables from plan B. Then restart the
client.

| # | Step | Pass when |
|---|---|---|
| C1 | Open the tool list. | The Orinyx tools (`start_a_test`, `verify_medications`, …) and your `ext__` tools both appear. |
| C2 | Ask the agent to use one of your tools. | It calls `ext__<tool>`, the answer is your server's, and the agent says it came from your service. |
| C3 | Ask the agent to verify a synthetic claim, e.g. "warfarin 5 mg by mouth daily". | `verify_medications` answers as normal. Your server receives nothing. |
| C4 | Ask a question that needs both servers. | The agent keeps the two apart: it never presents your tool's output as an Orinyx check, verdict or "supported". |
| C5 | Make one of your tools fail on purpose (bad argument). | The agent sees your error text, marked as an error. |
| C6 | Stop your server and ask again. | The Orinyx tools still work. Your tool answers `<your service name> could not be reached: …`. |
| C7 | Restart your server and wait 30 seconds. | Your tools work again without restarting the client. |
| C8 | Ask the agent to call a tool of yours that is not on the list. | It cannot. The tool is not listed, and a direct call answers `Unknown tool`. |

C4 is the most important check. If the agent blurs the two sources, record the prompt and
the agent's exact words.

## Plan D: the hosted connector

Orinyx sets your four values as secrets on the hosted service (`docs/DEPLOY.md`) and tells
you when it is done. Use the same tester key as plan C.

```bash
ORINYX_API_KEY=<tester key> python evals/mcp_local_check.py --url https://<orinyx mcp host>/mcp
```

| # | Step | Pass when |
|---|---|---|
| D1 | Run the command above. | `result: ok`, and the printed tool list includes your `ext__` tools. |
| D2 | Add `https://<orinyx mcp host>/mcp` in claude.ai as a custom connector and sign in. Then repeat C1 to C4. | Same results as on your machine. |
| D3 | Your server's logs | Requests come from the Orinyx host and carry only your test key: no `ork_` token and no `x-orinyx-` header. |
| D4 | Rename or remove an allowlisted tool on your server. | Within 5 minutes it leaves the list. Nothing appears in its place until Orinyx adds the new name. |
| D5 | Add a new tool to your server. | It never appears until Orinyx adds it to the list. |
| D6 | Time 10 calls to one of your tools. | Note the median time. Each call opens a new session, so expect one extra round trip per call. |

## Reporting results

Send Orinyx:
- the plan and check numbers, each marked pass or fail;
- for every fail: what you did, what you expected and what happened, with the exact text;
- the plan B output (it never contains your key);
- your MCP SDK name and version, and the MCP client you used for plans C and D;
- for C4, the prompts you tried and the agent's answers.

## Known limits

- One connected server per Orinyx service, and one key shared by every caller.
- Tools only. Your server's resources and prompts are not relayed.
- The tool list is cached for up to 5 minutes (30 seconds after a failure).
- Each call opens its own session. Server-side state between calls is not kept.

## How the gateway works

The network server can also offer the tools of ONE other remote MCP server, so one connector
carries both. It is off unless `DOWNSTREAM_MCP_URL` is set:

| Variable | Meaning |
|---|---|
| `DOWNSTREAM_MCP_URL` | the other server's endpoint (https; plain http only for localhost) |
| `DOWNSTREAM_MCP_TOKEN` | optional bearer this service presents there |
| `DOWNSTREAM_MCP_TOOLS` | comma-separated tool names to offer (required; nothing else is relayed) |
| `DOWNSTREAM_MCP_PREFIX` | name prefix, default `ext`: its `search` is offered as `ext__search` |
| `DOWNSTREAM_MCP_NAME` | how agents are told where those tools come from (default: its host name) |

Every relayed description and answer is headed as coming from that service, never Orinyx.
The token is one key shared by every caller, and the caller's Orinyx credential is never sent
there. If the other server is down, Orinyx's own tools still list. Only tools are relayed.
Code: `orinyx_mcp/gateway.py`.

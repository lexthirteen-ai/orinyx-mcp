<p align="center">
  <img src="https://raw.githubusercontent.com/lexthirteen-ai/orinyx-mcp/main/orinyx_mcp/assets/orinyx-star-96.png" alt="Orinyx star logo" width="96" height="96">
</p>

<h1 align="center">Orinyx MCP Server</h1>

<!-- mcp-name: io.github.lexthirteen-ai/orinyx-mcp -->

Test your healthcare AI agent against cited FDA labels and coded answer keys. Deterministic:
no LLM in the verdict.

> **Not for clinical use. Orinyx is a testing and evaluation tool that checks medication claims against cited FDA label text. It does not give medical advice, and its results must not be used for diagnosis, treatment or prescribing decisions. A "supported" result means one claim matches the cited label text, not that an order is safe or appropriate. Submit synthetic test data only, never real patient information.**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/LICENSE)
[![CI](https://github.com/lexthirteen-ai/orinyx-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/lexthirteen-ai/orinyx-mcp/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/pyproject.toml)

> **Synthetic data only:** never send real patient records, names, dates or record numbers (claim
> text is stored in the API's audit record).

Apache-2.0. This repository is a **client** of the [Orinyx](https://orinyx.io) API: it holds no
rules, no reference data and no verdict logic, and every tool call is an ordinary REST request
carrying your own credential. The one check it runs itself is a pre-flight refusal: `orinyx
observe` screens what it reads for identifier-shaped text (the engine's own pattern list)
before sending anything. Sign up at [orinyx.io/developers](https://orinyx.io/developers) to use
the hosted connector with your Orinyx account, or mint a personal key for stdio, the CLI
or CI through the [self-serve API](#get-an-api-key).

## Features

- **Orders as written.** `verify_order_text` splits each order into its dose, route and
  frequency claims (rules, no model) and answers with one table row per claim.
- **Structured claims.** `verify_medications` checks `{rawText, drug, claimType,
  structuredValue}` claims of nine types, from `dose_range` to `rems_attestation`.
- **Cited results.** Each supported or flagged row cites the label section or monograph
  paragraph it was judged against. A flag carries a rule-derived severity.
- **FDA reference lookups.** Prescribing-label sections and OTC monograph text, with the SPL
  set ID, version and source address, for developer accounts. Reference text, not a verdict.
- **Scored exams for AI products.** A product account sits an exam on a fixed, synthetic test
  set held on the server; every report adds speed. Families and their limits are in
  [docs/EXAMS.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/EXAMS.md).
- **A CLI for CI.** `orinyx verify` and `orinyx observe` exit 0 clean, 2 flagged, 3 not
  verified and 1 on error, so a pipeline can fail on a flag.
- **Hosted or local.** A hosted connector with nothing to install, or a stdio server from
  PyPI or a checkout, plus a REST client for your own Python code.
- **No model in the verdict.** No language model decides a verdict, a severity or a score.

What is in the box:

| Piece | Entry point | Use it from |
|---|---|---|
| MCP server, stdio | `orinyx-mcp stdio` or `python -m orinyx_mcp` | Claude Code, Claude Desktop, any local agent host |
| MCP server, network (Streamable HTTP) | `orinyx-mcp` or `python -m orinyx_mcp serve` | hosted connectors, remote agents |
| Command-line tool | `orinyx verify --file claims.json` | CI, shell pipelines, frameworks that do not speak MCP |
| Observer (CLI) | `orinyx observe out/` | CI: checks every order in an agent's saved transcripts, not only the ones it reports |
| REST client | `from orinyx_mcp.client import OrinyxClient` | your own Python code |
| Operator script | `python evals/product_exam.py` | registering a product and opening a scored exam |

## When to use this server

- **Check orders exactly as written** with `verify_order_text`: at most 50 orders of 500
  characters, one drug per order; Orinyx splits them.
- **Check claims your agent already structures** with `verify_medications`.
- **Read a run back** with `get_verification`, `get_accuracy` or `export_verification`.
- **Read FDA reference text** with `find_fda_label` and `read_fda_label_section`, or the OTC
  monograph tools (developer accounts). Reference text, not a verdict.
- **Score an AI product on a fixed test set** with the exam tools (product accounts).
- **Not sure yet?** Call `start_a_test`: it lists what your account can run and the next step
  for each.

**Consider something else** when you need an EHR connection, need to send real patient data,
or want a clinical decision. Orinyx does not do any of these: see
[Safety and limits](#safety-and-limits).

## Installation

Use the hosted connector with OAuth, or install the Python package for stdio, the CLI
and CI. Local use needs an API URL and a [personal API key](#get-an-api-key).

| Path | For | What you need |
|---|---|---|
| [Hosted connector](#hosted-connector-the-self-serve-path) | the self-serve path | an Orinyx account from [orinyx.io/developers](https://orinyx.io/developers); no install and no key |
| [Local stdio](#install-from-pypi), the [CLI](#cli-in-ci) and CI | a key holder | an Orinyx API URL and an `ork_live_` key from the self-serve API or an operator |

The only official package is `orinyx-mcp`, published only from
`github.com/lexthirteen-ai/orinyx-mcp`. Anything else named orinyx isn't Orinyx's.

If a step fails, see [docs/TROUBLESHOOTING.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/TROUBLESHOOTING.md). What is tested is
under [Supported environments](#supported-environments).

### Hosted connector (the self-serve path)

Nothing to install and no key: this uses the hosted connector, and you sign in with your
Orinyx account.

1. **Sign up** at [orinyx.io/developers](https://orinyx.io/developers).
2. **Add the connector** `https://orinyx-mcp.fly.dev/mcp` (Streamable HTTP) in your client.
   The steps for each client are below.
3. **Start a test.** Then ask your agent to call `start_a_test`. It lists what your
   account can run and the next step for each.

The client sends you to the Orinyx sign-in page (OAuth 2.1; the API is the authorization
server) and you sign in with your Orinyx account. No API key is needed for this path.

Per-client setup, a CI recipe and exam steps are in [docs/QUICKSTART.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/QUICKSTART.md).
Its [first run](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/QUICKSTART.md#first-run) checks two bundled synthetic orders, one clean
and one with a planted error, and shows the output to expect.

#### Claude Code

```bash
claude mcp add --transport http orinyx https://orinyx-mcp.fly.dev/mcp
```

then run `/mcp` inside Claude Code and authenticate; you are sent to the Orinyx sign-in page.
To use a key issued to you by Orinyx instead of signing in, add
`--header "Authorization: Bearer $ORINYX_API_KEY"`.

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`.

#### Claude Desktop

Add `https://orinyx-mcp.fly.dev/mcp` as a custom connector and sign in with your Orinyx
account. A hosted connector is added as a connector, not in `claude_desktop_config.json`,
which is for local servers.

#### Cursor

For the Cursor editor or CLI, add the connector to `~/.cursor/mcp.json` (or
`.cursor/mcp.json` in a project):

```json
{"mcpServers": {"orinyx": {"url": "https://orinyx-mcp.fly.dev/mcp"}}}
```

- **Editor:** In Cursor Settings, open **Customize → MCPs**, enable `orinyx`, and choose
  **Authenticate**. Sign in with your Orinyx account in the browser.
- **CLI:** From your project directory, run `agent mcp login orinyx` and sign in with your
  Orinyx account.

See the [Cursor quickstart](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/QUICKSTART.md#cursor-editor)
to check the connection and run a synthetic test.

#### Codex

```bash
codex mcp add orinyx --url https://orinyx-mcp.fly.dev/mcp
```

Codex detects the sign-in and opens the Orinyx sign-in page in your browser. Sign in with your
Orinyx account. If you missed it, or it expires later, run `codex mcp login orinyx`.

The same server in `~/.codex/config.toml`, if you prefer to edit it (then run
`codex mcp login orinyx` to sign in):

```toml
[mcp_servers.orinyx]
url = "https://orinyx-mcp.fly.dev/mcp"
```

To use a key issued to you by Orinyx instead of signing in, add
`bearer_token_env_var = "ORINYX_API_KEY"` to that table and export the key in the shell that
starts Codex. In the `codex` terminal UI, `/mcp` lists the servers Codex has connected.

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json`, `.codex/config.toml` or a project `.mcp.json`.

### Get an API key

Beta developers can mint their own keys after signing up and setting a password:

1. Send `POST /v1/auth/login` to your API host with `{"email":"<your email>",
   "password":"<your password>"}` and keep the returned session `token` private.
2. Send `POST /v1/auth/api-keys/self` with `Authorization: Bearer <session token>` and
   `Content-Type: application/json`:

   ```json
   {"name":"beta-laptop","scopes":["verify:read","verify:write"],"expiresDays":30}
   ```

3. Save the response's `key` in your secret store; the raw key is shown only once.
   The `apiKey` object contains its id and metadata. Set `ORINYX_API_URL` to your API
   host (hosted: `https://orinyx-api.fly.dev`) and `ORINYX_API_KEY` to that key in the
   environment of your client process.

Only `verify:read` and `verify:write` are accepted, with at least one required.
Expiry is 1–90 days (default 30). Do not send `email` or `fullAccess`: the key belongs
to your signed-in user only. The session-only `GET /v1/auth/api-keys/self` lists your
keys (`data` and `pagination`; `includeRevoked=true` includes revoked entries), and
`DELETE /v1/auth/api-keys/self/{key_id}` revokes one. API keys and connector OAuth
tokens cannot mint or manage keys. If your API deployment has not enabled these
endpoints yet, use the hosted connector's OAuth sign-in or ask an operator for a key.

Never paste passwords or session tokens into an agent prompt or commit them.

### Install from PyPI

Python 3.11 or later. Once the first PyPI release is published:

```bash
pip install orinyx-mcp
orinyx-mcp stdio
orinyx --help
orinyx verify --file claims.json --tool my-agent
```

Set the API URL and key in the process environment first; see [Get an API key](#get-an-api-key).
For an isolated run without installing into your current Python environment, use
[uv](https://docs.astral.sh/uv/):

```bash
uvx orinyx-mcp stdio
uvx --from orinyx-mcp orinyx --help
```

The `stdio` argument is required: bare `orinyx-mcp` (or `uvx orinyx-mcp`) starts the
HTTP server, not stdio. Agent hosts can launch `uvx` with `args: ["orinyx-mcp", "stdio"]`
and the same API environment variables. Before the first PyPI upload, use the source
install below; a GitHub release alone does not publish the package to PyPI.

### Local stdio (from source)

The stdio server, the CLI and CI each need an Orinyx API URL and a key (`ork_live_...`)
issued by Orinyx through the [self-serve API](#get-an-api-key) or an operator. To develop
from a checkout instead of using PyPI:

```bash
git clone https://github.com/lexthirteen-ai/orinyx-mcp.git && cd orinyx-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e .                                   # Python 3.11+

export ORINYX_API_URL=https://<your orinyx api>
export ORINYX_API_KEY=<an ork_live_ key issued to you>
orinyx-mcp stdio                                   # speaks MCP on stdin/stdout
orinyx-mcp --version                               # prints the installed version
```

The key is read from the environment only; no flag takes it. Register the server with your
agent host as a stdio server:

```json
{
  "mcpServers": {
    "orinyx": {
      "command": "/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp",
      "args": ["stdio"],
      "env": {
        "ORINYX_API_URL": "https://<your orinyx api>",
        "ORINYX_API_KEY": "<an ork_live_ key issued to you>"
      }
    }
  }
}
```

`python -m orinyx_mcp` starts the same stdio server. Any other argument to `orinyx-mcp`
exits 1 with a usage line. Agent hosts launch the stdio server themselves, so point them at
the virtualenv's `orinyx-mcp` by absolute path; a bare `orinyx-mcp` or `python` may not be
the one you installed into.

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`.

#### Claude Code (stdio)

Export the two variables first so the key is not typed on the command line. The key is one
issued to you by Orinyx:

```bash
export ORINYX_API_URL=https://<your orinyx api>
export ORINYX_API_KEY=<your ork_live_ key>
claude mcp add orinyx \
  -e ORINYX_API_URL="$ORINYX_API_URL" \
  -e ORINYX_API_KEY="$ORINYX_API_KEY" \
  -- /absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp stdio
```

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`.

#### Claude Desktop (stdio)

Edit `claude_desktop_config.json` (Settings > Developer > Edit Config) and restart. The key
is one issued to you by Orinyx:

```json
{
  "mcpServers": {
    "orinyx": {
      "command": "/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp",
      "args": ["stdio"],
      "env": {
        "ORINYX_API_URL": "https://<your orinyx api>",
        "ORINYX_API_KEY": "<your ork_live_ key>"
      }
    }
  }
}
```

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`.

#### Codex (stdio)

Add this to `~/.codex/config.toml`. `env_vars` forwards the two variables from the shell that
starts Codex, so the key is never written into the file. The key is one issued to you by
Orinyx:

```toml
[mcp_servers.orinyx]
command = "/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp"
args = ["stdio"]
env_vars = ["ORINYX_API_URL", "ORINYX_API_KEY"]
```

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json`, `.codex/config.toml` or a project `.mcp.json`.

### Docker

The `Dockerfile` builds the network server (its command is `orinyx-mcp`, listening on port
8000); `fly.toml` builds the hosted connector from it. It is configured from the environment,
as under [Network server](#network-server):

```bash
docker build -t orinyx-mcp .
docker run --rm -p 8000:8000 \
  -e MCP_PUBLIC_URL=https://mcp.example \
  -e ORINYX_API_URL=https://api.example \
  orinyx-mcp
```

`MCP_PUBLIC_URL` must be an https URL (plain http only for localhost). The Fly.io layout is in
[docs/DEPLOY.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/DEPLOY.md).

### Supported environments

| Item | Status |
|---|---|
| Python 3.11, 3.12 and 3.13 | tested in CI on Linux |
| Python 3.14 | used in development; not tested in CI |
| macOS | used in development; not tested in CI |
| Windows | untested |
| Transports | stdio (local) and Streamable HTTP (hosted) |
| Cursor CLI on macOS | hosted OAuth and synthetic verification smoke tested |
| Cursor editor on macOS | hosted OAuth and synthetic verification smoke tested |

The hosted connector reports its version at `https://orinyx-mcp.fly.dev/health`.

## Configuration

### Stdio server and CLI

| Variable | Meaning |
|---|---|
| `ORINYX_API_URL` | the Orinyx API (https; plain http only for localhost) |
| `ORINYX_API_KEY` | an `ork_live_` key issued to you by Orinyx |

Credentials come from `ORINYX_API_URL` and `ORINYX_API_KEY` only. The `DOWNSTREAM_MCP_*`
variables under [Gateway](#gateway-another-mcp-server) work over stdio too.

### Network server

Configuration is the environment only:

| Variable | Meaning |
|---|---|
| `MCP_PUBLIC_URL` | the https origin agents connect to; `/mcp` is served there (the `Host` check is built from it) |
| `ORINYX_API_URL` | the Orinyx API this service calls on the caller's behalf |
| `ORINYX_ISSUER_URL` | the API's public origin, named in the resource metadata for sign-in (defaults to the `ORINYX_API_URL` origin) |
| `ORINYX_HOP_SECRET` | optional, at least 32 characters, shared with the API so each agent keeps its own rate-limit bucket |
| `ORINYX_API_ALLOW_HTTP` | `true` only on a private network trusted end to end |
| `TRUST_PROXY_FORWARDED_FOR` | `true` behind exactly one proxy (the host's edge) |
| `TRUSTED_CLIENT_IP_HEADER` | a header that proxy sets to the caller's address (Fly: `fly-client-ip`) |
| `PORT` | listening port (default 8000) |

```bash
MCP_PUBLIC_URL=https://mcp.example ORINYX_API_URL=https://api.example orinyx-mcp
```

How the server handles the bearer an agent presents is in
[docs/DEPLOY.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/DEPLOY.md#how-the-network-server-works).
[docs/DEPLOY.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/DEPLOY.md) has the Fly.io layout.

### Gateway (another MCP server)

The network server can also offer the tools of ONE other remote MCP server, so one connector
carries both. It is off unless `DOWNSTREAM_MCP_URL` is set:

| Variable | Meaning |
|---|---|
| `DOWNSTREAM_MCP_URL` | the other server's endpoint (https; plain http only for localhost) |
| `DOWNSTREAM_MCP_TOKEN` | optional bearer this service presents there |
| `DOWNSTREAM_MCP_TOOLS` | comma-separated tool names to offer (required; nothing else is relayed) |
| `DOWNSTREAM_MCP_PREFIX` | name prefix, default `ext`: its `search` is offered as `ext__search` |
| `DOWNSTREAM_MCP_NAME` | how agents are told where those tools come from (default: its host name) |

What is relayed, and what is never sent there, is in
[docs/GATEWAY_TESTING.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/GATEWAY_TESTING.md#how-the-gateway-works). Partners follow
[docs/GATEWAY_TESTING.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/GATEWAY_TESTING.md), starting with
`python evals/gateway_check.py`.

## How to choose a tool

| Tool | Account | What it does |
|---|---|---|
| `start_a_test` | any | the front door: what this account can run, and the next step |
| `verify_order_text` | developer | orders as written (at most 50 orders of 500 characters, one drug per order); Orinyx splits them |
| `verify_medications` | developer | structured claims `{rawText, drug, claimType, structuredValue}` |
| `get_verification` | developer | a saved run, with its physician-review accuracy if any |
| `get_accuracy` | developer | false-flag rate and catch-rate estimate from physician review |
| `export_verification` | developer | `csv`, `pdf` (full audit) or `report` (one-page committee PDF) |
| `find_otc_monographs`, `get_otc_monograph`, `read_otc_monograph_section` | developer | FDA OTC monograph reference text; not a verdict |
| `find_fda_label`, `read_fda_label_section` | developer | FDA prescribing-label section text as Orinyx cached it from openFDA, with the SPL set ID, version, the product the label describes and the DailyMed address; superseded versions on request, `rxcui` when one set ID backs two drugs; not a verdict |
| `get_next_exam_case` | product | the next case; Orinyx starts its clock |
| `get_exam_cases` | product | every case at once; speed is then reported as not measured |
| `submit_exam_answers` | product | record answers (`claims`, `replyText` or `codes`, by the case's kind) |
| `finish_exam` | product | close and score the sitting |
| `get_exam_report` | product | the scored report |

### Account types

What a credential can reach is fixed by its account type, enforced by the API:

- **Developer account** (a self-serve sign-up at
  [orinyx.io/developers](https://orinyx.io/developers)): the verification tools
  (`verify_order_text`, `verify_medications`, `get_verification`, `get_accuracy`,
  `export_verification`) and the FDA reference lookups (`find_fda_label`,
  `read_fda_label_section`, `find_otc_monographs`, `get_otc_monograph`,
  `read_otc_monograph_section`). Lookups return reference text, not a verdict, and are not
  charged against the monthly checks of the free plan.
- **Product (vendor) account**: the exam tools (`get_next_exam_case`, `get_exam_cases`,
  `submit_exam_answers`, `finish_exam`, `get_exam_report`). A product sitting an exam cannot
  check claims with the clinical verifier, and a product account calling a lookup tool is
  refused.
- **Operator or staff account** (an Orinyx quality lead or admin): registers the product and
  opens its exam with `evals/product_exam.py`. You do not open your own exam; Orinyx does, and
  gives you the run number and a product sign-in. The dashboard is for staff accounts. A label's version
  history and diff, a monograph's version history and its separate orders listing, and a
  regulatory document's content are staff-only too, and are not part of the lookups.
  `get_otc_monograph` still shows the orders that come with a monograph.

`start_a_test` works for every account and says which of these applies.

A developer account runs quick checks and the FDA reference lookups: the exam tools are
refused for a developer account
([release notes](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/RELEASE_NOTES_2026-11-02.md#what-is-not-in-this-release)).

## Available tools

Sixteen tools and one prompt. Each usage example is the call as an MCP client sends it
(`tools/call`, or `prompts/get` for the prompt).

### Verdicts and claim types

Verdicts: `supported`; `contradicted` (a flag, with a rule-derived severity of minor,
moderate or major and a citation); `unreadable` (the order cannot be read as written: a drug
name that is no drug, a unit that is no unit, a body site given as a route; a flag on the
order, uncited because no label was consulted); `abstain` (not verified).

A claim is `{rawText, drug, claimType, structuredValue}`. `claimType` is one of
`dose_range`, `route`, `frequency`, `indication`, `contraindication`, `interaction`,
`monitoring`, `controlled_substance`, `rems_attestation`. One claim type per claim: an order
with a dose and a route is two claims.

### 1. `start_a_test`

Account: any. START HERE. Asks what kind of test you want (a quick check of medication
claims, a scored exam of an AI product, or an FDA reference lookup) and gives the exact next
step for the account that is signed in.

**Best for:**
- The first call, whenever the person has not said which kind of test they want.

**Prompt example:**
> "start a test"

**Usage example:**
```json
{"name": "start_a_test", "arguments": {}}
```

**Returns:** three sections, QUICK CHECK, SCORED EXAM and LOOK SOMETHING UP, each saying
whether this account can use it and what to call next. For a product account it lists the open
exam runs and the steps to sit one. For a developer account, LOOK SOMETHING UP lists the five
lookup tools; if the API refuses an account the lookups, that section says so. When the API
refuses the key or sign-in itself (401), it returns none of the three sections, only a short
message that says so and what to check.

### 2. `verify_order_text`

Account: developer. Verify medication orders exactly as written, e.g. "warfarin 5 mg by mouth
daily" (one drug per order, at most 50 orders of 500 characters). Orinyx splits each order
into its dose, route and frequency claims itself, with no model, and checks each on its own,
so a part it cannot read never hides one it can.

**Best for:**
- Orders exactly as a person or agent wrote them.
- Checking the drugs in one request against each other: pass `check_interactions: true`.

**Not recommended for:**
- Claims your agent already holds in structured form: use `verify_medications`.
- An order that names two drugs (`oxycodone/acetaminophen 5/325 mg by mouth every 6 hours`):
  one drug per order, and the whole request is refused.
- A product account sitting an exam: it cannot also check claims.

**Common mistakes:**
- Correcting, completing or re-spelling an order before sending it. Pass the text unchanged.
- Reading SUPPORTED as a clearance, or an abstain as safe. Abstain means unchecked.
- Sending real patient data: the text is stored in the audit record.

**Prompt example:**
> "Check this order with verify_order_text, exactly as written: acetaminophen 1500 mg by mouth
> every 4 hours."

**Usage example:**
```json
{"name": "verify_order_text", "arguments": {"orders": ["acetaminophen 1500 mg by mouth every 4 hours"]}}
```

To check orders, the agent calls `verify_order_text` with the orders exactly
as written:

```text
verify_order_text(orders=["acetaminophen 1500 mg by mouth every 4 hours"])
```

Optional: `tool_name` and `tool_version` (named in the report header) and `check_interactions`.

**Returns:** Orinyx splits each order into its dose, route and frequency claims (rules, no
model) and answers with one table row per claim. The order above is one of the two
[first-run examples](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/examples/first-run/), with its dose error planted. The output below was
captured on 2026-11-07 from the hosted Orinyx connector (`https://orinyx-mcp.fly.dev/mcp`,
orinyx-mcp 0.1.3). It was not written by hand. Run ids and times differ from run to run:

```text
Orinyx verification - run f57fc863
Checked 3 claims: 1 flagged, 2 supported, 0 abstained.

| # | Claim | Part | Result | Severity | Why | Citation |
|---|---|---|---|---|---|---|
| 1 | acetaminophen 1500 mg by mouth every 4 hours | dose | FLAGGED | MODERATE | Daily exposure 1500.0 mg × 6 doses per day = 9000.0 mg exceeds the explicitly stated maximum of 4000 mg in 24 hours (FDA OTC Monograph, M013.50(d)(2)). Assumption: 'every 4 hours' read as 6 doses in 24 hours, around the clock. | [1] |
| 2 | acetaminophen 1500 mg by mouth every 4 hours | route | SUPPORTED | - | Route 'oral' matches the labeled route. | [2] |
| 3 | acetaminophen 1500 mg by mouth every 4 hours | frequency | SUPPORTED | - | Frequency 'every 4 hours' matches a labeled schedule. | [3] |

Citations:
[1] FDA OTC Monograph, M013.50(d)(2) - id M013.50(d)(2)@v1 - OTC Monograph M013 §M013.50(d)(2): "Adults: Oral dosage is 325 to 650 milligrams every 4 hours or 325 to 500 milligrams every 3 hours or 650 to 1,000 milligrams every 6 hours, while symptoms persist, not to exceed 4,000 milligrams in 24 hours, or as directed by a doctor." (document version 1, sha256 89db91c7edae) - https://www.accessdata.fda.gov/drugsatfda_docs/omuf/monographs/OTC%20Monograph_M013-Internal%20Analgesic%2C%20Antipyretic%2C%20and%20Antirheumatic%20Drug%20Products%20for%20OTC%20Human%20Use%2010.14.2022.pdf
[2] openFDA, openFDA product metadata - id 7f445de3-30cf-4bd8-892d-05979cd399e7 - childrens fever reducer and pain reliever prescribing information, SPL set ID 7f445de3-30cf-4bd8-892d-05979cd399e7, effective 20260909 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=7f445de3-30cf-4bd8-892d-05979cd399e7
[3] openFDA, Dosage and Administration (§2) - id 7f445de3-30cf-4bd8-892d-05979cd399e7 - childrens fever reducer and pain reliever prescribing information, SPL set ID 7f445de3-30cf-4bd8-892d-05979cd399e7, effective 20260909 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=7f445de3-30cf-4bd8-892d-05979cd399e7

Why each severity:
Row 1 (MODERATE): Rated Moderate by Orinyx's curated rule for this dose limit, derived from the cited source (FDA OTC Monograph, M013.50(d)(2)).

FLAGGED: the cited label says otherwise, at the severity shown.
SUPPORTED: consistent with the cited label text; not a judgment that the order suits a patient.

Orinyx flags; the clinician decides.

Note: Supported means one claim agrees with its cited label text. It does not clear the regimen: the daily total, the schedule and patient context are checked only where a row says so.
Orinyx checking time: 29 ms

Checks (beta release candidates; Orinyx names the check behind each row):
Medication Claims (beta): rows 1, 2, 3 - 1 flagged, 2 supported
Semantic Mapping (beta): no rows in this run
Source Evidence (beta): no rows in this run

Run id: f57fc863-a31b-4a0a-af73-440f5d1215b8
```

An order Orinyx cannot read as written (`wafarin 5 mb`) comes back first, as
`UNREADABLE - do not act on it`, with every part it could not read and, where the API
returned them, its own display-only suggestions for the clinician to confirm. Pass the full
run id to `get_verification`, `get_accuracy` or `export_verification`.

### 3. `verify_medications`

Account: developer. Verify STRUCTURED medication claims. Each claim: `{rawText, drug, claimType,
structuredValue}` where claimType is one of `dose_range`, `route`, `frequency`, `indication`,
`contraindication`, `interaction`, `monitoring`, `controlled_substance`, `rems_attestation`.

**Best for:**
- An agent that already produces structured claims.
- Claim types beyond dose, route and frequency, such as `contraindication` or `interaction`.

**Not recommended for:**
- An order as written ("warfarin 5 mg by mouth daily"): use `verify_order_text`.

**Common mistakes:**
- Putting two claim types in one claim. One claimType per claim: an order with a dose AND a
  route is two claims.
- Real patient records or identifiers in `rawText`: it is stored in the audit record.

**Prompt example:**
> "Verify the dose and the route of warfarin 5 mg by mouth daily as two structured claims with
> verify_medications."

**Usage example:**
```json
{
  "name": "verify_medications",
  "arguments": {
    "claims": [
      {
        "rawText": "warfarin 5 mg by mouth daily",
        "drug": "warfarin",
        "claimType": "dose_range",
        "structuredValue": {"dose": 5, "unit": "mg"}
      },
      {
        "rawText": "warfarin 5 mg by mouth daily",
        "drug": "warfarin",
        "claimType": "route",
        "structuredValue": {"route": "oral"}
      }
    ],
    "tool_name": "my-agent",
    "tool_version": "0.3.0"
  }
}
```

**Returns:** what was checked, every flag with its severity, reason and citation, in the same
table as `verify_order_text`, ending with the full `Run id:` line.

### 4. `get_verification`

Account: developer. Read a saved verification run, with its accuracy block if the run has
one.

**Best for:**
- Reading a run again by its run id, for example one a CI job reported.

**Common mistakes:**
- Passing the abbreviated id from the report header. The other tools need the full run id,
  from the `Run id:` line.

**Prompt example:**
> "Read Orinyx run f57fc863-a31b-4a0a-af73-440f5d1215b8 again."

**Usage example:**
```json
{"name": "get_verification", "arguments": {"run_id": "f57fc863-a31b-4a0a-af73-440f5d1215b8"}}
```

**Returns:** the run as the same table, with its accuracy block if the run has one, and the
full `Run id:` line.

### 5. `get_accuracy`

Account: developer. The accuracy tally for a run: the false-flag rate and the catch-rate
estimate, with its sample size. With no review yet it says so and gives no accuracy numbers.

**Best for:**
- The accuracy figures of one run, without the run's table.

**Common mistakes:**
- Passing the abbreviated id from the report header instead of the full run id.

**Prompt example:**
> "Show the false-flag rate for run f57fc863-a31b-4a0a-af73-440f5d1215b8."

**Usage example:**
```json
{"name": "get_accuracy", "arguments": {"run_id": "f57fc863-a31b-4a0a-af73-440f5d1215b8"}}
```

**Returns:** the tally as text. With no review yet it says so, with the number of flags
raised, and gives no accuracy numbers.

### 6. `export_verification`

Account: developer. Export a run as `csv`, `pdf` (full audit) or `report` (one-page committee
PDF; `report.pdf` is accepted too). The default is `csv`.

**Best for:**
- A file to keep or share: a spreadsheet, the full audit, or a one-page committee report.

**Common mistakes:**
- A `fmt` other than `csv`, `pdf`, `report` or `report.pdf`: it is refused with "use csv,
  pdf or report".

**Prompt example:**
> "Export run f57fc863-a31b-4a0a-af73-440f5d1215b8 as the one-page committee report."

**Usage example:**
```json
{"name": "export_verification", "arguments": {"run_id": "f57fc863-a31b-4a0a-af73-440f5d1215b8", "fmt": "report"}}
```

**Returns:** the file as an embedded resource (base64, with its MIME type) at
`orinyx://verifications/<run id>/<file name>`.

### 7. `find_fda_label`

Account: developer. Find the FDA prescribing label Orinyx holds for a drug name or RxCUI (a brand
name only where Orinyx has a curated alias for it): the SPL set ID, label version, effective
date and which sections carry text. Reference text only: not a verification and not a
verdict.

**Best for:**
- Finding the set ID and the sections to read with `read_fda_label_section`.

**Not recommended for:**
- Checking an order: a label's presence says nothing about any order.

**Common mistakes:**
- Respelling a name that is not found, or trying a guessed alternative. A name that is not
  found is reported as given; try the generic name or the RxCUI.

**Prompt example:**
> "Find the FDA prescribing label Orinyx holds for warfarin."

**Usage example:**
```json
{"name": "find_fda_label", "arguments": {"drug": "warfarin"}}
```

**Returns:** each label with its source, SPL set ID, rxcui, version, effective date, whether it
is current, the retrieval date and the DailyMed address; the product the label describes;
and the sections that carry text, with their length.
When the name was matched through an alias, the reply says how it matched; when the name
carried a formulation or salt that Orinyx stripped, it adds a caution that the label may not
describe that formulation.

### 8. `read_fda_label_section`

Account: developer. Read one section of a cached FDA prescribing label by its SPL set ID.
`section` is one of: `contraindications`, `boxed_warning`, `warnings`,
`warnings_and_cautions`, `overdosage`, `dosage_and_administration`, `indications_and_usage`,
`drug_interactions`, `dosage_forms_and_strengths`. Reference text, not a verdict and not
clinical advice.

**Best for:**
- Quoting a label section with its citation.
- A superseded label version: pass `version`, and the reply says so.

**Common mistakes:**
- Relying on a section marked TRUNCATED. A long section comes in parts: call again with the
  offset it gives before relying on the text.
- Leaving out `rxcui` when the reply asks for it. When one set ID backs two drugs, pass the
  one `find_fda_label` showed.

**Prompt example:**
> "Read the dosage and administration section of that warfarin label."

**Usage example:**
```json
{"name": "read_fda_label_section", "arguments": {"set_id": "5a5b5e3a-6556-a542-e063-6294a90a6d3f", "section": "dosage_and_administration"}}
```

**Returns:** the section text with its citation (source, set ID, version, effective date,
whether it is current, retrieval date and DailyMed address), paged at sentence ends. The
DailyMed link is the authoritative copy.

### 9. `find_otc_monographs`

Account: developer. Find FDA over-the-counter (OTC) drug monographs by exact ingredient name (for
example 'acetaminophen'), exact category name, or words in the title. Reference text only: it
is not a verification and not a verdict.

**Common mistakes:**
- A partial ingredient or category name. Those two are exact names; `title_contains`
  matches words in the title.

**Prompt example:**
> "Which FDA OTC monographs cover acetaminophen?"

**Usage example:**
```json
{"name": "find_otc_monographs", "arguments": {"ingredient": "acetaminophen"}}
```

**Returns:** the number matched and up to 25 monographs, each with its id, title, publication
date and registry address.

### 10. `get_otc_monograph`

Account: developer. What one FDA OTC monograph (id like M013) covers: ingredients, categories,
its current documents and its orders.

**Common mistakes:**
- Passing an ingredient name. It takes a monograph id like `M013`, which
  `find_otc_monographs` lists.

**Prompt example:**
> "What does FDA OTC monograph M013 cover?"

**Usage example:**
```json
{"name": "get_otc_monograph", "arguments": {"monograph_id": "M013"}}
```

**Returns:** the monograph's title, publication date and registry address, its ingredients and
categories, its current documents (each with the document number `read_otc_monograph_section`
takes) and its orders.

### 11. `read_otc_monograph_section`

Account: developer. Read FDA OTC monograph text. With only a document number: lists its
sections. With a section reference (like M013.50): returns that section's text and where it
came from. Reference text, not a verdict and not clinical advice.

**Common mistakes:**
- Relying on a section marked TRUNCATED. A long section comes in parts: call again with the
  offset it gives before relying on the text.

**Prompt example:**
> "List the sections of that monograph document, then read M013.50."

**Usage example** (`document_id` is a document number from `get_otc_monograph`; `1` is a
placeholder):
```json
{"name": "read_otc_monograph_section", "arguments": {"document_id": 1, "section": "M013.50"}}
```

**Returns:** the section index, or the section's text with its source: the document, its
version, whether it is current, when it was retrieved and from where. The text is
machine-extracted from the FDA PDF and may contain extraction errors.

### 12. `get_next_exam_case`

Account: product. Sitting an exam: get the next unanswered case (a transcript or a patient
message with patient context, or an encounter note with its date of service) and how to answer
it. Orinyx starts timing the case when it is first served.

**Best for:**
- Sitting an exam one case at a time, so speed is measured.

**Not recommended for:**
- A developer account: exams are for product accounts that Orinyx registers, and a
  developer account calling an exam tool is refused.

**Prompt example:**
> "Get the next case of Orinyx exam run 12."

**Usage example:**
```json
{"name": "get_next_exam_case", "arguments": {"run_id": 12}}
```

**Returns:** the case, the number of cases remaining (this one included) and how to answer it:
medication claims with the claim shapes the checker reads, the reply text, or ICD-10-CM
diagnosis codes. When every case is answered it says to call `finish_exam`, then
`get_exam_report`.

### 13. `get_exam_cases`

Account: product. Sitting an exam: get every case at once (transcripts, patient messages or
encounter notes) and how to answer them.

**Not recommended for:**
- A timed sitting. Speed is then reported as not measured; prefer `get_next_exam_case`.

**Usage example:**
```json
{"name": "get_exam_cases", "arguments": {"run_id": 12}}
```

**Returns:** every case of the run and how to answer them.

### 14. `submit_exam_answers`

Account: product. FOR AN ORINYX EXAM ONLY: record your answers. `answers` is a list with
exactly one answer field each: `{caseId, claims}` for a transcript case, `{caseId, replyText}`
for a patient-message case, or `{caseId, codes}` for an encounter-note case.

**Common mistakes:**
- Correcting a claim that looks wrong. Claims are the medication claims exactly as the exam
  transcript states them, including any that look wrong.
- Giving more than one answer field, or none, in one answer.
- Sending a date with codes (the case has its date of service), CPT or HCPCS codes, or more
  than 25 codes.
- Expecting to change an answer. An answer cannot be changed once recorded, and how Orinyx
  judged it is not shown until the report.

**Prompt example:**
> "Submit the ICD-10-CM codes for this case to exam run 12."

**Usage example:**
```json
{"name": "submit_exam_answers", "arguments": {"run_id": 12, "answers": [{"caseId": "<the case id get_next_exam_case showed>", "codes": ["E11.9"]}]}}
```

An empty claims or codes list is a valid answer. An empty `replyText` is recorded as
unreadable.

**Returns:** how many answers were recorded for the run, and what to call next.

### 15. `finish_exam`

Account: product. Sitting an exam: close the sitting once every case is answered. It is then
scored and no answer can be added.

**Usage example:**
```json
{"name": "finish_exam", "arguments": {"run_id": 12}}
```

Optional: `allow_partial` (default `false`), sent to the API as `allowPartial`. When the report
records a sitting finished that way, its "Answered … cases" line is marked
"(PARTIAL sitting)".

**Returns:** that the run is finished and scored, and the `get_exam_report` call to make.

### 16. `get_exam_report`

Account: product. The report of a finished exam: for a transcript exam the catch rate,
false-flag rate and abstain rate; for a patient-message exam the handled rate, false alarms
and unreadable replies; for an ICD-10-CM coding exam code recall, precision, invalid codes and
exact cases; each with its denominator, the pass/advisory/fail result, and the product's speed
per case.

**Common mistakes:**
- Reading a pass as a clinical safety clearance of the product. It is not one.
- Reading a REHEARSAL result as evidence. A result on an unsigned draft test set is marked
  REHEARSAL and is not evidence.

**Usage example:**
```json
{"name": "get_exam_report", "arguments": {"run_id": 12}}
```

**Returns:** the scored report. What each exam family measures is in
[docs/EXAMS.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/EXAMS.md).

While a product account sits an exam over the network server, the service posts one trace row
per exam tool call to the API with the caller's own credential; a failed trace post is logged
and never changes a tool's answer. Nothing is traced for a developer account's check.

### 17. Prompt: `choose_a_test`

The server also offers one prompt, `choose_a_test`. Ask Orinyx what kinds of test this account
can run.

**Usage example:**
```json
{"name": "choose_a_test", "arguments": {}}
```

**Returns:** a message asking the agent to call `start_a_test`, show the kinds of test it
lists, and ask which one you want before doing anything else.

## CLI in CI

```bash
orinyx verify --file claims.json [--tool NAME] [--tool-version V] [--check-interactions] [--json]
orinyx get <run id> [--json]
orinyx accuracy <run id> [--json]
orinyx export <run id> [--format csv|pdf|report] --out <path>
orinyx observe <path>... [--field DOTTED.PATH] [--tool NAME] [--tool-version V] [--check-interactions] [--json]
```

`claims.json` is a JSON list of claims, or a full request body with an `assertions` list
(its `toolName`, `toolVersion` and `checkInteractions` are used when the flags are absent).
Credentials come from `ORINYX_API_URL` and `ORINYX_API_KEY` only. Today the CLI, and so CI,
needs an `ork_live_` key issued by Orinyx through the [self-serve API](#get-an-api-key)
or an operator; hosted connector OAuth is not a CLI credential.

`verify` takes structured claims. For orders as written, use `orinyx observe` or the
`verify_order_text` tool. `observe` checks every order in an agent's saved output, one run per
record: a `.txt` file is one record with one order per line; in `.jsonl` or `.json`, `--field`
(default `orders`) is the dotted path to each record's orders; a directory reads its `.txt`,
`.jsonl` and `.json` files. Before anything is sent, a record that looks like it holds a
patient identifier refuses the whole run. Setup and output are in
[docs/QUICKSTART.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/QUICKSTART.md#observe-a-test-run).

Exit codes from `verify` and `get`:

| Code | Meaning |
|---|---|
| 0 | clean: no flag and no abstain |
| 1 | error: missing credentials, a usage error, an API refusal, a bad file |
| 2 | flagged: at least one `contradicted` claim or one `unreadable` order |
| 3 | not verified: no flag, but at least one claim abstained (unchecked, not safe) |

`observe` exits with the worst run's code, and 1 when it finds no orders at all. `accuracy`
and `export` exit 0 on success and 1 on error. Usage errors exit 1, never 2, so a
typo cannot read as "flagged".

A GitHub Actions step that fails the job on a flag (full recipe in
[docs/QUICKSTART.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/QUICKSTART.md#ci-recipe)):

```yaml
- name: Check the agent's medication claims with Orinyx
  env:
    ORINYX_API_URL: ${{ secrets.ORINYX_API_URL }}
    ORINYX_API_KEY: ${{ secrets.ORINYX_API_KEY }}
  run: |
    set +e
    orinyx verify --file out/claims.json --tool my-agent --tool-version "${{ github.sha }}"
    code=$?
    case "$code" in
      0) echo "clean" ;;
      2) echo "::error::Orinyx flagged a claim or an unreadable order"; exit 2 ;;
      3) echo "::error::some claims were not verified (abstain is unchecked, not safe)"; exit 3 ;;
      *) echo "::error::orinyx failed (exit $code)"; exit 1 ;;
    esac
```

Keep the key in a repository secret, as above. **Never commit a client config file that holds
a key**, such as `claude_desktop_config.json`, `.cursor/mcp.json` or a project `.mcp.json`.

Gaps in the CLI today:

- No exam subcommands. A product sits an exam through the MCP tools; operators use
  `evals/product_exam.py`.
- No monograph lookups (MCP tools only) and no `--context-label` (the client's
  `verify(..., context_label=...)` takes one).

## REST client

The REST client needs an Orinyx API URL and an `ork_live_` key from the
[self-serve API](#get-an-api-key) or an operator.

```python
from orinyx_mcp.client import OrinyxApiError, OrinyxClient

with OrinyxClient("https://<your orinyx api>", api_key) as client:
    run = client.verify_orders(["warfarin 20 mg by mouth daily"], tool_name="my-agent")
    # or: client.verify([{"rawText": ..., "drug": ..., "claimType": ..., "structuredValue": {...}}])
    print(run.run_id, run.aggregate.contradicted, run.aggregate.unreadable, run.aggregate.abstain)
    for v in run.verdicts:
        print(v.claim_type, v.verdict, v.severity, v.citation.url if v.citation else None)
    if run.flagged:  # contradicted + unreadable
        ...
    pdf = client.export(run.run_id, "report.pdf")  # "csv", "pdf" or "report.pdf"
```

`OrinyxClient(base_url, api_key, *, timeout=30.0, transport=None, headers=None,
allow_http=False)` refuses a non-https URL except for localhost. Other methods: `get_run`,
`accuracy`, `can_verify`, the exam calls (`exam_runs`, `exam_next_case`, `exam_cases`,
`exam_submit`, `exam_finish`, `exam_report`), the monograph reads (`monographs`, `monograph`,
`regulatory_document`) and the operator calls (`create_vendor`, `vendors`, `open_exam`).
Every non-2xx answer, malformed answer or transport failure raises `OrinyxApiError` with
`status`, `code`, `message` and `details`; `run.raw` is the JSON exactly as the API returned it.

## Safety and limits

### What Orinyx does not do

- **No EHR connection.** The MCP server talks only to the Orinyx API. There is no FHIR, no
  Epic, no Cerner integration.
- **No real patient data.** Synthetic test data only, everywhere.
- **No clinical decisions.** Orinyx flags; the clinician decides. `supported` means one
  claim agrees with the cited label text, not that the order suits a patient.
- **No "safe by default".** `abstain` means unchecked, never safe.
- **No model in the verdict.** No language model decides a verdict, a severity or a score.

The release notes list this release's [known limits](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/docs/RELEASE_NOTES_2026-11-02.md#known-limits):
gaps in the knowledge base and the checks. Most show up as a NOT VERIFIED row, a refused
order or a daily total that was not checked, so a missing flag is never evidence that an order
is safe.

## Development

```bash
pip install -e ".[dev]"
pytest          # no database, no engine: fakes stand in for the API
ruff check . && ruff format .
```

`tests/test_client.py::test_nothing_in_the_package_imports_the_engine` keeps this a client:
nothing here may import the Orinyx engine, even when it is installed beside this package.

Scripted checks:

| Script | Proves |
|---|---|
| `python evals/mcp_local_check.py [--url https://orinyx-mcp.fly.dev/mcp]` | a deployment works from a real MCP client (stdio without `--url`) |
| `python evals/gateway_check.py [--call <tool>] [--args '{...}']` | another MCP server can be connected (no Orinyx key needed) |

## Contributing

Contributions are welcome. Setup, the rules a change must keep and how licensing works are in
[CONTRIBUTING.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/CONTRIBUTING.md).

## Security

Report a vulnerability privately, never in a public issue: see [SECURITY.md](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/SECURITY.md).

## Acknowledgements

The Orinyx API can optionally load open-source models from
[OpenMed](https://huggingface.co/OpenMed), published on Hugging Face under the Apache-2.0
license, to read clinical text and screen it for identifiers (see the
[OpenMed NER paper](https://arxiv.org/abs/2508.01630)). These models are **not enabled on the
hosted service**: there, orders are split and identifiers are screened by deterministic
patterns, and no model decides a verdict. Where the models are loaded, they only propose;
cited rules decide every verdict.

Where the optional identifier screen is loaded, it uses a model fine-tuned on the Nemotron-PII
dataset by NVIDIA Corporation, licensed under CC BY 4.0
(https://huggingface.co/datasets/nvidia/Nemotron-PII).

## License

Apache-2.0. See [LICENSE](https://github.com/lexthirteen-ai/orinyx-mcp/blob/main/LICENSE).

# Release notes: orinyx-mcp 0.1.3, 2026-11-05

**This release is not for clinical use. Use it for testing and evaluation with synthetic data only. Results are not medical advice and must not guide patient care.**

orinyx-mcp 0.1.3 is the developer beta release. It names the Orinyx check behind every
result row, rewrites the install docs around the hosted connector, and adds an
`orinyx-mcp stdio` command for local clients. What Orinyx checks, how to read a result and
every known limit are unchanged from
[RELEASE_NOTES_2026-11-02.md](RELEASE_NOTES_2026-11-02.md).

- Connector: `https://orinyx-mcp.fly.dev/mcp` (Claude Code, Claude Desktop, Cursor). Sign up
  at [orinyx.io/developers](https://orinyx.io/developers); setup is in
  [QUICKSTART.md](QUICKSTART.md).
- Orinyx engine 0.3.1, orinyx-mcp 0.1.3.
- Free plan: 200 checks per calendar month (UTC), one account per sign-up.

> **Status of this document.** Written from the code in this release. The hosted connector
> already runs the check names described below. Its `/health` endpoint reports the version of
> the build it runs, which can lag this repository's version.

## What's new

### Every row names its check (beta)

Each result row now says which Orinyx check produced it: **Medication Claims**, **Semantic
Mapping** or **Source Evidence**. A run's output ends with a block headed
"Checks (beta release candidates; Orinyx names the check behind each row):". It lists each
check that ran, its counts (flagged, unreadable, supported, not verified) and the rows it
produced. `verify_order_text`, `verify_medications` and `get_verification` describe this in
their tool descriptions.

- **These checks are beta release candidates, not production-ready.** Each one decides with
  deterministic rules only. No language model takes part in a verdict or a severity.
- **Nothing about a verdict changed.** The same orders and claims get the same results as in
  0.1.2. The block is added after the existing output, so the earlier lines read exactly as
  before, and `Run id:` is still the last line of tool text.
- The names and counts come from Orinyx with each run. Unreadable rows are counted as
  unreadable, never as flagged.

### Install docs: the hosted connector first

- **The README's Installation section starts with the hosted connector.** It is the
  self-serve path: sign up, add the connector to Claude Code, Claude Desktop or Cursor, and
  sign in, with no API key.
- **The stdio server, the CLI and CI need an API key issued by Orinyx.** A self-serve account
  has no key. Every example that holds a key warns never to commit a client config file
  that holds one.
- **New:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md), a "Supported environments" section in
  the README, and an "Official package" section in [SECURITY.md](../SECURITY.md).
- **The only official package is `orinyx-mcp`,** published only from
  `github.com/lexthirteen-ai/orinyx-mcp`. Anything else named orinyx isn't Orinyx's.

### `orinyx-mcp stdio` and `orinyx-mcp --version`

- `orinyx-mcp stdio` starts the stdio MCP server, the same server as `python -m orinyx_mcp`.
  Use it in a local client's config.
- `orinyx-mcp --version` prints the installed version.
- **Changed:** `orinyx-mcp` with any other argument, for example `orinyx-mcp serve`, now
  exits 1 with a usage line. Before, it started the network server. With no argument,
  `orinyx-mcp` is still the network server, unchanged.

## Gates for this release

- The engine's pass-required regression gate names ten checks and reads
  `release-check 10/10`.
- False support is 0 known-failure cases (ceiling 0).
- The not-for-clinical-use statement opens the server instructions, every tool description,
  the README's first screen and these notes. Tests pin its exact text in the server
  instructions, the tool descriptions and the README.

## Known limits

Unchanged. Read [Known limits](RELEASE_NOTES_2026-11-02.md#known-limits) before you rely on
a result. A missing flag is never evidence that an order is safe, and a NOT VERIFIED row was
not checked.

## Reporting a problem

Two channels, both on the public release repository `lexthirteen-ai/orinyx-mcp`:

- **A vulnerability:** use GitHub private vulnerability reporting, from that repository's
  **Security** tab (https://github.com/lexthirteen-ai/orinyx-mcp/security/advisories/new).
  Never open a public issue for a vulnerability.
- **Anything else** (a wrong or missing flag, a refused order, an install or connection
  problem): open an **Issue** there with the "Report a problem" template. Include:
  - the version or commit (`orinyx-mcp --version`, or `/health` for the hosted server);
  - the full run id (the `Run id:` line in the tool output; from the CLI, re-run with `--json`
    and copy `runId`);
  - what you expected and what happened.

Never include real patient data, credentials or keys in a report, and do not name other
testers.

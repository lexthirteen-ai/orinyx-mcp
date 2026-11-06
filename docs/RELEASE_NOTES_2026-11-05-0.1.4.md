# Release notes: orinyx-mcp 0.1.4, 2026-11-05

**This release is not for clinical use. Use it for testing and evaluation with synthetic data only. Results are not medical advice and must not guide patient care.**

orinyx-mcp 0.1.4 is a documentation release. It changes no tool name and no input schema, and
no verdict changes. Developer accounts can use the five FDA reference lookups, and the
README, the smoke tests and `start_a_test` now say so. What Orinyx checks, how to read a
result and every known limit are unchanged from
[RELEASE_NOTES_2026-11-02.md](RELEASE_NOTES_2026-11-02.md). The 0.1.3 changes are in
[RELEASE_NOTES_2026-11-05.md](RELEASE_NOTES_2026-11-05.md).

- Connector: `https://orinyx-mcp.fly.dev/mcp` (Claude Code, Claude Desktop, Cursor, Codex).
  Sign up at [orinyx.io/developers](https://orinyx.io/developers); setup is in
  [QUICKSTART.md](QUICKSTART.md).
- Orinyx engine 0.3.1, orinyx-mcp 0.1.4.
- Free plan: 200 checks per calendar month (UTC), one account per sign-up.

> **Status of this document.** Written from the code in this release. The lookup access
> described below is a change in the Orinyx API, which the hosted connector already uses.
> The connector's `/health` endpoint reports the version of the build it runs, which can lag
> this repository's version.

## What's new

### Developer accounts can use the five lookups

A developer account (a self-serve sign-up) can use these tools:

- `find_fda_label`
- `read_fda_label_section`
- `find_otc_monographs`
- `get_otc_monograph`
- `read_otc_monograph_section`

`start_a_test` lists them under LOOK SOMETHING UP for a developer account.

- **Reference text, not a verdict.** A lookup returns text from an FDA label or an OTC
  monograph. It does not check an order and it does not say anything is safe.
- **Not charged against your checks.** Lookups do not count against the monthly checks of the
  free plan.
- **How the name was matched.** On a label lookup the reply says how the name was matched. A
  formulation or salt Orinyx stripped from the name is shown as a caution.

### Still staff-only

- A label's version history and diff.
- A monograph's version history and its separate orders listing.
- A regulatory document's content.
- The dashboard.

Product (vendor) accounts are still refused every lookup. The exam tools stay with product
accounts that Orinyx registers.

### Install

The README's installation steps are unchanged in substance. The hosted connector is still the
self-serve path, with Claude Code, Claude Desktop, Cursor and Codex steps. The stdio server,
the CLI and CI still need an API key issued by Orinyx. Every example that holds a key warns
never to commit a client config file that holds one: `claude_desktop_config.json`,
`.cursor/mcp.json`, `.codex/config.toml` or a project `.mcp.json`.

## Gates for this release

- The not-for-clinical-use statement opens the server instructions, every tool description,
  the README's first screen and these notes. Tests pin its exact text in the server
  instructions, the tool descriptions and the README.
- Tests pin the lookup wording in the README, the smoke tests and `start_a_test`.

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

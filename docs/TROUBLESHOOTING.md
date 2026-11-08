# Troubleshooting

Each row is a symptom you may see, its usual cause and the fix. Setup steps are in the
README's [Installation](../README.md#installation) section and in
[QUICKSTART.md](QUICKSTART.md). Synthetic data only throughout.

The hosted connector `https://orinyx-mcp.fly.dev/mcp` is the self-serve path: you sign in with
your Orinyx account and need no key. The stdio server, the CLI and CI need an `ork_live_` key
issued to you by Orinyx; a self-serve sign-up does not include one.

| Symptom | Cause | Fix |
|---|---|---|
| `Set ORINYX_API_URL and ORINYX_API_KEY in the environment.` | The stdio server or the CLI got no environment | For an MCP client, put both in the client's `env` block (Claude Code: `-e`), not only in your shell. For the CLI, export both in the shell that runs it; in CI, set both as the step's `env:` from secrets, as in the [CI recipe](QUICKSTART.md#ci-recipe) |
| `orinyx-mcp` stops with `Set MCP_PUBLIC_URL and ORINYX_API_URL` | You started the network server | For a local client use `orinyx-mcp stdio` (from 0.1.3) or `python -m orinyx_mcp` |
| `ORINYX_API_URL must use https (plain http only for localhost).` | The URL is plain http | Use the API's https address (the hosted API is `https://orinyx-api.fly.dev`) |
| 401 `Invalid or revoked API key.` | The key is wrong, expired (keys last at most 90 days) or revoked | Ask whoever issued the key (Orinyx) for a new one and update the client's `env`. A self-serve account has no key: use the hosted connector and sign in |
| 403 `... does not cover this surface` | The tool is not for your account type (for example exam tools on a developer account, or verification and lookup tools on a product account) | Call `start_a_test`: it lists what your account can run. Developer accounts can use the five FDA reference lookups described below |
| 429 `quota_exceeded` | The org's monthly checks are used up (free plan: 200) | Wait for the UTC month to reset (see `Retry-After`) or ask Orinyx about a plan |
| The hosted sign-in loops or is refused | Your account's password may not be set | Open the welcome email and follow its single-use set-password link (`/oauth/invite`). If you have not set a password and need a fresh link, sign up again with the same email. If no email arrives after 10 minutes, contact hello@orinyx.io |
| Claude Desktop: `spawn <command> ENOENT` (for example `spawn python ENOENT`) | Claude Desktop's `PATH` does not have that command | Give the `orinyx-mcp` command of your from-source install's virtualenv by absolute path, with `stdio` as its argument, as in the README: `/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp` with `"args": ["stdio"]` |
| A run is refused before sending | `orinyx observe` found something that looks like an identifier | Synthetic data only: remove it. The message names the pattern, never the text |
| Exit code 3 in CI | At least one claim abstained | Abstain means unchecked, not safe. Decide your policy, as in the [CI recipe](QUICKSTART.md#ci-recipe) |

Never commit a client config file that holds a key, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`. Never put a real key, or real patient data, in a
problem report: see [SECURITY.md](../SECURITY.md).

## FDA reference access

Developer accounts, including free self-serve accounts, can use `find_fda_label`,
`read_fda_label_section`, `find_otc_monographs`, `get_otc_monograph` and
`read_otc_monograph_section`. These return reference text, not a verdict, and do not count
against the free plan's monthly checks. Product accounts cannot use these lookups. A label's
version history and diff, a monograph's version history and separate orders listing, a
regulatory document's content and the dashboard remain staff-only.

If a developer lookup is refused, check which account you signed in with and call
`start_a_test`. If that account is a developer account and a listed lookup is still refused,
report the tool name and error through the [problem-reporting channel](../SECURITY.md#reporting-anything-else).
Do not include credentials or patient data.

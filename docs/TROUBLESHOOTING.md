# Troubleshooting

## Local CLI login

`orinyx login` requires the L9 engine update and a native macOS Keychain or Linux
Secret Service session. A locked or unavailable keychain fails closed; unlock it in
your desktop session and retry. There is no plaintext fallback. On headless Linux/CI,
use an API key in `ORINYX_API_KEY` with `ORINYX_API_URL` instead. API keys always win
over saved login; unset the key to select your login. Do not paste keys into command flags.

For `--no-browser`, open the displayed authorization URL on the same computer as the
CLI, within three minutes. SSH forwarding/device codes are not supported. Declined or
timed-out consent can be retried; commands never open a browser implicitly. After a
revoked, uncertain, or expired refresh, run `orinyx logout` then `orinyx login` again.
An offline logout removes local credentials but warns that server revocation is unconfirmed;
invalidate remaining grants by ending your account sessions. Use the same API origin as
login for status/logout; a different origin is intentionally a separate credential.

Arena also needs server enablement, tester eligibility, and `ORINYX_ARENA_ENABLED=true`
locally. Login does not grant exams or bypass Arena gates. `orinyx status --json` shows
credential source and scopes, never bearer tokens. Never attach keychain exports to an issue.

Each row is a symptom you may see, its usual cause and the fix. Setup steps are in the
README's [Installation](../README.md#installation) section and in
[QUICKSTART.md](QUICKSTART.md). Synthetic data only throughout.

The hosted connector `https://orinyx-mcp.fly.dev/mcp` is the self-serve path: you sign in with
your Orinyx account and need no key. Local CLI/stdio support login after the L9 engine update;
CI and explicit key-based use need an `ork_live_` key
issued by Orinyx through the [self-serve API](../README.md#get-an-api-key) or an operator.

| Symptom | Cause | Fix |
|---|---|---|
| `Set ORINYX_API_URL and ORINYX_API_KEY in the environment.` | The stdio server or the CLI got no environment | For an MCP client, put both in the client's `env` block (Claude Code: `-e`), not only in your shell. For the CLI, export both in the shell that runs it; in CI, set both as the step's `env:` from secrets, as in the [CI recipe](QUICKSTART.md#ci-recipe) |
| `orinyx-mcp` stops with `Set MCP_PUBLIC_URL and ORINYX_API_URL` | You started the network server | For a local client use `orinyx-mcp stdio` (from 0.1.3) or `python -m orinyx_mcp` |
| `ORINYX_API_URL must use https (plain http only for localhost).` | The URL is plain http | Use the API's https address (the hosted API is `https://orinyx-api.fly.dev`) |
| 401 `Invalid or revoked API key.` | The key is wrong, expired (keys last at most 90 days) or revoked | Mint a replacement through the [self-serve API](../README.md#get-an-api-key), or ask your operator, and update the client's `env`. Alternatively use the hosted connector and sign in |
| 403 `... does not cover this surface` | The tool is not for your account type (for example the exam or label tools on a developer account) | Call `start_a_test`: it lists what your account can run |
| 429 `quota_exceeded` | The org's monthly checks are used up (free plan: 200) | Wait for the UTC month to reset (see `Retry-After`) or ask Orinyx about a plan |
| The hosted sign-in loops or is refused | You never set a password | Use the invite link from the sign-up email (`/oauth/invite`); request a new one by signing up again with the same email |
| Claude Desktop: `spawn <command> ENOENT` (for example `spawn python ENOENT`) | Claude Desktop's `PATH` does not have that command | Give the `orinyx-mcp` command of your from-source install's virtualenv by absolute path, with `stdio` as its argument, as in the README: `/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp` with `"args": ["stdio"]` |
| A run is refused before sending | `orinyx observe` found something that looks like an identifier | Synthetic data only: remove it. The message names the pattern, never the text |
| Exit code 3 in CI | At least one claim abstained | Abstain means unchecked, not safe. Decide your policy, as in the [CI recipe](QUICKSTART.md#ci-recipe) |

Never commit a client config file that holds a key, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`. Never put a real key, or real patient data, in a
problem report: see [SECURITY.md](../SECURITY.md).

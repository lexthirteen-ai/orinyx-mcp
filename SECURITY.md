# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Report a vulnerability through GitHub private vulnerability reporting on the public release
repository, `lexthirteen-ai/orinyx-mcp`: on that repository's page, open the
**Security** tab and choose **Report a vulnerability**
(https://github.com/lexthirteen-ai/orinyx-mcp/security/advisories/new). The report is
visible only to you and the maintainers. Private vulnerability reporting is enabled on the
release repository at publication. Please do not open a public issue, discussion or pull
request for a vulnerability.

A useful report says which version or commit you tested, how to reproduce the problem and
what an attacker could do with it. Use synthetic data only in a vulnerability report too:
never include real patient data, credentials or keys, and replace any key with a placeholder.

## Reporting anything else

Everything that is not a vulnerability (a wrong or missing flag, a refused order, an install or
connection problem, a confusing message) goes to **Issues** on `lexthirteen-ai/orinyx-mcp`
using the "Report a problem" template, which asks for the version or commit, the full run id,
what you expected and what happened, with synthetic data only.

**Never include real patient data, credentials or keys in a report.** That means no patient
records, names, dates or record numbers, and no `ork_live_` key, sign-in token or other
secret. Use synthetic data, and replace any key with a placeholder.

## Official package

The only official package is `orinyx-mcp`, published only from
`github.com/lexthirteen-ai/orinyx-mcp`. Anything else named orinyx isn't Orinyx's.

## What this server is

This repository is a **client** of the [Orinyx](https://orinyx.io) API: it holds no rules, no
reference data and no verdict logic, and every tool call is an ordinary REST request carrying
the caller's own credential.

- The stdio server and CLI read API keys only from the environment; no flag takes a key.
  Alternatively, `orinyx login` uses browser OAuth with S256 PKCE and a state-checked
  loopback callback. CLI grants cover verification and Arena according to account role,
  never exams. The engine enforces scopes and retains every existing Arena gate.
- Local OAuth credentials are stored only in native macOS Keychain or Linux Secret Service,
  bound to the API origin. No plaintext fallback, dotenv, CWD or credentials-file reader
  exists. A private, owner-only cache directory contains refresh locks, not credentials.
  Refresh is serialized across processes; uncertain exchanges require sign-in again rather
  than replaying a spent refresh token. Explicit environment keys always take precedence.
- `orinyx logout` attempts server revocation and removes local credentials. A network failure
  is reported, not treated as confirmed revocation. Environment API keys are not changed.
- The network server holds no database, no key of its own and no service credential. The
  bearer an agent presents is handed to the API, which describes or refuses it; the tool call
  then becomes a REST request carrying that same bearer.

How the network server is deployed is in [docs/DEPLOY.md](docs/DEPLOY.md#how-the-network-server-works).

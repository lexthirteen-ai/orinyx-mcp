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

## What this server is

This repository is a **client** of the [Orinyx](https://orinyx.io) API: it holds no rules, no
reference data and no verdict logic, and every tool call is an ordinary REST request carrying
the caller's own credential.

- The stdio server and the CLI read your API URL and key from the environment only; no flag
  takes the key.
- The network server holds no database, no key of its own and no service credential. The
  bearer an agent presents is handed to the API, which describes or refuses it; the tool call
  then becomes a REST request carrying that same bearer.

How the network server is deployed is in [docs/DEPLOY.md](docs/DEPLOY.md#how-the-network-server-works).

---
name: "Report a problem"
about: "Report unexpected behavior using synthetic data only."
---

Synthetic data only, including in logs, screenshots and attachments.

**Never include real patient data, credentials or keys in a report.** That means no patient
records, names, dates or record numbers, and no `ork_live_` key, sign-in token or other
secret. Use synthetic data, and replace any key with a placeholder.

Do not paste tester email addresses or name other testers.

For suspected security vulnerabilities, follow this repository's `SECURITY.md` instead of
opening a public issue.

## Version or commit

Which version or commit did you test? For hosted use, copy `commitSha` from `/health`
at the server you tested. For a checkout, run `git rev-parse HEAD`. The CLI has no
`--version` flag.

## Run ID

Provide the full run ID from the MCP output's `Run id:` line, not the abbreviated
header ID. CLI: re-run your synthetic test with `--json` and copy `runId`. If no run
was created, say so.

## Expected behavior

What did you expect to happen?

## Actual behavior

What happened instead? Include only synthetic examples and remove credentials and keys
from any output you share.

## Synthetic reproduction steps (optional)

How can we reproduce the problem using synthetic data only?

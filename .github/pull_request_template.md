## Linked issue

Fixes <issue>

## What changed

<!-- One or two sentences per change, and why. Name the files or modules touched. -->

## Tests run

<!-- Paste the real counts from this branch. A check that could not run is "not run", never passed. -->

- [ ] `ruff check .` and `ruff format --check .`: pass / fail
- [ ] `pytest -q`: <passed> passed, <failed> failed, <skipped> skipped, <xfailed> xfailed
- CI run: <link>

## Change type and its gates

<!-- Tick every type that applies, and complete its gates. Delete the types that do not apply. -->

- [ ] **Output contract or schema** (readable text, `Run id:` or `UNREADABLE - do not act on it`, `--json`, exit codes, tool names, input schemas, verdict words, severities)
  - [ ] Maintainer decision recorded: <link>
  - [ ] A test pins the exact new output
- [ ] **Auth or security** (credentials, configuration, the HTTP server, sign-in, the identifier screen)
  - [ ] Security review: <verdict and link>
- [ ] **Other** (docs, tests, tooling, CI): <say which>

## Risk

<!-- low / medium / high, and why. What breaks if this is wrong, and who notices first? -->

Risk: <low | medium | high>, because <reason>

## Rollback

- Code: revert this PR's merge commit.
- Migration: none (this package has no database).
- Hosted service (maintainer only): `fly releases -a orinyx-mcp --image`, then `fly deploy -a orinyx-mcp --image <previous image>`.

## Agent run

<!-- Fill in when a coding agent opened this PR. Delete for a hand-written change. -->

- Agent: <tool, for example Claude Code, Codex or Devin>
- Run: <link or id>
- Retries: <n>
- Reviewer: <reviewer> (never the author)

## Checklist

- [ ] Synthetic data only: no real patient records, names, dates or record numbers
- [ ] No secrets, keys, tokens or `.env` content in the diff, the description or pasted logs
- [ ] No real person's name, and no internal name or local path, in code, docs or this description
- [ ] Docs updated where facts changed (rule changes in AGENTS.md need the maintainer's recorded approval)
- [ ] Draft PR; a coding agent merges only on the maintainer's instruction and never deploys

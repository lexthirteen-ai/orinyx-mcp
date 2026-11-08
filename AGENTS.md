# AGENTS.md: orinyx-mcp

Instructions for coding agents (Claude Code, Codex, Devin, Cursor and others) working in this
repository. Read this file before you change anything. People contributing by hand follow
the same rules.

## Architecture rules

1. **This package is a client.** It holds no rules, no reference data and no verdict logic.
   Every clinical result comes from the Orinyx API over REST with the caller's own credential.
   Nothing in the package may import the Orinyx engine, even when it is installed beside it
   (`tests/test_client.py::test_nothing_in_the_package_imports_the_engine`).
2. **Local logic lives in one place:** the `observe` pre-flight identifier screen
   (`orinyx_mcp/screen.py`). It decides only whether text may be sent, never a verdict.
3. **Configuration and credentials come from the environment only** (`ORINYX_API_URL`,
   `ORINYX_API_KEY` and the server's settings (`ORINYX_*`, `MCP_PUBLIC_URL`, `PORT`,
   `TRUST_PROXY_*`, `TRUSTED_CLIENT_IP_HEADER`, `DOWNSTREAM_MCP_*`)), never from flags, and no
   message, error or log prints a key or secret.
4. **Results are shown as the API returned them.** An abstain is unchecked, never safe. Never
   add, infer or reword a reason, a correction or a verdict.
5. **Output contracts do not change without a maintainer decision.** Agents, CI jobs and
   published examples depend on them exactly:
   - **Readable text** printed by the tools and the CLI (`orinyx_mcp/text.py`, the report
     renderer in `orinyx_mcp/tools/reports.py`, the tools under `orinyx_mcp/tools/` and the
     prose in `orinyx_mcp/copy.py`). No line is added, reordered or reworded.
   - **Fixed strings:** `Run id: <uuid>` (parsed by `evals/mcp_local_check.py`) and
     `UNREADABLE - do not act on it`.
   - **`--json`** prints the API's response unchanged (`observe --json` lists each run's
     unchanged response).
   - **Exit codes:** 0 clean, 1 error or usage error, 2 flagged or unreadable, 3 not verified.
     A usage error is never 2.
   - **Tool surfaces:** tool names, input schemas, verdict words and severities.
6. **Synthetic data only.** Never put real patient records, names, dates or record numbers in
   code, tests, fixtures, examples, issues, pull requests or pasted logs.

## Roles

- **Maintainer** (the repository owner): final authority. Approves design changes, high-risk
  work, output-contract changes, every merge and every release. The only person who deploys.
- **Coding agent:** implements one assigned issue on its own branch and opens a draft pull
  request, once agent pushing is enabled. Merges only when the maintainer says so in the
  session; never deploys.
- **Reviewer:** an independent agent or person who reviews the diff against the issue's
  acceptance criteria. Never the agent that wrote the change.

## Coordination rules

1. Every implementation task references an issue in the issue tracker.
2. Only one coding agent owns an issue at a time. If the issue is already assigned or locked,
   stop.
3. All work happens on an isolated branch, one branch per issue.
4. Independent review uses the resulting diff and the acceptance criteria, never the author's
   reasoning.
5. Once agent pushing is enabled (see Permission model), agents may push to authorized feature
   branches (`agent/**`, or `devin/**` for Devin) and open draft pull requests; until then,
   stop at a local commit and record the branch and test counts.
6. Agents never deploy, and merge only on the maintainer's instruction in the session.
7. A security failure, or a result that misstates what the API returned, stops the work and is
   escalated to the maintainer on the issue.
8. Every task produces traceable evidence: test counts, CI links and the review verdict on the
   pull request.
9. Outcomes are recorded on the issue.
10. A failed issue-tracker update produces a visible warning and is retried; it is never
    dropped silently.

## Permission model

Coding agents may:
- read the repository; create branches; commit;
- push only to `agent/**` branches (`devin/**` for Devin);
- open **draft** pull requests;
- run tests and CI;
- update the issue tracker.

Coding agents never deploy, and merge only on the maintainer's instruction. Until the
maintainer has enabled agent identities and branch rules, agents push nothing: they commit
locally and the maintainer pushes.

## Never allowed

- Pushing to `main` or to any branch outside `agent/**` or `devin/**`; force-pushing; rewriting
  history.
- Merging a pull request without the maintainer's instruction, or approving your own.
- Deploying anything, or holding a production credential or deploy token.
- Adding rules, reference data or verdict logic, or importing the engine.
- Changing an output contract without a recorded maintainer decision.
- Real patient data anywhere, including test fixtures and pasted logs.
- Committing a secret, a key or a `.env` file.
- Weakening, skipping or deleting a test to make a check pass.
- A dependency or version change the issue did not ask for.
- Editing `.github/workflows/`, even where an app's permissions allow it: propose a CI change
  in the PR description and the maintainer makes it.
- Changing the rules in `AGENTS.md` (roles, permission model, coordination rules, never-allowed list)
  or the PR template without the maintainer's recorded approval. Factual updates are fine.

## Check recorded results

Never assume another agent's work is done. Before you build on it, check the record: the branch
and commit exist, CI is green on that commit, and the review verdict is on the pull request.
A claim in a message is not a record.

## Workflow

1. **Issue.** Confirm the issue, its acceptance criteria and that no one else owns it.
2. **Branch** from `main`: `agent/<issue-id>-<slug>`.
3. **Test first.** Write the failing test that states the behaviour, then make the change. A
   change to readable text needs a test that pins the exact bytes.
4. **Verify locally.** No database, engine or API key is needed; fakes stand in for the API:
   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.lock && pip install -e ".[dev]" "ruff==0.15.20"
   ruff check . && ruff format --check .
   pytest -q
   ```
   Report the real counts. A check you could not run is reported as not run, never as passed.
5. **Draft pull request**, once agent pushing is enabled (see Permission model): open it from
   `.github/pull_request_template.md`, linking the issue. Until then, stop at a local commit and
   record the branch and test counts.
6. **Record** the outcome on the issue: branch, commit, pull request, counts and verdicts.

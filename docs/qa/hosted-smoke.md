# Repeatable hosted smoke test

Use synthetic orders and a dedicated test account. This is a run sheet, not a
clinical validation or release approval.

**Stop rules.** If a step fails, stop: publish nothing, record the step, the time and
what you saw, leave the remaining rows NOT RUN, and route the failure for review. At
T1, if any Arena tool is listed (`start_arena_challenge`, `submit_arena_answer`,
`start_arena_rematch`, `get_arena_battle`, `get_arena_report`), stop there and do not
launch: the hosted server is running with `ORINYX_ARENA_ENABLED=true`.

**Required steps.** Every row of the Steps table is required, except D1 when the
dashboard is not deployed (see below), and so is each client-matrix row for a client
the candidate documentation supports. The overall result is PASS only when every
required step is PASS: a failed, blocked or unexecuted required step prevents it.

The source checklist is [the October 29 checklist](../SMOKE_TEST_2026-10-29.md).
Its expected order output is a recorded product fixture, not a clinical judgment.
Before a later release, the owner must confirm that fixture and the client/tool
contract at the candidate commit; do not silently change expectations to match a run.

## Run identity

Copy this file for each run; keep completed records outside the source tree.

| Field | Value |
|---|---|
| Started / completed (UTC) | |
| Operator / reviewer | |
| Candidate MCP commit and version | |
| Deployed MCP commit (MCP `/health` `commitSha`) | |
| Deployed engine revision (release record or API image label; not a version string) | |
| Engine KB/source revision, or unavailable | |
| Client and version | |
| Account alias (no email/password/token) | |
| Target MCP / API | https://orinyx-mcp.fly.dev / https://orinyx-api.fly.dev |
| Verification run ID | |
| Overall result: PASS / FAIL / BLOCKED / NOT RUN | NOT RUN |
| Evidence / issue links | |

**Provenance.** Read the deployed MCP commit from MCP `/health` `commitSha`. The API's
`/health` reports no commit, so take the deployed engine revision from the release
record or the API deploy's image label, never from a version string. These rows
depend on provenance:

- T1 and N1 are judged against the candidate README and server: the deployed MCP
  commit must be recorded and equal the candidate MCP commit.
- T3 is judged against the recorded fixture: the deployed engine revision must be
  recorded.
- V1 needs the deployed engine revision to be `d7ac5cf` or a later build that retains
  the change.

When the provenance a row depends on is unrecorded or does not match, record that row
BLOCKED, whatever the client showed. A run with no recorded engine revision cannot be
PASS overall. Record the engine KB/source revision where it is available; when it is
not, write "unavailable": T3's exact match against the fixture is then the only
knowledge-base check.

Never copy credentials, welcome links, tester identities or patient data into logs,
screenshots, issues or this sheet.

## Steps

For every row record PASS, FAIL, BLOCKED or NOT RUN, timestamp, actual result,
and an evidence reference. Do not leave unexecuted rows looking like a pass.

| ID | Action | Expected result | Result / evidence |
|---|---|---|---|
| H1 | GET API `/health` | HTTP 200 | NOT RUN |
| H2 | GET MCP `/health` | HTTP 200 | NOT RUN |
| H3 | GET MCP `/mcp` without credentials | HTTP 401 challenge | NOT RUN |
| H4 | GET MCP `/.well-known/oauth-protected-resource/mcp` | Resource is the target `/mcp`; authorization server is the target API | NOT RUN |
| A1 | Sign up with a fresh dedicated test mailbox; inspect email privately | Confirmation; email within 2 minutes; link requires Continue before password change; password of at least 12 characters accepted | NOT RUN |
| A2 | Connect the MCP client and complete OAuth on the target API origin | Connected; account is the intended test role | NOT RUN |
| T1 | List tools | Exactly the candidate README's default tool set (October 29 fixture: 16); no Arena tools in the launch configuration. Any Arena tool listed: stop (see the stop rules) | NOT RUN |
| N1 | In the client's tool view, read each listed tool's description | Every description opens with exactly: `Not for clinical use. Orinyx checks medication claims against cited FDA label text for testing and evaluation only. Do not use its results to diagnose, treat, prescribe or make patient care decisions. Use synthetic test data only.` A tool without it, or with any other wording, is a FAIL | NOT RUN |
| T2 | Ask `start a test` | QUICK CHECK available; no open exam; lookups described as unavailable for the developer account | NOT RUN |
| T3 | Ask: `Check this order with verify_order_text, exactly as written: acetaminophen 1500 mg by mouth every 4 hours. Show the tool's output exactly as returned.` | Compare the tool's output exactly as returned, citation IDs included, never the agent's own summary of it, with the October 29 fixture ([QUICKSTART.md planted example](../QUICKSTART.md#expected-output)): `Checked 3 claims: 1 flagged, 2 supported, 0 abstained.`; dose FLAGGED MODERATE, 9,000 mg/day versus 4,000 mg/day, FDA OTC Monograph M013.50(d)(2); route and frequency SUPPORTED with the fixture's citations; a `Run id:` line; the footer reads exactly `Orinyx flags; the clinician decides.` Only the run ID and checking time may differ: any other difference from the fixture (a row, a verdict, a severity, a citation) is a FAIL, because the hosted knowledge base differs from the one the fixture was captured on | NOT RUN |
| V1 | Ask: `Check this order with verify_order_text, exactly as written: Acetaminophen 650 mg IV every 4 hours. Show the tool's output exactly as returned.` (a synthetic order) | Judge the frequency verdict and its reason from the tool's output exactly as returned, never from the agent's own summary of it: frequency row NOT VERIFIED (abstain), never SUPPORTED or FLAGGED; its reason names the label's route (oral) against the order's route (intravenous). Recorded at engine `d7ac5cf` (regression case REG-004). Depends on the hosted API carrying engine `d7ac5cf` or a later build that retains the change: with the engine revision unrecorded or earlier, record BLOCKED; on a build that carries d7ac5cf or later, a SUPPORTED or FLAGGED frequency is a FAIL | NOT RUN |
| T4 | Call `get_next_exam_case` with `run_id: 1` as developer | Readable 403/scope refusal; no case text | NOT RUN |
| T5 | Call `find_fda_label` for `warfarin` as developer | Readable refusal; no label text | NOT RUN |
| A3 | Repeat signup with the same test address; wait 2 minutes | Same public confirmation; no second welcome email; original password still works. Inspect backend `exists` response only through authorized private tooling: HTTP `200` with `"status": "exists"` and no `inviteUrl`; any other status, or an `inviteUrl`, is a FAIL | NOT RUN |
| D1 | If dashboard is deployed, sign in and open `/audits` | Developer reaches the staff-only gate; sign-out returns to login. Check candidate-specific allowed routes separately | NOT RUN |
| C1 | Record cleanup and evidence | Authorized owner excludes test account from launch metrics; audit record retained; no test identity published | NOT RUN |

H1–H4 need no credentials and may be run from a terminal. A1–C1 need an authorized
operator/client; do not treat a mocked unit test as a hosted pass. If the dashboard
is not deployed, D1 is NOT RUN and the overall result is explicitly scoped to MCP.
Changing deployment configuration or publishing is outside this script.

## Client matrix

Repeat A2/T1/T3 for each client actually supported by the candidate documentation.
Record client version, sign-in result, tool-call result, UTC timestamp and run ID.
Keep clients pending rollout clearly NOT RUN; do not infer cross-client compatibility.

## Review handoff

Post candidate/deployed revisions, statuses, sanitized evidence and run IDs to the
linked issue. Have a second reviewer acknowledge the record. This smoke pass does
not clear engine release requirements: REG-004, REG-008, REG-015 and REG-016 remain
subject to the owner's separate must-fix gate. A known-limit note is not a waiver.

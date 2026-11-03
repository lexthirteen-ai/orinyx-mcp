# Hosted smoke test, Thu 2026-10-29 morning

One pass of the hosted sign-up and connector path, run by the Orinyx team before any launch copy goes
out. About 15 minutes. Synthetic data only. If a step fails, stop: publish nothing and note
the step, the time and what you saw.

**You need:** a fresh email address that has never signed up (a plus-address on your own
mailbox works, e.g. `you+orx-smoke-1029@yourdomain`), Claude (web or desktop) and a terminal.

Write the address here before you start: `____________________`

## 0. Pre-flight (1 min)

```bash
curl -s -o /dev/null -w 'api health %{http_code}\n' https://orinyx-api.fly.dev/health
curl -s -o /dev/null -w 'mcp health %{http_code}\n' https://orinyx-mcp.fly.dev/health
curl -s -o /dev/null -w 'mcp no token %{http_code}\n' https://orinyx-mcp.fly.dev/mcp
curl -s https://orinyx-mcp.fly.dev/.well-known/oauth-protected-resource/mcp
```

- [ ] api health `200`, mcp health `200`
- [ ] mcp no token `401` (a sign-in challenge, not a 5xx)
- [ ] the protected-resource document names `https://orinyx-mcp.fly.dev/mcp` and the
      `https://orinyx-api.fly.dev` issuer

## 1. Sign up (2 min)

1. Open [orinyx.io/developers](https://orinyx.io/developers) and sign up with the fresh
   address.
2. Open the welcome email.
3. Follow its link. The page shows a **Continue** button only (it changes nothing until
   clicked). Click it.
4. Set a password of 12 characters or more.

- [ ] the form confirms the sign-up
- [ ] the welcome email arrives within 2 minutes
- [ ] the link shows Continue first, then the password form
- [ ] the password is accepted

## 2. Add the connector and sign in (3 min)

1. In Claude, add a custom connector: `https://orinyx-mcp.fly.dev/mcp`.
2. Connect it. Claude sends you to the Orinyx sign-in page on `orinyx-api.fly.dev`.
3. Sign in with the fresh address and the password from step 1, and allow access.

- [ ] the sign-in page is Orinyx's, on `orinyx-api.fly.dev`
- [ ] sign-in succeeds and Claude shows the connector as connected
- [ ] the connector's tool list has exactly 16 tools, the 16 in the README's
      [How to choose a tool](../README.md#how-to-choose-a-tool) table, and no tool name
      contains `arena`. Any other count is a fail. If it lists the five Arena tools
      (`start_arena_challenge`, `submit_arena_answer`, `start_arena_rematch`,
      `get_arena_battle`, `get_arena_report`), stop and do not launch: the hosted server is
      running with `ORINYX_ARENA_ENABLED=true`.

## 3. One synthetic order check (3 min)

1. Type: `start a test`
2. Type: `Check this order with verify_order_text, exactly as written: acetaminophen 1500 mg
   by mouth every 4 hours. Show the tool's output exactly as returned.`
3. Compare with the planted example in [QUICKSTART.md](QUICKSTART.md#expected-output).

- [ ] `start a test` offers the QUICK CHECK and lists no open exam
- [ ] `Checked 3 claims: 1 flagged, 2 supported, 0 abstained.`
- [ ] row 1 dose `FLAGGED`, `MODERATE`, 9,000 mg against the 4,000 mg in 24 hours maximum,
      citing `FDA OTC Monograph, M013.50(d)(2)`
- [ ] rows 2 and 3 (route, frequency) `SUPPORTED`, each with a citation
- [ ] the footer reads `Orinyx flags; the clinician decides.`
- [ ] a `Run id:` line is present. Write it here: `____________________`

The run id and checking time differ from QUICKSTART.md. Any other difference (a row, a
verdict, a severity, a citation) is a fail: the hosted knowledge base differs from the one
the quickstart was captured on.

## 4. A developer is refused an exam tool (1 min)

In the same chat, type: `Call get_next_exam_case with run_id 1.`

- [ ] the tool returns an error that names a refusal (a 403 or a missing scope)
- [ ] no exam case text comes back

Then type: `Call find_fda_label for warfarin.` This is refused too: the API keeps label and
monograph lookups to staff accounts.

- [ ] step 3's `start a test` said so under LOOK SOMETHING UP: `Not available to this
      account. Ask the Orinyx operator if you need FDA label or monograph text.`
- [ ] the lookup is refused, and no label text comes back

## 5. A duplicate sign-up returns `exists` (2 min)

1. Sign up again on [orinyx.io/developers](https://orinyx.io/developers) with the same
   address.
2. Wait 2 minutes.

- [ ] the form shows the same message as the first sign-up (it must not reveal that the
      account exists)
- [ ] no second welcome email arrives
- [ ] the account still signs in with the step 1 password (re-run step 2's sign-in, or
      reconnect the connector)
- [ ] if the orinyx.io form's server logs the engine's answer, it is `200` with
      `"status": "exists"` and no `inviteUrl`

Optional, if `SIGNUP_HOOK_SECRET` is in your local shell (it is never typed on the command
line or pasted anywhere):

```bash
curl -s -w '\nHTTP %{http_code}\n' -X POST https://orinyx-api.fly.dev/v1/signups \
  -H "X-Orinyx-Signup-Secret: $SIGNUP_HOOK_SECRET" -H 'Content-Type: application/json' \
  -d '{"email":"<the same address>","name":"Smoke Test"}'
```

- [ ] `HTTP 200` and `"status":"exists"`, with no link

## 6. Dashboard gate (1 min, only if the developer-role dashboard is deployed)

Sign in to the dashboard with the fresh address.

- [ ] it lands on "This dashboard is for staff accounts" with the connector URL
- [ ] opening `/audits` directly lands on the same page
- [ ] Sign out returns to the sign-in page

## 7. Afterwards (2 min)

- [ ] ask the operator to exclude the address from launch metrics, so it is not counted as a
      launch sign-up
- [ ] keep the account (its audit record cannot be deleted). To retire it later, the operator
      deactivates it on the API side. A deactivated address cannot sign up again.
- [ ] record the time, the run id and "pass" in the launch log; then publish the copy

## Client matrix

One row per MCP client: sign in, then make one tool call (step 3's order check will do).
Fill in a row when that client has been tried.

| client | version | sign-in OK | one tool call OK | date | notes |
|---|---|---|---|---|---|
| Claude Code | | | | | |
| Claude connector | | | | | |

## Not covered here

- `python evals/mcp_local_check.py --url https://orinyx-mcp.fly.dev/mcp` needs an API key as
  the bearer. A developer account cannot mint one (minting is admin-only, inside the same
  organization), so it would run as a staff key, and every run writes audit events that
  cannot be deleted. It belongs to the Monday rehearsal, run once.
- The quota header (`X-RateLimit-*`) is not visible through Claude. One check uses 1 of 200
  for the month.
- The clean warfarin example: run it too if there is time; it should match QUICKSTART.md
  with 3 supported rows.

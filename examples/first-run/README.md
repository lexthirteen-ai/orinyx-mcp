# First-run reference example

Four synthetic orders and one set of structured claims, with the output each one produced on
the hosted Orinyx API. None of them is about a real patient, and none is a dosing example: each
order is there to show one kind of result.

| File | Input | What comes back | Exit |
|---|---|---|---|
| `clean.txt` | `warfarin 5 mg by mouth daily` | 4 claims (dose, route, frequency, identity), all supported, each with a citation. No flag. | 0 |
| `planted.txt` | `acetaminophen 1500 mg by mouth every 4 hours` | The dose is flagged (Moderate). Route, frequency and identity are supported. | 2 |
| `abstain.txt` | `pravastatin 40 mg by mouth daily` | Route and identity are supported. Dose and frequency **abstain**: no rule covers them. | 3 |
| `known-limit.txt` | `metoprolol succinate ER 50 mg by mouth daily` | Shows a **published known limit**: frequency is supported from a different formulation's label. | 3 |
| `claims.json` | Structured dose and route claims for the clean order | 2 claims, both supported. | 0 |

Exit codes: 0 clean, 2 flagged or unreadable, 3 not verified (at least one claim was not
checked). The full expected output of each input, for the MCP tool and the CLI, is in
[expected/](expected/).

## Run it

**From an agent** connected to Orinyx, ask for each order to be checked with
`verify_order_text`, exactly as written. To compare line by line, ask the agent to show the
tool's output as returned.

**From the shell**, sign in once with `orinyx login`, or set `ORINYX_API_KEY`. Installation is in
[docs/QUICKSTART.md](../../docs/QUICKSTART.md#install).

```bash
orinyx observe examples/first-run/clean.txt         # exit 0
orinyx observe examples/first-run/planted.txt       # exit 2
orinyx observe examples/first-run/abstain.txt       # exit 3
orinyx observe examples/first-run/known-limit.txt   # exit 3
orinyx get <run id>                                 # one run in full
orinyx verify --file examples/first-run/claims.json # exit 0
```

## Expected results

Captured on 2026-11-15 (21:35 UTC) from the hosted Orinyx API 0.4.0 (knowledge graph
`kg-2026.11.6`), with orinyx-mcp 0.1.5 from PyPI. The hosted connector at
`https://orinyx-mcp.fly.dev/mcp` runs the same release (commit `f0a4386`).

| Input | Part | Verdict | Severity | Cited label set id or source | Effective |
|---|---|---|---|---|---|
| clean | dose | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 20260831 |
| clean | route | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 20260831 |
| clean | frequency | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 20260831 |
| clean | identity | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 2026-08-31 |
| planted | dose | contradicted | moderate | FDA OTC Monograph M013.50(d)(2) | document version 1 |
| planted | route | supported | none | `7f445de3-30cf-4bd8-892d-05979cd399e7` | 20260909 |
| planted | frequency | supported | none | `7f445de3-30cf-4bd8-892d-05979cd399e7` | 20260909 |
| planted | identity | supported | none | `7f445de3-30cf-4bd8-892d-05979cd399e7` | 2026-09-09 |
| abstain | route | supported | none | `222b90fd-f070-4fa8-8f8b-720133cb2b0a` | 20261106 |
| abstain | identity | supported | none | `222b90fd-f070-4fa8-8f8b-720133cb2b0a` | 2026-11-06 |
| abstain | dose | abstain | none | - | - |
| abstain | frequency | abstain | none | - | - |
| known-limit | route | supported | none | `59ed27b8-32b5-60c0-e063-6394a90a8a23` | 20260826 |
| known-limit | frequency | supported | none | `59ed27b8-32b5-60c0-e063-6394a90a8a23` | 20260826 |
| known-limit | dose | abstain | none | - | - |
| known-limit | identity | abstain | none | - | - |
| claims.json | dose | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 20260831 |
| claims.json | route | supported | none | `5a5b5e3a-6556-a542-e063-6294a90a6d3f` | 20260831 |

Each set id opens its label on DailyMed:
`https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=<set id>`. The identity row prints
the same effective date in a different format.

### The planted error

At 1,500 mg every 4 hours, the daily total is 9,000 mg. FDA OTC Monograph M013.50(d)(2) states
a maximum of 4,000 mg in 24 hours, so the dose is flagged. The error is planted so you can see a
flag.

The supported frequency row cites a children's product label. This is a published known limit
(REG-012 in the
[0.1.1 release notes](../../docs/RELEASE_NOTES_2026-11-02.md#known-limits)): that label does not
establish that the frequency applies to an adult order.

### The abstain

Abstain means the claim was **not checked**. It never means the claim is correct. Here the
reasons are:

- dose: "No dose_range rule covers this drug; abstaining."
- frequency: "No frequency rule covers this drug; abstaining."

The run is marked NOT VERIFIED and exits 3.

### The known limit

This order names a formulation, metoprolol succinate extended-release. Orinyx holds one label
per drug, and the label it holds for metoprolol is the tartrate label. So:

- dose and identity abstain, and say why (the formulation cannot be matched);
- **frequency is supported from the tartrate label**, which does not establish that the schedule
  applies to the extended-release formulation.

This is published known limit REG-010 in the
[0.1.1 release notes](../../docs/RELEASE_NOTES_2026-11-02.md#known-limits). A supported row is
only as good as the label it cites, so check the label name in each citation.

## When your results differ

Results can change when a label is updated. Compare the citation on each row: if the set id or
the effective date differs from the table above, the API is reading a newer label, and the
verdict it returns is the one to read. These always differ from run to run:

- the run id and the times;
- the header, which names your tool if the agent passes a tool name.

These examples show what each kind of result looks like. They are not evidence of accuracy.

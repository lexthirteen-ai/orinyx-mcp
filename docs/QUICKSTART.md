# Quickstart

Connect an agent to Orinyx, run a first check, add it to CI, and sit an exam. Synthetic data
only throughout: never real patient records, names, dates or record numbers.

For the hosted connector, the self-serve path, you need an Orinyx account and no key;
[First run](#first-run) starts with signing up. Local CLI and stdio also support
[`orinyx login`](../README.md#cli-login): browser sign-in,
secure OS storage, verification and Arena access according to account permissions, no exams.
CI and explicit key-based use need an Orinyx API URL and a key (`ork_live_...`) issued through the
[self-serve API](../README.md#get-an-api-key) or an operator. PyPI and `uvx` installation
instructions are in the [README](../README.md#install-from-pypi).

## First run

Nothing to install: this uses the hosted connector.

1. **Sign up** at [orinyx.io/developers](https://orinyx.io/developers).
2. **Open the welcome email** and follow its link to set your password. The link can be used
   once. If the email has not arrived after 10 minutes, contact [hello@orinyx.io](mailto:hello@orinyx.io).
3. **Add the connector** `https://orinyx-mcp.fly.dev/mcp` in your client (steps for each client
   are under [Connect your client](#connect-your-client)). The client sends you to the
   Orinyx sign-in page. Sign in with your email and the password you set.
4. **Type "start a test".** The agent calls `start_a_test`, which lists what your account can
   run. The examples below use the quick check (`verify_order_text`).
5. **Run the clean example.** Ask: "Check this order with verify_order_text, exactly as
   written: warfarin 5 mg by mouth daily."
6. **Run the planted example.** Ask: "Check this order with verify_order_text, exactly as
   written: acetaminophen 1500 mg by mouth every 4 hours."
7. **Compare** each result with the expected output below.

The two orders are also in [examples/first-run/](../examples/first-run/) (`clean.txt`,
`planted.txt`), with the same check run from the shell, an abstain example and a known-limit
example.

### Expected output

The expected output of both orders is in the
[first-run reference example](../examples/first-run/README.md#expected-results), with each
row's verdict, severity, cited label set id and effective date, and the API and package
versions it was captured on. The full text the tool returns is in
[examples/first-run/expected/](../examples/first-run/expected/). Your run should match on these
points: the same rows, the same verdict and severity on each, and the same citations. These parts
will be different:

- the run id;
- the "Orinyx checking time" line;
- the header, which names your tool if the agent passes a tool name.

Your agent may summarise the result in its own words. To compare line by line, ask it to show
the tool's output exactly as returned.

If you get a different verdict for either order, compare the citation's set id and effective
date with the reference example. A different label means different results, and the verdict
the API returned is the one to read.

### Limits

- **Synthetic data only.** Never send real patient records, names, dates or record numbers.
- **Supported is not a clearance.** A supported row means one claim agrees with the cited label
  text. It is not a judgment that the order suits a patient, and it does not clear the daily
  total, the schedule or the patient context unless a row says so.
- **Not verified means unchecked.** An abstained row was not checked. It does not mean the claim
  is correct.
- **Orinyx flags; the clinician decides.** No language model decides a verdict or a severity.

### What is sent, and where

- Your agent host (for example Claude) sends each order, as the agent passes it, to the Orinyx
  MCP service at `orinyx-mcp.fly.dev`. If the agent passes a tool name and version, those go
  too. The host keeps its own copy of the conversation under its own terms.
- The MCP service relays the request to the Orinyx API with your own sign-in. The service has
  no database of its own.
- The API refuses an order that looks like it holds an identifier (a phone number, SSN, date,
  long number or record number). Otherwise it checks the order and stores the order text and
  the result in its audit record, under your account. Audit records cannot be deleted.

## Install

Install it from a checkout (Python 3.11+):

```bash
git clone https://github.com/lexthirteen-ai/orinyx-mcp.git && cd orinyx-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e .
```

This gives you `orinyx-mcp stdio` (the stdio MCP server; `python -m orinyx_mcp` starts the
same server), the `orinyx` CLI and the `orinyx-mcp` network server (no argument).
`orinyx-mcp --version` prints the installed version, and any other argument exits 1 with a
usage line. Agent hosts launch the stdio server themselves, so point them at the virtualenv's
`orinyx-mcp` by absolute path (`/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp` below); a
bare `orinyx-mcp` may not be the one you installed into. The stdio server and the CLI need
an `ork_live_` key issued to you by Orinyx.

## Connect your client

### Claude Code

Hosted (Streamable HTTP), the self-serve path, signing in with your Orinyx account:

```bash
claude mcp add --transport http orinyx https://orinyx-mcp.fly.dev/mcp
```

then run `/mcp` inside Claude Code and authenticate; you are sent to the Orinyx sign-in page.
To use a key issued to you by Orinyx instead of signing in, add
`--header "Authorization: Bearer $ORINYX_API_KEY"`.

Local (stdio), with a key issued to you by Orinyx. Export the two variables first so the key
is not typed on the command line:

```bash
export ORINYX_API_URL=https://<your orinyx api>
export ORINYX_API_KEY=<your ork_live_ key>
claude mcp add orinyx \
  -e ORINYX_API_URL="$ORINYX_API_URL" \
  -e ORINYX_API_KEY="$ORINYX_API_KEY" \
  -- /absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp stdio
```

`claude mcp add` writes to the local scope by default; `-s project` writes `.mcp.json` into
the repository, so do not use it with a key in `-e`. **Never commit a client config file that
holds a key**, such as `claude_desktop_config.json`, `.cursor/mcp.json` or a project
`.mcp.json`.

### Claude Desktop

For the hosted connector, the self-serve path, add `https://orinyx-mcp.fly.dev/mcp` as a
custom connector and sign in with your Orinyx account.

For the local (stdio) server, with a key issued to you by Orinyx, edit
`claude_desktop_config.json` (Settings > Developer > Edit Config) and restart:

```json
{
  "mcpServers": {
    "orinyx": {
      "command": "/absolute/path/to/orinyx-mcp/.venv/bin/orinyx-mcp",
      "args": ["stdio"],
      "env": {
        "ORINYX_API_URL": "https://<your orinyx api>",
        "ORINYX_API_KEY": "<your ork_live_ key>"
      }
    }
  }
}
```

**Never commit a client config file that holds a key**, such as `claude_desktop_config.json`,
`.cursor/mcp.json` or a project `.mcp.json`.

### Cursor editor

1. Sign in to Cursor and open your project. Add the
   [hosted Orinyx connector to Cursor's `mcp.json`](../README.md#cursor).
2. Open **Cursor Settings**, then **Customize → MCPs**. If `orinyx` is disabled,
   select it and enable it for your project.
3. Choose **Authenticate** next to `orinyx`. In your browser, sign in to Orinyx and
   choose **Sign in and approve**. Return to Cursor and confirm that `orinyx` is
   listed under **Connected** with its tools. The hosted connection needs no Orinyx API key.
4. In Cursor Agent, ask it to call `start_a_test`. Then run the planted synthetic order
   from [First run](#first-run) with `verify_order_text`. Ask the agent to put the order
   in the `orders` array and compare the result with the [expected output](#expected-output).

### Cursor CLI

Add the [hosted Orinyx connector to Cursor's `mcp.json`](../README.md#cursor). From your
project directory, run `agent mcp list`. If `orinyx` is disabled, run
`agent mcp enable orinyx`. Then run:

```bash
agent mcp login orinyx
agent mcp list
```

Sign in to Orinyx when your browser opens. The list should show `orinyx: ready`. The
hosted connection needs no Orinyx API key.

Sign in to Cursor with `agent login` if needed. Ask Cursor Agent to call `start_a_test`
and approve the tool call when prompted. Then run the planted synthetic order from
[First run](#first-run) with `verify_order_text` and compare it with the
[expected output](#expected-output).

### Check the connection

```bash
python evals/mcp_local_check.py                         # launches python -m orinyx_mcp over stdio
python evals/mcp_local_check.py --url https://orinyx-mcp.fly.dev/mcp  # a hosted endpoint, key as bearer
```

Both forms need an `ork_live_` key issued to you by Orinyx in the environment.

It lists the tools, verifies three synthetic warfarin claims, reads the run back, exports it
and confirms an unknown run id is a readable 404; exit 0 when every step answered as
expected. Each run writes verification events that cannot be deleted, so point it at a
sandbox.

## Check from the shell

The `orinyx` CLI needs an Orinyx API URL and an `ork_live_` key issued to you by Orinyx. The
two first-run orders are bundled as files. `orinyx observe` sends each file as one run:

```bash
orinyx observe examples/first-run/    # clean.txt exits 0 on its own, planted.txt 2; together 2
```

[examples/first-run/README.md](../examples/first-run/README.md) has the commands and their
captured output.

`orinyx verify` takes claims your agent has already split into structured form:

```bash
cat > claims.json <<'EOF'
[
  {
    "rawText": "warfarin 5 mg by mouth daily",
    "drug": "warfarin",
    "claimType": "dose_range",
    "structuredValue": {"dose": 5, "unit": "mg"}
  },
  {
    "rawText": "warfarin 5 mg by mouth daily",
    "drug": "warfarin",
    "claimType": "route",
    "structuredValue": {"route": "oral"}
  }
]
EOF
orinyx verify --file claims.json --tool my-agent --tool-version 0.3.0
echo "exit $?"
```

Output captured on 2026-10-22 from Orinyx engine 0.3.1 running on a local machine. Your run id
will be different:

```text
Orinyx verification - run d048062e (my-agent 0.3.0)
Checked 2 claims: 0 flagged, 2 supported, 0 abstained.

FLAGS (0): no claim was found to contradict its label. This is not a safety clearance; abstained claims below were not checked.

SUPPORTED (2) - consistent with the cited label text; not a judgment that the order suits a patient:
1. warfarin 5 mg by mouth daily (dose)
   Citation: openFDA, Dosage and Administration (§2) - id 5a5b5e3a-6556-a542-e063-6294a90a6d3f - Warfarin Sodium prescribing information, SPL set ID 5a5b5e3a-6556-a542-e063-6294a90a6d3f, effective 20260831 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=5a5b5e3a-6556-a542-e063-6294a90a6d3f
2. warfarin 5 mg by mouth daily (route)
   Citation: openFDA, openFDA product metadata - id 5a5b5e3a-6556-a542-e063-6294a90a6d3f - Warfarin Sodium prescribing information, SPL set ID 5a5b5e3a-6556-a542-e063-6294a90a6d3f, effective 20260831 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=5a5b5e3a-6556-a542-e063-6294a90a6d3f

ABSTAINED (0)

Orinyx flags; the clinician decides.
exit 0
```

`--json` prints the API's JSON instead. The text form shows the run id abbreviated; take the
full `runId` from `--json` for the follow-ups:

```bash
orinyx get <run id>                                   # the run again, with any physician review
orinyx accuracy <run id>                              # the physician-review tally
orinyx export <run id> --format report --out report.pdf   # csv | pdf | report; --out is required
```

## CI recipe

`orinyx verify` exits 0 clean, 2 flagged (a `contradicted` claim or an `unreadable` order),
3 not verified (no flag, but an abstain), 1 error. Usage errors exit 1, never 2.

CI needs an `ork_live_` key issued by Orinyx through the [self-serve API](../README.md#get-an-api-key)
or an operator: hosted connector OAuth is not a CLI credential. Have your test job write the agent's claims for a
fixed set of synthetic inputs to a JSON file, then:

```yaml
name: orinyx
on: [pull_request]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install orinyx-mcp (from its repository)
        run: pip install "git+https://github.com/lexthirteen-ai/orinyx-mcp.git@<commit>"
      - name: Produce the agent's claims (your own step)
        run: python scripts/run_agent_on_fixtures.py --out out/claims.json
      - name: Check them with Orinyx
        env:
          ORINYX_API_URL: ${{ secrets.ORINYX_API_URL }}
          ORINYX_API_KEY: ${{ secrets.ORINYX_API_KEY }}
        run: |
          set +e
          orinyx verify --file out/claims.json --tool my-agent --tool-version "${{ github.sha }}" --json > out/orinyx.json
          code=$?
          case "$code" in
            0) echo "clean" ;;
            2) echo "::error::Orinyx flagged a claim or an unreadable order"; exit 2 ;;
            3) echo "::error::some claims were not verified (abstain is unchecked, not safe)"; exit 3 ;;
            *) echo "::error::orinyx failed (exit $code)"; cat out/orinyx.json; exit 1 ;;
          esac
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: orinyx-run
          path: out/orinyx.json
```

Pin a commit in the install line. Use a separate key for CI, issued by Orinyx, so its
rate-limit bucket and access-log identity are its own. Keep the key in a repository secret,
as above. **Never commit a client config file that holds a key**, such as
`claude_desktop_config.json`, `.cursor/mcp.json` or a project `.mcp.json`. If your team
decides an abstain should not block a merge, change the `3)` branch to a warning; it still
means the claim was not checked.

What the CLI does not cover yet: exams and monograph lookups. Free-text orders are covered
by `orinyx observe`, below.

## Observe a test run

`orinyx verify` checks the claims your agent hands it. `orinyx observe` reads what the agent
already wrote, its saved transcript or trace export, and checks every order in it, so the
agent does not choose what gets checked. Like every `orinyx` command, it needs an
`ork_live_` key issued to you by Orinyx. Run it on the output of a fixed set of synthetic
inputs:

```bash
orinyx observe examples/observe-sample.jsonl         # a synthetic sample: one flag, one skipped turn
orinyx observe out/                                  # every .txt, .jsonl and .json file in out/
orinyx observe out/trace.jsonl --field output.orders --tool my-agent --tool-version 0.3.0
```

- `.txt`: the file is one record, one order per line.
- `.jsonl` / `.json`: one record per line (or per list item). `--field` (default `orders`) is
  the dotted path to the record's orders, as a list of strings or one string with one order
  per line. A record without it is listed as skipped, never dropped silently.
- Each record is one run, so `--check-interactions` sees that record's orders together. A
  record over the API's limits (50 orders, 500 characters per order) is refused, not split.
- Before anything is sent, every order goes through the same identifier screen the engine
  uses (phone, SSN, date, long number, MRN). One hit refuses the whole invocation, names the
  record and the pattern, and sends nothing. Synthetic test data only.

It prints one line per run and a total; `orinyx get <run id>` reads a run in full. `--json`
prints `{"runs": [{"source", "runId", "raw"}], "skipped": [...]}`. The exit code is the worst
run's, with the same codes as `verify`, and finding no orders at all exits 1, so an empty
test run never passes. In the CI recipe above, swap the check step's command for:

```bash
orinyx observe out/ --tool my-agent --tool-version "${{ github.sha }}" --json > out/orinyx.json
```

## Sit an exam

Exams are for a **product account**. Orinyx registers your product and opens the exam; you
do not open it yourself.

1. **Orinyx registers the product and opens a run.** An operator (quality lead or admin key)
   runs:

   ```bash
   python evals/product_exam.py setup --name "Acme" --product "Scribe 2.1 (prompt v3)" \
       --contact-email qa@acme.example
   python evals/product_exam.py open --vendor-id 3 --case-set ambient-core --version 1.0.0
   ```

   `setup` prints the vendor id (or reports the vendor already exists). `--product` carries
   the product's name, version and prompt: a different prompt is a different product. `open`
   prints the run number to give the product's tester.

2. **Connect the product's agent with the product sign-in** (any client above), and ask it to
   call `start_a_test`. It lists the open run and the steps.

3. **Sit it one case at a time:** `get_next_exam_case(run_id)` → answer →
   `submit_exam_answers(run_id, answers)` → repeat → `finish_exam(run_id)` →
   `get_exam_report(run_id)`. Answers are `{caseId, claims}` for a transcript case or
   `{caseId, replyText}` for a patient-message case. An answer cannot be changed once
   recorded. `get_exam_cases` returns the whole paper at once, but speed is then reported as
   not measured.

4. **A product that cannot connect an agent:** the operator runs the product on each case by
   hand and records the answers from a file:

   ```bash
   python evals/product_exam.py answer --run 12 --answers answers.json --finish
   python evals/product_exam.py report --run 12
   ```

   `answers.json` is a JSON list of `{"caseId": ..., "claims": [...]}`,
   `{"caseId": ..., "replyText": "..."}` or `{"caseId": ..., "codes": [...]}` by the case's
   kind, with an entry for every case (an empty claims or codes list is a valid answer); if
   any case is missing, nothing is recorded. `--finish` closes the
   sitting and prints the report. Answers recorded this way are not timed, and the report
   says speed was not measured.

`product_exam.py` subcommands and flags, all required unless marked:

| Subcommand | Flags |
|---|---|
| `setup` | `--name`, `--product`, `--contact-email` |
| `open` | `--vendor-id` (number), `--case-set`, `--version` |
| `answer` | `--run` (number), `--answers` (path), `--finish` (optional) |
| `report` | `--run` (number) |

It reads `ORINYX_API_URL` and `ORINYX_API_KEY` from the environment, exits 1 with
`refused: ...` on an API refusal or a bad file, and never reads a case-set file: the answer
key stays on the server.

A report on an unsigned test set is marked REHEARSAL and is not evidence. A pass is not a
clinical safety clearance of the product.

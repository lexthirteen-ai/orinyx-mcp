# Clinical test script: UTI-001

Tests whether **Orinyx** detects what it should on one synthetic case family (adult outpatient acute
cystitis, US guidance). It scores Orinyx (Layer B). The agent's behaviour (Layer A) is the brief's
`expected_assessment` in the fixture file, unedited and never re-graded by a model. This is **not** a
clinical validation, a safety certification or evidence of release readiness.

| File | What it is |
|---|---|
| [CAPABILITY_MAP.md](CAPABILITY_MAP.md) | What Orinyx accepts and returns, the label mapping, and SUPPORTED / PARTIAL / UNSUPPORTED for every check |
| `../../../tests/fixtures/clinical/uti-001.json` | The 13 fixtures, the evidence registry and the capability registry |
| `../../../evals/clinical_suite.py` | The runner (`lint`, `run`) |
| `../../../tests/test_clinical_suite.py` | Offline tests (fakes, no engine) |
| [baseline/results.json](baseline/results.json), [baseline/results.md](baseline/results.md) | One baseline run, 3 runs per fixture |

## Run it

```bash
export ORINYX_API_URL=https://api.example.com
export ORINYX_API_KEY="$TESTER_API_KEY"
python evals/clinical_suite.py lint
python evals/clinical_suite.py run --runs 3 --out clinical-suite-results
```

`--only UTI-001-B,UTI-001-D` runs a subset. `--max-per-minute` (default 50) paces requests under the
engine's 60-per-minute limit; a 429 is retried and counted. Every outbound string passes the repo's
identifier screen first. Each request is an ordinary API call and is recorded in the engine's audit
trail with tool name `orinyx-clinical-suite`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | every automated fixture is a stable TRUE_POSITIVE or TRUE_NEGATIVE |
| 1 | an execution error, or a usage error |
| 2 | at least one CRITICAL false negative, whatever the pass rate |
| 3 | not clean: a false negative or positive, or an inconclusive or unstable automated fixture (including a CRITICAL check Orinyx could not establish) |

`UTI-001-E` is `clinician_review` and never affects the exit code.

```yaml
- name: Clinical test script (UTI-001)
  env:
    ORINYX_API_URL: ${{ secrets.ORINYX_API_URL }}
    ORINYX_API_KEY: ${{ secrets.ORINYX_API_KEY }}
  run: python evals/clinical_suite.py run --runs 3 --out clinical-suite-results
```

Today this step would fail on every run (exit 3): the baseline shows why.

## How a fixture reaches Orinyx

Orinyx takes orders or structured claims, not patient context or a second turn. Each fixture lists
`probes`; a probe states whether its text is `verbatim_from_candidate_output` (checked by `lint`) or
`harness_translated_from_patient_context` (a claim the harness authored: Orinyx did not read the
context). Only `scored` probes change a bucket; the rest are observations and wording-sensitivity
checks. Results that depend on a harness-translated claim are tagged `approximation`.

## Buckets

`TRUE_POSITIVE`, `TRUE_NEGATIVE`, `FALSE_NEGATIVE` (missed unsafe), `FALSE_POSITIVE` (flagged safe),
`INCONCLUSIVE` (unsupported check, clinician review, or unmappable output), `EXECUTION_ERROR`. They are
never merged. An UNSUPPORTED check is INCONCLUSIVE, never a pass; a TRUE_NEGATIVE means "no flag", not
"cleared".

## Baseline provenance

The baseline ran on 2026-10-23 against a development build of the Orinyx API 0.3.1. The run IDs
in `results.json` refer to that environment. The runner used public orinyx-mcp commit `4a15a16`
with local suite changes. The public copy uses neutral evidence descriptions and retains the
original run results.

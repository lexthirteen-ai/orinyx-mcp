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
export ORINYX_API_URL=https://<your orinyx api>     # a local engine on localhost also works
export ORINYX_API_KEY=<a tester key>
python evals/clinical_suite.py lint
python evals/clinical_suite.py run --runs 3 --out clinical-suite-results \
    --engine-commit <engine git sha>                 # REST does not report the engine commit
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
  run: python evals/clinical_suite.py run --runs 3 --out clinical-suite-results --engine-commit "$ENGINE_SHA"
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

Run against a local engine 0.3.1 at commit `b1687ccbbbe596902f89e40463fc74485d9527e3`, which is the head of
the then-unmerged `build/2026-10-22-password-reset` branch, not `main` (`bc86d37`). That branch adds no migration
and no knowledge-base or verifier change, so the verdicts should match `main`; re-run on `main` to confirm. It ran on a disposable
copy of the development database (`orinyx_uti001_baseline`; the original was only read). Orinyx run ids
in `results.json` point into that copy's audit trail. Runner commit `4a15a16` with uncommitted changes
(the working tree was dirty: these files were new).

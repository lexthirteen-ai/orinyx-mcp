# How Orinyx evaluates

This page explains how the Orinyx API reaches a verdict, how this repository tests that it
reports verdicts faithfully, and what the results can and cannot tell you. It describes the
method. It publishes no accuracy figures, because no reviewed case set exists yet to measure
them against.

> **Not for clinical use.** Orinyx checks medication claims against cited FDA label text. A
> "supported" result means one claim matches the cited label text, not that an order is safe
> or appropriate. Submit synthetic test data only. Orinyx flags; the clinician decides.

## 1. How a verdict is reached

- **Rules from label text, applied the same way every time.** The Orinyx API checks each claim
  against rules taken from FDA label text. The same claim against the same label version gives
  the same verdict. No language model decides a verdict, a severity or a score
  ([README, "No model in the verdict"](../README.md#safety-and-limits)).
- **Four verdicts:**
  - `supported`: the claim matches the cited label text;
  - `contradicted`: the claim breaks a cited rule;
  - `abstain`: no applicable label evidence, so the claim was **not checked**. Abstain never
    means safe;
  - `unreadable`: the order could not be read as written.
- **Every supported or contradicted row carries its citation:** source, label section, label
  set id and effective date.
- **Label silence is not a contradiction.** A supported claim says nothing about whether the
  whole order suits a patient.
- **This package holds no rules.** It sends your claims to the API and shows what comes back.
  The one check it runs itself is a pre-flight screen that refuses identifier-shaped text
  before anything is sent.

## 2. What is checked today, and what is not

| Check | Today |
|---|---|
| Which medication an order names, with a label citation | Checked |
| Route | Checked |
| Frequency | Checked where the label states a schedule; otherwise abstain |
| Maximum single dose | Checked where the label states one; otherwise abstain |
| As-needed (PRN) daily maximum | Not checked yet: an as-needed order is not flagged |
| Missing order parts (no route, no frequency) | Reported as a note, not as a verdict |
| Pediatric versus adult dosing | Not checked: population-specific maximums are set aside |
| Allergies and interactions for a patient | **Not available.** A synthetic order carries no patient context. |

The medications covered by each release are listed in its
[release notes](https://github.com/lexthirteen-ai/orinyx-mcp/releases). The known gaps are
listed in the [0.1.1 release notes](RELEASE_NOTES_2026-11-02.md#known-limits).

## 3. Test fixtures in this repository

These fixtures test that this client reports the API's verdicts faithfully. They do not test
whether a verdict is clinically right.

- **`tests/fixtures/check_lines_goldens.json`:** approved samples of the text report, copied
  verbatim. A change in that wording fails a test.
- **`tests/fixtures/engine_contract.json`:** values this client copies from the API: the
  identifier-screen patterns, label section names, unreadable markers and check names. Drift
  tests fail if a copy no longer matches.
- **A synthetic clinical suite** (`tests/fixtures/clinical/`), run by `evals/clinical_suite.py`.
  It checks which planted problems the API catches and which it misses.
- **Exam answer keys stay on the server.** They are never in this repository, so a builder can't
  study the key ([EXAMS](EXAMS.md)).

## 4. Regression testing

- **Known failures are kept, not hidden.** Every known wrong result is a named regression case.
  While it fails, it is marked as an expected failure; when it is fixed, the test flips and
  someone has to look. This list is published in the
  [0.1.1 release notes](RELEASE_NOTES_2026-11-02.md#known-limits).
- **A release gate:** a fixed list of cases must pass before a release.
- **False support is tracked against a ceiling of zero.** False support means a `supported`
  verdict on a claim that breaks the label. Any new false support stops the release.
- **This repository's CI** runs lint, the full test suite and a clean install on Python 3.11,
  3.12 and 3.13 ([ci.yml](../.github/workflows/ci.yml)).
- **What regression results are not:** passing them shows nothing has slipped. It is not
  evidence of accuracy.

## 5. Catches, false flags and misses

These definitions apply to case sets where each case has a known answer.

| Term | Meaning |
|---|---|
| Catch | The planted error is contradicted at a high enough severity |
| False flag | A known-clean claim is contradicted |
| False support | A known error is marked `supported` |
| Missed | A known error gets `abstain` |

- **Abstain is neither a catch nor a false flag.** It is always reported on its own.
- **Rates come with their counts:** every rate is shown with its numerator and denominator.
- **A missing rate is unmeasured, not zero.**
- **Rates are measured only on reviewed case sets.** None has been published yet, so this
  repository states no catch rate or false-flag rate.

## 6. Who reviews

- **Synthetic data only**, everywhere.
- **Medications** in a release are mapped to their FDA label and approved for testing by
  Orinyx. Each release list says the medications are "set for additional physician review".
- **Exam answer keys are written and signed by reviewers, not by the people who build the
  checks.** A report on an unsigned test set is marked REHEARSAL, not evidence
  ([EXAMS](EXAMS.md)). Signing a set later does not turn an earlier sitting into evidence.
- **A model never writes an answer key.** A model's output is what's being tested, never the
  answer it's tested against.

## 7. Proposed, not built: Arena judge independence

The Arena is off by default ([Arena tools](arena-integration.md)). **Nothing in this section is
built.** It is the design Orinyx intends to follow before any Arena result counts as evidence.

- **Answer keys stay server-side**, out of the agent's reach.
- **Signed sets only.** A battle on an unsigned set is rehearsal.
- **Author is not signer.** The person who writes a case can't sign it.
- **The judge stays deterministic.** A model may explain a result, but it never decides a
  verdict, a severity or a pass.
- **Disagreement goes to a person.** When two independent checks disagree, the case goes to
  human review instead of being settled by either check.
- **Every result names its versions:** the evaluator, the case set and the label data it ran
  against.
- **Test generation is kept apart from judging.** Cases generated to attack an agent are
  reviewed by a person before they enter any set, and a generator never marks its own cases
  correct.

## 8. Limits of this method

- **It doesn't measure:** clinical accuracy in live use, patient outcomes, fairness across
  populations, or general model quality.
- **Coverage is narrow:** the medications, rules and claim shapes in each release.
- **Results depend on label versions.** A label change can change a verdict, which is why every
  citation names its label set id and effective date.
- **Abstain is common.** Many labels state no schedule or maximum Orinyx can read, so a claim
  about them returns abstain.
- **Rehearsal results and regression runs are not evidence.**

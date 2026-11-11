# Capability map: what Orinyx can check in the UTI-001 fixtures

Suite: UTI-001 (adult outpatient acute cystitis, US guidance). Every status below was fixed from the code, the docs and the
exploratory calls in section 9 **before the first scored run**. Correction to the working order: the runner
(`evals/clinical_suite.py`) was drafted before this file was finalized, so the map was not literally written
before all test logic; no scored run existed when it was written.
Nothing here edits Orinyx. The fixtures' `expected_assessment` values are the brief's, unedited.

**Reading rule.** SUPPORTED = maps to an existing output field. PARTIAL = can be approximated, and the
approximation is stated; a result obtained through it is tagged `approximation`. UNSUPPORTED = no
corresponding capability exists; the fixture is reported INCONCLUSIVE and listed as a missing
capability, never as a pass.

## 1. What was inspected

`orinyx-mcp`: README, CLAUDE.md, docs/QUICKSTART.md, `orinyx_mcp/{client,tools,text,screen,cli}.py`,
`evals/product_exam.py`, `tests/` (pytest, fakes, no database), `tests/fixtures/engine_contract.json`.
`orinyx-engine` (read only): CLAUDE.md, `app/schemas.py`, `app/verifications/engine/{verify,severity}.py`,
`app/verifications/context_disclosure.py`, `data/red_flag_rules.json`, `app/orders/`, the knowledge base
in the local development database (read only), and the cached FDA label text for the drugs in the
fixtures. Engine 0.3.1, commit `b1687ccbbbe596902f89e40463fc74485d9527e3`; orinyx-mcp commit
`4a15a162e776bcf64d4f39ee6aa236e38bbb721b`.

There is **no `record.py` and no evaluation record yet** (orinyx-mcp CLAUDE.md: nothing built, planned
for the release after 2026-10-29), and no `docs/` page for an API route list beyond the Postman
collection. The "API route or schema definitions" are `orinyx_mcp/client.py` (the wire models) and the
engine's `app/schemas.py`.

## 2. What Orinyx accepts

| Input | Endpoint (client method) | Shape and limits |
|---|---|---|
| Free-text medication orders | `POST /v1/verifications/orders` (`verify_orders`, MCP `verify_order_text`) | `orders`: 1-50 strings of 1-500 characters, **one drug per order**; optional `checkInteractions`, `toolName`, `toolVersion`. Orinyx splits each order into dose, route and frequency claims by a deterministic grammar. Text with no dose, route or frequency is refused (422). |
| Structured claims | `POST /v1/verifications` (`verify`, MCP `verify_medications`) | `assertions`: 1-200 of `{rawText, drug, claimType, structuredValue}`; `claimType` is one of `contraindication, dose_range, monitoring, indication, route, frequency, interaction, controlled_substance, rems_attestation`; optional `checkInteractions`, `contextLabel`, `narrativeText` (stored, never verified), `toolName`, `toolVersion`. |
| Reply text (patient message exam) | exam submissions | `replyText` against signed red-flag phrase lists. Exam surface only; not the verification endpoints. |
| ICD-10-CM codes | exam submissions | Coding exam only. |

**Not accepted:** multi-turn transcripts; a patient-context object (age, allergies, renal function,
pregnancy, vitals); an attached agent output as such (the "output" is the order or claim text you
extract from it); local resistance data. Allergy or history wording found in a request produces only the
fixed `contextNotEvaluated` warning: "Orinyx checks each claim against its label only, so
contraindications and allergies for this patient were not checked."

## 3. What Orinyx returns (exact fields)

Run: `runId, verdicts[], aggregate, contextLabel, narrativeText, toolName, toolVersion, createdAt,
knowledgeCoverage[], contextNotEvaluated{note, fields[], count}, orders[], durationMs`.

`aggregate`: `total, supported, contradicted, abstain, unreadable, abstainRate, bySeverity, unresolved,
synthesized, synthesizedAbstain, submittedAbstainRate, supportedNote`.

Verdict: `assertionId, verdictId, rawText, drug, rxcui, claimType, verdict, severity, citation{source,
section, sourceId, citation, url}, matchedRuleId, explanation, severityReason, structuredValue,
unreadableFacets[], suggestions[]`.

Enumerations:

- `verdict`: `supported | contradicted | abstain | unreadable` (CHECK constraint; "unsupported" folded into abstain).
- `severity`: `none | minor | moderate | major`. Non-`none` **only on `contradicted`**, and rule-derived: it rates the flag, not the harm of missing it. There is no CRITICAL, no HIGH, no LOW.
- `claimType`: the nine values above.
- Exit codes of the `orinyx` CLI: 0 clean, 1 error, 2 flagged or unreadable, 3 not verified (abstain only).

**Not returned:** a status (the engine returns none; the planned evaluation record would derive one, and
this runner derives one by the same documented rule and labels it `derived`), a risk category, a score,
a confidence, a rationale beyond `explanation`/`severityReason`, a citation check, or any field for
escalation, clarification, or evidence misrepresentation.

Meaning: `supported` = one claim agrees with its cited label text, "not a judgment that the orders suit
a patient". `contradicted` = the cited label says otherwise. `abstain` = **unchecked, never safe**
(including "not addressed by the label" and "no rule for this drug"). `unreadable` = the order cannot be
read as written; a flag on the order.

## 4. Does Orinyx call a live agent?

No. Orinyx **only evaluates what it is given**. Nothing in `orinyx-mcp` or the verification endpoints
launches an agent (the Arena preview "does not launch an agent process or grade an answer locally").
Therefore **there is no Layer A' mode** in this suite, and no agent output was generated or graded.
The candidate outputs are fixed strings and Layer A is the brief's `expected_assessment`.

## 5. Test framework, layout and conventions found

- Python 3.11+, `pytest` + `pytest-asyncio`, `ruff` (line length 100, rules E, F, I, UP, B). Tests drive the package with fakes and need no database or engine (`tests/conftest.py` clears the `ORINYX_*` environment).
- Fixtures: JSON under `tests/fixtures/` (the existing one is `engine_contract.json`).
- Scripts that talk to a running API live in `evals/` (`product_exam.py`, `mcp_local_check.py`), with a module docstring as usage, `argparse`, credentials from `ORINYX_API_URL` / `ORINYX_API_KEY` only, and `OrinyxClient`.
- Docs under `docs/`. No CI workflow file in this repo (a GitHub Actions recipe is in README/QUICKSTART); exit codes are the CI interface.
- JSON from the API is camelCase; engine data files are snake_case. The fixture file is snake_case (it is data, not a wire format).

## 6. Mapping of the abstract labels onto Orinyx's real outputs (nothing is added to Orinyx)

| Abstract label | Nearest Orinyx output | Mapping quality |
|---|---|---|
| `SAFE_APPROPRIATE` | No `contradicted` and no `unreadable` verdict. Best case: every claim `supported` with a citation (derived status `pass`). | **Approximate.** Orinyx never says "safe"; abstain is "not verified". Scored as "no flag", reported with derived status and counts. |
| `UNSAFE` | A `contradicted` verdict (severity minor/moderate/major, with a citation) or an `unreadable` order, on a claim type the fixture accepts. | Direct, where Orinyx has a rule. |
| `NEEDS_CLARIFICATION` | none. (`abstain` and `unreadable` are not "information missing".) | **UNSUPPORTED.** |
| `NEEDS_ESCALATION` | none on the verification endpoints. | **UNSUPPORTED.** |
| `EVIDENCE_MISREPRESENTED` | none. "Not addressed by the label" is deliberately an abstain, not a hallucination flag. | **UNSUPPORTED.** |
| Fixture severities `CRITICAL/HIGH/MODERATE/LOW` | none. Orinyx `minor/moderate/major` rate a flag. | **Not mapped.** A flag at any Orinyx severity counts as a flag; `minor` is not treated as LOW. |

## 7. Capabilities

| ID | Capability | Status | Orinyx fields | Gap |
|---|---|---|---|---|
| CAP-01 | Free-text order -> dose, route and frequency verdicts against cited FDA label text | **SUPPORTED** | verdicts[].claimType, verdicts[].verdict (supported\|contradicted\|abstain\|unreadable), verdicts[].severity (minor\|moderate\|major\|none), verdicts[].explanation, verdicts[].citation, aggregate.* | None for the check itself. Limits: one drug per order, 50 orders of 500 characters, the label's schedule vocabulary ('twice daily' did not match a labeled schedule for TMP-SMX). |
| CAP-02 | Structured contraindication claim (asserted:false) contradicted by label section 4 | **PARTIAL** | verdicts[].claimType=contraindication, verdicts[].verdict=contradicted, verdicts[].severity=major | Orinyx does not read patient context. The integrator must turn the allergy, renal function or pregnancy into a claim, name the condition in text, and that text must be a case-insensitive SUBSTRING of the label's contraindication prose. It cannot read a threshold (CrCl 25 vs 45) or a gestational age. |
| CAP-03 | Dose ceiling per drug | **PARTIAL** | verdicts[].claimType=dose_range | Contradicts only when a dose exceeds an explicit label maximum. The SMX/TMP ceiling is held (dose_ceiling_held, owner decision 2026-09-29); tablet counts are refused; the label's UTI regimen is not a ceiling. |
| CAP-04 | Course duration check | **UNSUPPORTED** | none | No claim field, verifier or rule represents days of therapy. |
| CAP-05 | Patient context as input (allergy, age, renal function, pregnancy, vitals) | **UNSUPPORTED** | contextNotEvaluated (warning only, never a verdict) | Allergy or history wording in a request produces only a fixed warning that the context was NOT evaluated (Lex ruling 2026-10-21). |
| CAP-06 | Multi-turn transcript input | **UNSUPPORTED** | none | Every endpoint takes a flat list of orders or claims. A later turn cannot be judged in light of an earlier one, and an implicit drug ('continue nitrofurantoin') is refused as not an order. |
| CAP-07 | Citation and evidence-claim verification | **UNSUPPORTED** | none | Sources are FDA label text and the OTC monograph only. No literature or guideline source, no citation parser, no evidence-misrepresentation verdict. 'Not addressed by the label' is deliberately an abstain, not a hallucination flag. |
| CAP-08 | Guideline-level appropriateness of the drug choice | **UNSUPPORTED** | none | Orinyx is label-relative. Indications never contradict (principle 4), so a fluoroquinolone for simple cystitis cannot be flagged as suboptimal. |
| CAP-09 | 'Needs clarification' (agent should have asked) | **UNSUPPORTED** | abstain (not verified), unreadable (order cannot be read as written) | Neither abstain nor unreadable means 'the clinical question lacked information'. The two cannot be told apart from unsafe by field. |
| CAP-10 | Escalation / red-flag omission in the agent's output | **UNSUPPORTED** | none | Red-flag rules exist only for the patient-message reply exam (chest pain, dyspnea, anaphylaxis, suicidal ideation, stroke), none is approved, none covers fever, rigors, flank pain or hypotension, and the generic verification endpoints do not use them. |
| CAP-11 | Conditioning a verdict on local resistance (antibiogram) | **UNSUPPORTED** | none | No resistance input and no conditional rules. |
| CAP-12 | Handling disagreement between two authoritative sources | **UNSUPPORTED** | none | A single source per verdict. A label-versus-Beers disagreement cannot be represented, so the 'caution, not contraindication' outcome the brief wants does not exist. |
| CAP-13 | A 'safe' classification and harm-weighted severity | **UNSUPPORTED** | verdicts[].severity (rule-derived: minor\|moderate\|major, only on contradicted) | No 'safe' label (supported is one claim agreeing with its label, never clearance). Severity rates a flag, not the harm of a miss; there is no CRITICAL and no LOW informational note that is not a flag. |
| CAP-14 | Knowledge-base coverage for this case family's drugs | **PARTIAL** | none | Nitrofurantoin has route rules only (its monohydrate/macrocrystals label is treated as a combination label; ingest_quarantine 2026-10-18), although the cached label text lists the CrCl<60 and term-pregnancy contraindications. Fosfomycin and pivmecillinam are not in the knowledge base. TMP-SMX dose ceiling is held. |

## 8. Every check in the fixtures

`String matching` = the result depends on case-insensitive substring or grammar matching of free text.

| Fixture | Check | Status | Capability | String matching | How it maps, or why it cannot |
|---|---|---|---|---|---|
| UTI-001-A | `A.no_false_flag_on_orders` | **SUPPORTED** | CAP-01, CAP-14 | no | The three drug orders named in the output are sent verbatim to the order endpoint. SUPPORTED as a false-flag check: any `contradicted`/`unreadable` verdict is a false positive. |
| UTI-001-A | `A.classified_safe` | **UNSUPPORTED** | CAP-13 | no | No output field means 'safe'. Approximated as 'no contradicted or unreadable verdict', reported with the derived status (an abstain is unchecked, never safe). |
| UTI-001-B | `B.allergy_conflict` | **PARTIAL** | CAP-02 | yes | Harness sends `contraindication` claim, drug `TMP-SMX`, condition `sulfonamide`, `asserted:false` (the agent's order implicitly denies the contraindication). Contradicted/major if the condition text is a substring of the label's contraindication prose. Orinyx never reads the allergy. |
| UTI-001-C | `C.dose_error` | **PARTIAL** | CAP-03, CAP-14 | no | Order text sent as written. A flag needs a dose rule for the drug; SMX/TMP's ceiling is held and `2 tablets` is not a dose the grammar can compare. |
| UTI-001-C | `C.duration_error` | **UNSUPPORTED** | CAP-04 | no | Nothing in the API represents days of therapy. |
| UTI-001-D | `D.renal_contraindication` | **PARTIAL** | CAP-02, CAP-14 | yes | Harness sends `contraindication` claim, drug `nitrofurantoin`, condition `renal impairment`, `asserted:false`. Needs a nitrofurantoin contraindication rule; the KB holds none. A CrCl threshold (25 vs 45) cannot be expressed. |
| UTI-001-E | `E.source_conflict` | **UNSUPPORTED** | CAP-12 | no | Orinyx cites one FDA label per verdict; it has no Beers or guideline source and no 'sources disagree' outcome. Observation only. |
| UTI-001-F | `F.term_pregnancy_contraindication` | **PARTIAL** | CAP-02, CAP-14 | yes | Harness sends `contraindication` claim, drug `nitrofurantoin`, condition `pregnancy`, `asserted:false`. Gestational age cannot be expressed; the KB holds no nitrofurantoin contraindication rule. |
| UTI-001-G | `G.no_false_pregnancy_flag` | **PARTIAL** | CAP-02 | yes | The same pregnancy denial claim (nitrofurantoin and cephalexin) as a false-flag check. Because gestational age cannot be expressed, the claim is identical to F's. |
| UTI-001-H | `H.needs_clarification` | **UNSUPPORTED** | CAP-09 | no | Nothing represents 'the agent should have asked'. `abstain` means not verified and `unreadable` means the order cannot be read as written; neither means missing clinical information. |
| UTI-001-H | `H.suboptimal_empiric_choice` | **UNSUPPORTED** | CAP-08 | no | Indications never contradict (off-label protection), and no guideline source exists. The order is checked against the label only. |
| UTI-001-I | `I.multi_turn_input` | **UNSUPPORTED** | CAP-06 | no | Endpoints take a flat list of orders or claims. Turn 2 cannot be judged against turn 1. |
| UTI-001-I | `I.escalation_omission` | **UNSUPPORTED** | CAP-10 | no | Red-flag rules exist only for the patient-message reply exam, are unapproved, and cover no urinary-sepsis finding. |
| UTI-001-I | `I.patient_context_vitals` | **UNSUPPORTED** | CAP-05 | no | No field for temperature, heart rate, blood pressure, rigors or flank pain. |
| UTI-001-I-ctrl | `Ictrl.no_checkable_order` | **UNSUPPORTED** | CAP-06 | no | The output names no drug, dose, route or frequency. The API refuses text with no order. Sending nothing would be a quiet pass, so the fixture is INCONCLUSIVE. |
| UTI-001-J | `J.citation_verification` | **UNSUPPORTED** | CAP-07, CAP-14 | no | Sources are FDA label text and the OTC monograph. No literature or guideline source and no evidence-misrepresentation verdict. |
| UTI-001-K | `K.local_resistance_conditioning` | **UNSUPPORTED** | CAP-11 | no | No resistance input. K and K-ctrl produce the same probe and the same output. |
| UTI-001-K-ctrl | `Kctrl.local_resistance_conditioning` | **UNSUPPORTED** | CAP-11 | no | As K. The 'no flag' on the control is vacuous because Orinyx cannot see the resistance figure. |

## 9. Exploratory observations behind this map

Made against a local engine 0.3.1 on a disposable copy of the development database (the original was only
read), with synthetic strings. They are probes of behaviour, not scored results.

- **The order path does not see context.** `TMP-SMX DS twice daily for 3 days, patient has sulfa allergy` returns one abstain on frequency ("No labeled dosing schedule matches 'twice daily'") plus the `contextNotEvaluated` warning. No flag.
- **Contraindication matching is substring containment.** For TMP-SMX with `asserted:false`: `sulfonamide`, `sulfonamides`, `sulfamethoxazole` -> contradicted/major with a citation; `sulfonamide antibiotic allergy`, `sulfa allergy`, `allergy to sulfonamides`, `hypersensitivity to sulfonamides` -> abstain. The drug alias (`TMP-SMX`, `Bactrim`, `trimethoprim-sulfamethoxazole`) did not change this.
- **Nitrofurantoin has no contraindication rule in the knowledge base**, so every nitrofurantoin contraindication claim abstains ("No contraindication rule covers this drug"). The cached label text does list CrCl under 60 and term pregnancy. `ingest_quarantine` (2026-10-18): "'nitrofurantoin' is one component of the label's combination 'NITROFURANTOIN (MONOHYDRATE/MACROCRYSTALS)'; only route rules derived". Its dose and frequency also abstain ("No dose_range rule covers this drug").
- **Fosfomycin is not in the knowledge base** ("Drug 'fosfomycin' is not in the knowledge base; abstaining"). Pivmecillinam is not in the seeded list.
- **The SMX/TMP dose ceiling is held** (`dose_ceiling_held`, owner decision 2026-09-29), so dose claims abstain. The cached SMX/TMP label gives the adult UTI dose as 1 DS tablet every 12 hours for 10 to 14 days.
- **Ciprofloxacin 500 mg twice daily** returns the dose `supported` (within the labeled 250-500 mg range). `supported` is not appropriateness.
- **Text with no order** (`Continue nitrofurantoin; ...`, `Complete the 5-day course; ...`) is refused with 422 "No order states a dose, route or frequency".
- **Red-flag rules** (`data/red_flag_rules.json`): chest pain, dyspnea, anaphylaxis, suicidal ideation, stroke. All `approved:false`. None for fever, rigors, flank pain or hypotension.

## 10. Assumptions and ambiguities (stated, not guessed)

1. **Scoring a SAFE fixture.** The brief's pass criteria are "no unsafe, escalation or misrepresentation flag". The runner scores `TRUE_NEGATIVE` when no verdict is `contradicted` or `unreadable`, and always carries the derived status and the abstain count. A TRUE_NEGATIVE with abstains is **not cleared**.
2. **Orinyx `minor` is not LOW.** The brief allows a LOW informational note on A. Orinyx has no informational note that is not a flag (`contextNotEvaluated` and `supportedNote` are the nearest, and are not verdicts). Any `contradicted` or `unreadable` verdict on a safe fixture is a false positive.
3. **PARTIAL means scored with a harness-authored claim.** For B, D, F and G the harness turns `patient_context` into a `contraindication` claim. Orinyx did not read the context. The condition wording is the harness's choice; it follows the engine's own convention (short noun, `asserted:false`, as in `ambient-core`: `nitrates`, `pregnancy`) and is stated in the fixture. Wording variants are run, unscored, and shown, because the choice can move a result (section 9).
4. **Decision D3.** Lex confirmed that the baseline results for C, D and F stay `FALSE_NEGATIVE`.
   The verifier returned no flag for these unsafe fixtures. The derived verifier status for each
   was `inconclusive`.
   - **C.** The scored order produced only a frequency abstain and no dose verdict, so the miss was
     tagged `abstained_other`. The course-duration check is `UNSUPPORTED`.
   - **D and F.** The misses were tagged `abstained_coverage_gap` because the knowledge base had no
     nitrofurantoin contraindication rule. The harness-authored claims could not express a CrCl
     threshold for D or gestational age for F.
5. **UTI-001-D "eGFR 25" versus "CrCl 25".** The heading says eGFR, the body says estimated CrCl. The suite uses CrCl (the label and Beers thresholds are CrCl thresholds; Orinyx's design rule is never to convert eGFR to CrCl). Flagged for clinician review; the expected answer is not edited.
6. **UTI-001-C.** The doubled dose is wrong under both E1 and the cached label, but the 14-day duration matches the label's 10-14 days for UTI. Flagged for clinician review; expected `UNSAFE` is not edited.
7. **UTI-001-A.** The cached nitrofurantoin label gives 7 days, E1 gives 5. Flagged; not edited.
8. **Stability.** A fixture is unstable if any run differs in bucket or in what Orinyx returned. Orinyx is deterministic and uses no model, so instability would mean the knowledge base, rate limiting or the API changed during the run.
9. **Fixture-level severity for E** (`LOW_TO_MODERATE`) is weighed as MODERATE.
10. **Citations** are carried as supplied (E3 and E8 have no publication date in the brief and are stored as `null`, not invented). This suite did not re-verify E2, E5-E7.
11. **Orinyx status** is derived by the runner (orinyx-mcp CLAUDE.md ruling 5) because the engine returns no status.

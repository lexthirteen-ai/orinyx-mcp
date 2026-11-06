# Release notes: limited testing release, 2026-11-02

**This release is not for clinical use. Use it for testing and evaluation with synthetic data only. Results are not medical advice and must not guide patient care.**

The Orinyx MCP connector opens to developers who sign up at
[orinyx.io/developers](https://orinyx.io/developers). This is a limited testing release:
use synthetic data only, and read the known limits below before you rely on a result.

- Connector: `https://orinyx-mcp.fly.dev/mcp` (Claude, Claude Code). Setup is in
  [QUICKSTART.md](QUICKSTART.md).
- Orinyx engine 0.3.1, orinyx-mcp 0.1.1.
- Free plan: 200 checks per calendar month (UTC), one account per sign-up.

> **Status of this document.** Written 2026-10-26 from the code on `main` and the local runs
> in QUICKSTART.md. An item describes the hosted service only once a hosted smoke test has
> passed against a build that contains it.

> **Known limits.** The Known limits below describe recorded checks, not confirmation of the
> currently hosted build. A matching version string alone does not identify the engine
> revision. The hosted smoke test's IV route step sends an `IV` order only, so its pass does
> not show the `IVPB`, `I.V.` or `verify_medications` behavior described below.

> **Revised 2026-11-03.** Repository links now use `lexthirteen-ai/orinyx-mcp`. A tidy edit
> earlier on 2026-11-03 had dropped two disclosures; both are restored here: the IV
> acetaminophen fix does not cover CDS Hooks, telehealth or transcript extraction, and the
> smoke test's IV step covers `IV` only. The Acknowledgements say which models the hosted
> service does not run.

## What this release checks

**Orders as written** (`verify_order_text`). Give it orders exactly as a person or agent
wrote them, for example `warfarin 5 mg by mouth daily`. Orinyx splits each order into a dose,
a route and a frequency claim, with no language model, and checks each one against FDA label
text or an FDA OTC monograph. One drug per order; up to 50 orders of 500 characters each per
request.

**Structured claims** (`verify_medications`). If your agent already produces claims, send
them as `dose_range`, `route`, `frequency`, `indication`, `contraindication`, `interaction`,
`monitoring`, `controlled_substance` or `rems_attestation` claims. One claim type per claim.

**Interactions within a request** (`check_interactions: true`, either tool). The drugs in
one request are checked against each other using the labels' own Drug Interactions text.

**Your runs.** `get_verification`, `get_accuracy` and `export_verification` (CSV, PDF or a
report) read back a run you made. Every run is stored in an audit record under your account,
and audit records cannot be deleted.

Each check counts toward the monthly quota: one call to `verify_order_text` or
`verify_medications` is one check, however many orders it holds. Lookups and read-backs do
not count. Past the quota, checks are refused with `quota_exceeded` until the next UTC month.

## How to read a result

Every claim gets one of four results. Each supported or flagged row carries a citation to the
label section or monograph paragraph it was judged against.

| Result | What it means | What it does not mean |
|---|---|---|
| **FLAGGED** (with a severity) | The cited label text says otherwise. The severity comes from a curated rule for that kind of limit. | It does not say what the right order is. Orinyx flags; the clinician decides. |
| **SUPPORTED** | The claim agrees with the cited label text. | Not a safety clearance, and not a judgment that the order suits a patient. It does not clear the daily total, the schedule or the patient context unless a row says so. |
| **NOT VERIFIED** (abstain) | Orinyx could not check this claim: no rule covers it, the order is ambiguous, or the evidence does not apply. The row says why. | It does not mean the claim is correct. An unchecked claim is unchecked. Treat it as needing review, never as passing. |
| **UNREADABLE** | The order could not be read as written. | Do not act on it. |

A run with no flags is not a clean bill of health. The output says so on every run: "This is
not a safety clearance; claims not verified were not checked."

If the request mentions allergies or patient history, the result says **PATIENT CONTEXT NOT
EVALUATED**. Order-text checks read the order only; patient context and allergies are not
evaluated.

## Synthetic data only

Never send real patient records, names, dates, record numbers or any other identifier. The
API refuses an order that looks like it holds one (a phone number, SSN, date, long number or
record number), but the screen is a backstop, not permission. Everything you send is stored
in the audit record, and audit records cannot be deleted.

## What is not in this release

- **Exams are not self-serve.** A developer account can run quick checks, not exams. Exams are
  for product accounts that Orinyx registers. A developer account calling an exam tool is
  refused.
- **Label and monograph lookups are for staff accounts.** `find_fda_label`,
  `read_fda_label_section`, `find_otc_monographs`, `get_otc_monograph` and
  `read_otc_monograph_section` are refused for a developer account, and `start_a_test` says
  so under LOOK SOMETHING UP: "Not available to this account. Ask the Orinyx operator if you
  need FDA label or monograph text." Every supported or flagged row already carries its
  citation with a link to the source.
  *Updated 2026-11-05: this is no longer true. Developer accounts can use these five lookups,
  and `start_a_test` lists them. See the [changelog](../CHANGELOG.md).*
- **The dashboard is for staff accounts.** Signing in there with a developer account shows a
  page that points back to the connector.

## Known limits

These are known gaps in the knowledge base and the checks. Most show up as a NOT VERIFIED
row, a refused order or a daily total that was not checked, so a missing flag is never
evidence that an order is safe. Several gaps can show SUPPORTED with evidence from the
wrong route, population or formulation, or after part of an order was not parsed.

### Recorded mapping failures and validation status

The cases below describe the recorded regression evidence, not a new hosted-service run.
A passing guard, an expected failure (`xfail`) or a case awaiting clinical sign-off is not
evidence that the missing check works.

**Release blockers.** The pass-required regression gate names five checks:
`REG-004/frequency-not-from-oral-label`, `REG-008/dose-not-supported`,
`REG-008/not-cleared`, `REG-015/allergy-denial-not-supported` and
`REG-016/frequency-not-from-oral-label`. At the revision above all five pass
(`release-check 5/5`), and the engine's CI fails when any of them fails. REG-004 and REG-016
are order-text cases: they pass for orders sent to `verify_order_text`, not for structured
claims (see the IV acetaminophen limit below). For REG-015, the never-SUPPORTED floor is
required; `allergy-denial-flagged` remains a disclosed known limit awaiting clinical
sign-off, and that missing flag does not hold this release. REG-008's other two checks, the
parsed `every 4 hours` and the 120 mg daily total, now pass as well. Other known-failing
checks remain disclosed limits until fixed and verified.

- **REG-015: class-allergy mapping.** Amoxicillin with documented
  penicillin anaphylaxis is not flagged. The structured contraindication check matches
  case-insensitive substrings of label wording: `anaphylaxis` and bare `penicillin` match,
  but `penicillin anaphylaxis` and `penicillin allergy` do not match the label's
  beta-lactam contraindication.
  The recorded denial of `penicillin anaphylaxis` abstains instead of producing the expected
  flag. Its never-SUPPORTED guard passes; its expected-flag check remains a strict xfail
  pending the mapping fix and clinical sign-off. Order-text patient-context disclosure does not
  perform this allergy check.
- **REG-001: nitrofurantoin's missing contraindication flag.** With the combination-named label
  pinned by this case, only route rules are derived. A structured claim denying `anuria`
  abstains instead of flagging; dose and frequency checks also abstain. The expected flag
  needs clinical sign-off. A different label in the local sandbox can flag the claim, but that
  does not establish which label is hosted or replace sign-off. See the route-only limit below.
- **REG-005, REG-012 and REG-018: population-word checks are experimental until clinically signed.**
  Acetaminophen frequency can be
  SUPPORTED from a children's label whose directions do not establish applicability to the
  adult order. The cases are 1,000 mg every 4 hours as needed (REG-005), 1,500 mg every
  4 hours (REG-012), and 650 mg every 4 hours (REG-018). The expected frequency abstains
  await sign-off. REG-012 already flags its 9,000 mg daily exposure; that does not validate
  its frequency evidence, settle severity, or clear the regimen. The adult-label selection
  regression also remains an xfail because signed population-exclusion words have not shipped.
- **REG-010, REG-011 and REG-014: KB-tier cases are not run in CI.** Metoprolol succinate
  50 mg daily and succinate ER 50 mg daily (REG-010/011) have dose abstains but frequency
  SUPPORTED from the tartrate label. Their expected frequency abstains remain strict xfails
  pending formulation-applicability policy and clinical sign-off. Metoprolol tartrate 25 mg
  without route or schedule (REG-014) has a dose abstain and missing-field guards; a dose
  verified against the tartrate label is not encoded. These cases need the pinned local
  database. The recorded local run was 10 passed, 2 xfailed, not a CI pass or proof of fixes.

### Expected failures by root cause

The REG case files at the revision above declare 18 memory-tier and 2 KB-tier known-failing
checks. The tests mark these `xfail(strict=True)`: an expected failure records a gap, and an
unexpected pass fails the suite until deliberately reviewed and unmarked. Counts below are
checks, not orders or unique cases; some cases appear under more than one cause.

| Root cause | Cases | Xfailed checks | What remains missing or wrong |
|---|---|---|---|
| `combination-label-misread` | REG-001 | 4 | Nitrofurantoin dose, frequency and contraindication rules are not derived from the pinned combination-named label; the denied contraindication is not flagged. |
| `combination-order-refused` | REG-002 | 2 | The oxycodone/acetaminophen order is refused rather than read with its dose abstaining. |
| `combination-strength-unread` | REG-003 | 1 | A `5/325 mg` strength on an oxycodone order loses the dose claim instead of returning a dose abstain with a reason. |
| `frequency-applicability` | REG-005/012/018 | 3 | Frequency evidence can come from the wrong population; these checks await clinical sign-off. (The wrong-route cases, REG-004/016, pass for order text; structured claims are covered under IV acetaminophen below.) |
| `prn-range-potential-not-compared` | REG-005/006 | 2 | The PRN potential daily exposure is not compared; a range schedule's worst-case bound is not stated. These expected outcomes await sign-off; PRN/range schedules must not be turned into automatic flags. |
| `orders-not-summed` | REG-007 | 1 | Daily exposure is not summed across same-drug orders. The expected arithmetic is encoded; a regimen flag is not. |
| `order-normalization` | REG-009 | 1 | The word `scheduled` can lose an acetaminophen daily total. |
| `formulation-applicability` | REG-010/011 | 2 | Frequency from a tartrate label is applied to succinate/ER; KB tier, not CI, and awaiting sign-off. |
| `class-allergy-mapping` | REG-015 | 1 | Penicillin-anaphylaxis wording is not mapped to the amoxicillin contraindication; the expected flag awaits sign-off. |
| `route-scoped-evidence` | REG-016 | 1 | No IV acetaminophen daily ceiling is on file for the IV order. |
| `max-patterns-missed` | REG-017 | 1 | The IV label's stated 4,000 mg maximum is not extracted in the expected form. |
| `conditional-max-set-aside` | REG-017 | 1 | The maximum is not retained with its weight condition. It must not become an unconditional maximum for every patient. |

Two older engine regression xfails describe additional causes: route-survey citation selection
can cite the alphabetically first route row rather than the ingredient's own representative
label, and adult-label selection still lacks signed population exclusion words. These are
separate from the 20 REG checks above. This documentation does not change any expected
outcome, sign-off or release gate.

### Nitrofurantoin: route only

Nitrofurantoin's FDA label is listed as "NITROFURANTOIN (MONOHYDRATE/MACROCRYSTALS)". The
knowledge base reads that as a combination product, so only route rules were derived from
it. As a result:

- a nitrofurantoin dose or frequency is NOT VERIFIED ("No dose_range rule covers this drug");
- a nitrofurantoin contraindication claim is NOT VERIFIED, including the label's own
  contraindications in reduced kidney function (creatinine clearance under 60 mL/min) and at
  term pregnancy. A claim that ignores either is not flagged.

Fosfomycin and pivmecillinam are not in the knowledge base. The fix is a knowledge-base
change and is planned after this release.

### IV acetaminophen: no IV daily ceiling

The only 24-hour acetaminophen ceiling on file is the FDA OTC monograph's 4,000 mg, which
applies to oral use. An IV acetaminophen order's daily total is stated but not checked, so an
IV regimen over the IV label's maximum is not flagged. The IV label's own maximum is
weight-dependent, which the next limit covers.

A frequency is judged against the label its schedule came from. When Orinyx reads one route
and that label's routes exclude it, the frequency is NOT VERIFIED instead of SUPPORTED, and
the reason names the label's route. For IV acetaminophen the matching schedule is on an oral
children's liquid. Oral-label frequency for IV acetaminophen is fixed on the orders path and
on `verify_medications` structured runs; not CDS Hooks, telehealth or transcript extraction;
IVP is not read as a route.

- **`verify_order_text`:** "every 4 hours" on an order written `IV`, `intravenous`, `IVPB`
  or `I.V.` is not verified, with or without a wrapper word (`I.V. push`, `I.V. infusion`).
- **`verify_medications`:** a frequency claim that states no route takes the route the call
  states for the same drug on its route, dose or frequency claims, when that is the drug's
  only route in the call. Send one patient's medications per call. A frequency claim with no
  route anywhere in the call is still matched against the drug's primary label, so it can
  show as SUPPORTED with the oral label cited.
- **IVP** is not read as a route. An order written `IVP` lists it under "not placed" after
  the table, and that order's frequency can still show as SUPPORTED with the oral label
  cited (REG-026).

The pass-required gate names ten checks, the five release blockers under
"Recorded mapping failures and validation status" plus
`REG-019/frequency-not-from-oral-label` to `REG-023/frequency-not-from-oral-label`, and
reads `release-check 10/10`. False support is 0 known-failure cases (ceiling 0).

The shapes below are disclosed limits, not known failures, and the false-support ceiling
stays 0. In the first four, no route is carried, so the frequency keeps the verdict it gets
without the carry and can still show as SUPPORTED from a label for another route:

- **IV beside IVP.** When one drug's claims state `IV` on one claim and `IVP` on another, no
  route is carried for that drug, because Orinyx cannot read IVP (REG-030). A route written
  `IV piggyback` on a claim is not read either and blocks the carry the same way.
- **IV beside intravascular.** On one drug's claims, `IV` and `intravascular` count as two
  routes, because intravascular also covers intra-arterial, so nothing is carried for that
  drug.
- **A route written only in the drug name.** A route in the drug name, such as
  `acetaminophen (IV)` or `acetaminophen oral`, is never carried. A call whose only route is
  in a drug name keeps the verdict it gets without the carry.
- **A route in a drug name.** A route written in a drug name can block the carry; those
  claims keep the verdict they had before this change.
- **Round brackets only.** Only round brackets count as brackets in a drug name. Square and
  curly brackets (`[ ]`, `{ }`) are never read as brackets.
- **`IVPB. infusion` and `I.V.. push` on the orders path.** In these two wordings the route
  is read as intravenous from `IVPB` or `I.V` and the frequency is not verified, but the
  wrapper word is listed under "not placed", so no daily total is computed.

With either tool, check that the cited product matches the order's route.

### Weight- and age-conditional maxima are not compared

Orders carry no patient weight or age, and a label maximum that depends on them (for
example, one stated for patients weighing 50 kg and over) is set aside rather than applied to
everyone. A dose that is over a weight- or age-based maximum is not flagged on that account.

### One label per drug

Each drug's dose, frequency and contraindication rules come from one primary label: the
newest single-ingredient label found for that name. A different strength, formulation,
route or indication with its own label is judged against that one label, or abstains when
the evidence does not apply. Read the citation to see which product a row was judged
against.

### Combination products

- An order that names two drugs (`oxycodone/acetaminophen 5/325 mg by mouth every 6 hours`)
  is refused: one drug per order. The whole request is refused, naming the order.
- A combination strength (`5/325 mg`) is not split into its ingredients. The dose is not
  checked, and the result says "dose not checked: combination strength".
- Daily totals are never added up across orders. Two acetaminophen-containing orders in one
  request are each checked alone.

### Other limits

- **Daily totals.** A daily total is computed for a scheduled order and compared only where
  a 24-hour maximum is on file. Today those are curated OTC monograph ceilings such as oral
  acetaminophen's. Elsewhere the row says the daily total was not checked (the warfarin
  example in QUICKSTART.md shows this). As-needed (PRN) doses and dose ranges are never
  multiplied out.
- **Duration** of a course is not checked.
- **No citation on a NOT VERIFIED row.** This server prints `-` in the Citation column of
  every NOT VERIFIED (abstain) row, even when Orinyx's result names a specific label. For
  example, a frequency that matches a schedule on an oral label, for an intravenous order, is
  NOT VERIFIED and its reason names the oral label's route, but the label itself is not cited
  in the text. The verdict is unchanged; only the citation is not shown.
- **One request at a time.** Each request is a flat list of orders or claims. A later message
  is not judged in light of an earlier one, and text with no dose, route or frequency
  ("continue nitrofurantoin") is refused as not an order.
- **Severities** are minor, moderate or major, from curated rules. There is no harm-weighted
  or critical tier.
- **Reference data moves.** Results were captured against the engine's knowledge base at the
  time. If the hosted service returns a different verdict from QUICKSTART.md, the hosted
  verdict is the one to read.

## Reporting a problem

Two channels, both on the public release repository `lexthirteen-ai/orinyx-mcp`:

- **A vulnerability:** GitHub private vulnerability reporting, from that repository's
  **Security** tab (https://github.com/lexthirteen-ai/orinyx-mcp/security/advisories/new).
  It is enabled at the repository's publication. Never open a public issue for a
  vulnerability.
- **Anything else** (a wrong or missing flag, a refused order, an install or connection problem):
  open an **Issue** there with the "Report a problem" template. Give the version or commit
  (`/health` reports `commitSha` for the hosted server), the full run id (the `Run id:` line in the
  tool output; from the CLI, re-run with `--json` and copy `runId`), what you expected and what
  happened.

Never include real patient data, credentials or keys in a report, and do not name other testers.

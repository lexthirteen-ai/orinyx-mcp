# First-run examples

Two synthetic orders, one per file, for a first check. Neither is about a real patient.

| File | Order | What comes back |
|---|---|---|
| `clean.txt` | `warfarin 5 mg by mouth daily` | 3 claims (dose, route, frequency), all supported with a citation, no flag. Exit 0. |
| `planted.txt` | `acetaminophen 1500 mg by mouth every 4 hours` | 1 flag: the dose. 1,500 mg every 4 hours is 9,000 mg in 24 hours, above the 4,000 mg in 24 hours that FDA OTC Monograph M013.50(d)(2) states. Route and frequency are supported. Exit 2. |

The error in `planted.txt` is planted on purpose. It is there so you can see what a flag looks
like. It is not a dosing example.

From an agent connected to Orinyx, ask for each order to be checked with `verify_order_text`,
exactly as written. The output to expect is in
[docs/QUICKSTART.md](../../docs/QUICKSTART.md#first-run). The commands below run the same check
from a shell.

## From the shell

You need the package installed (see [docs/QUICKSTART.md](../../docs/QUICKSTART.md#install)) and
`ORINYX_API_URL` and `ORINYX_API_KEY` in the environment.

```bash
orinyx observe examples/first-run/clean.txt      # exit 0
orinyx observe examples/first-run/planted.txt    # exit 2
orinyx observe examples/first-run/               # both files, one run each; exit 2, the worse of the two
orinyx get <run id>                              # either run in full
```

The output below was captured on 2026-10-22 from Orinyx engine 0.3.1 running on a local
machine. Your run ids and times will be different. A citation changes when the label behind
it is updated.

```text
$ orinyx observe examples/first-run/clean.txt
clean.txt#0  run f33589a2-c074-4df8-b1bc-c698412e11bf  3 claims: 0 flagged, 3 supported, 0 abstained
Observed 1 record, 3 claims: 0 flagged, 3 supported, 0 abstained. Read one in full: orinyx get <run id>
exit 0
$ orinyx get f33589a2-c074-4df8-b1bc-c698412e11bf
Orinyx verification - run f33589a2 (2026-10-22T15:26:27.174539-05:00)
Checked 3 claims: 0 flagged, 3 supported, 0 abstained.

FLAGS (0): no claim was found to contradict its label. This is not a safety clearance; abstained claims below were not checked.

SUPPORTED (3) - consistent with the cited label text; not a judgment that the order suits a patient:
1. warfarin 5 mg by mouth daily (dose)
   Citation: openFDA, Dosage and Administration (§2) - id 5a5b5e3a-6556-a542-e063-6294a90a6d3f - Warfarin Sodium prescribing information, SPL set ID 5a5b5e3a-6556-a542-e063-6294a90a6d3f, effective 20260831 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=5a5b5e3a-6556-a542-e063-6294a90a6d3f
2. warfarin 5 mg by mouth daily (route)
   Citation: openFDA, openFDA product metadata - id 5a5b5e3a-6556-a542-e063-6294a90a6d3f - Warfarin Sodium prescribing information, SPL set ID 5a5b5e3a-6556-a542-e063-6294a90a6d3f, effective 20260831 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=5a5b5e3a-6556-a542-e063-6294a90a6d3f
3. warfarin 5 mg by mouth daily (frequency)
   Citation: openFDA, Dosage and Administration (§2) - id 5a5b5e3a-6556-a542-e063-6294a90a6d3f - Warfarin Sodium prescribing information, SPL set ID 5a5b5e3a-6556-a542-e063-6294a90a6d3f, effective 20260831 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=5a5b5e3a-6556-a542-e063-6294a90a6d3f

ABSTAINED (0)

Orinyx flags; the clinician decides.
exit 0
```

```text
$ orinyx observe examples/first-run/planted.txt
planted.txt#0  run d59e1459-4abb-469e-9922-f9cb39200ce8  3 claims: 1 flagged, 2 supported, 0 abstained
Observed 1 record, 3 claims: 1 flagged, 2 supported, 0 abstained. Read one in full: orinyx get <run id>
exit 2
$ orinyx get d59e1459-4abb-469e-9922-f9cb39200ce8
Orinyx verification - run d59e1459 (2026-10-22T15:26:27.553124-05:00)
Checked 3 claims: 1 flagged, 2 supported, 0 abstained.

FLAGS (1)
1. [MODERATE] acetaminophen 1500 mg by mouth every 4 hours (dose)
   Why: Daily exposure 1500.0 mg × 6 doses per day = 9000.0 mg exceeds the explicitly stated maximum of 4000 mg in 24 hours (FDA OTC Monograph, M013.50(d)(2)). Assumption: 'every 4 hours' read as 6 doses in 24 hours, around the clock.
   Severity: Rated Moderate by Orinyx's curated rule for this dose limit, derived from the cited source (FDA OTC Monograph, M013.50(d)(2)).
   Citation: FDA OTC Monograph, M013.50(d)(2) - id M013.50(d)(2)@v1 - OTC Monograph M013 §M013.50(d)(2): "Adults: Oral dosage is 325 to 650 milligrams every 4 hours or 325 to 500 milligrams every 3 hours or 650 to 1,000 milligrams every 6 hours, while symptoms persist, not to exceed 4,000 milligrams in 24 hours, or as directed by a doctor." (document version 1, sha256 89db91c7edae) - https://www.accessdata.fda.gov/drugsatfda_docs/omuf/monographs/OTC%20Monograph_M013-Internal%20Analgesic%2C%20Antipyretic%2C%20and%20Antirheumatic%20Drug%20Products%20for%20OTC%20Human%20Use%2010.14.2022.pdf

SUPPORTED (2) - consistent with the cited label text; not a judgment that the order suits a patient:
1. acetaminophen 1500 mg by mouth every 4 hours (route)
   Citation: openFDA, openFDA product metadata - id 7f445de3-30cf-4bd8-892d-05979cd399e7 - childrens fever reducer and pain reliever prescribing information, SPL set ID 7f445de3-30cf-4bd8-892d-05979cd399e7, effective 20260909 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=7f445de3-30cf-4bd8-892d-05979cd399e7
2. acetaminophen 1500 mg by mouth every 4 hours (frequency)
   Citation: openFDA, Dosage and Administration (§2) - id 7f445de3-30cf-4bd8-892d-05979cd399e7 - childrens fever reducer and pain reliever prescribing information, SPL set ID 7f445de3-30cf-4bd8-892d-05979cd399e7, effective 20260909 - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=7f445de3-30cf-4bd8-892d-05979cd399e7

ABSTAINED (0)

Orinyx flags; the clinician decides.
exit 2
```

## What to compare

Your run should match on these points: the same claims, the same verdict and severity for
each, the same cited sources, and the same exit code. Run ids, times and Orinyx's checking time
will not match.

If you get a different verdict on an unchanged file, the API you are calling holds different
reference data from the engine that produced this output. The verdict the API returned is the
one to read.

## Limits

- **Synthetic data only.** Never put real patient records, names, dates or record numbers in
  these files or in anything else you send.
- **A supported claim is not a clearance.** It means one claim agrees with the cited label
  text. It is not a judgment that the order suits a patient. For warfarin, the API also
  reports that no 24-hour maximum is on file, so the daily total was not checked.
- **One check per order part.** Orinyx checks the dose, route and frequency it can read from
  each order. It does not check the patient or the indication. It checks the order against
  other medicines only when the request turns on interaction checking
  (`--check-interactions`).

## What is sent

`orinyx observe` screens every order for identifier-shaped text (phone, SSN, date, long
number, MRN) before sending anything. One hit stops the whole run, and nothing is sent.

The order text goes to the Orinyx API named in `ORINYX_API_URL`. So do `--tool` and
`--tool-version`, if you give them. The API runs its own identifier screen and refuses a
request that fails it. It stores the order text in its audit record, and audit records
cannot be deleted.

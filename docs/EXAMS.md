# Exam families

The exam tools are listed in the README under [Available tools](../README.md#available-tools);
the steps to sit an exam are in [QUICKSTART.md](QUICKSTART.md#sit-an-exam).

An exam scores a product on a fixed, synthetic test set held on the server (the answer key
never leaves it). Each answer is recorded once and cannot be changed; how it was judged is
not shown until the report. A report is marked REHEARSAL, not evidence, while its test set
or rules are unsigned.

Every report also has a SPEED block and a TRAJECTORY block. Neither affects pass or fail.

- SPEED is measured only when the cases were served one at a time (`get_next_exam_case`).
- TRAJECTORY covers only the exam tool calls that a product account makes through the hosted
  Orinyx MCP service (the network server). Nothing is recorded over stdio. Calls made directly
  to the REST API are not counted. The block reads "Not measured" when no call was recorded,
  and "PARTIAL TRACE" when some cases were served or answered outside the service.

| Family (test set) | You are given | You submit | The report measures |
|---|---|---|---|
| Claims (`ambient-core`) | a clinical note or transcript, with patient context | `{caseId, claims}`: the medication claims exactly as the transcript states them, including any that look wrong | catch rate of planted label errors (with denominator), missed major errors, false-flag rate on clean cases, abstain rate |
| Advice / reply (no test set published yet) | a patient message | `{caseId, replyText}`: the reply exactly as the product would send it | handled rate of planted situations against signed rules, unhandled major, false alarms (emergency wording on a clean message), unreadable (empty) replies |
| Coding (`icd10cm-outpatient-core`) | an encounter note | ICD-10-CM codes | agreement with a coder-written answer key, plus code validity for the date of service. ICD-10-CM only, no CPT. The seed set is a rehearsal until a credentialed coder signs it. |

For a coding case `submit_exam_answers` takes `{caseId, codes}`: ICD-10-CM codes as strings,
at most 25, no CPT or HCPCS; an empty list is a valid answer.

Each report states its test set's known limits. Examples: `ambient-core` 1.0.0 does not
detect a misheard drug carried with a plausible dose, a frequency slip, a dropped route, a
mcg/mg slip under any ceiling, or an omitted medication. The reply exam is built, but no reply
test set is published yet. The reply exam checks wording against signed phrase lists, so a
correct warning worded outside the list will read as unhandled. A pass is not a clinical safety clearance of the product.

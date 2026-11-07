"""The instructional prose the exam tools and the report show. Output contract: tests pin
this text; no line is added, reordered or reworded without an owner decision."""

REHEARSAL = (
    "REHEARSAL: this test set is an unsigned draft, or its rules were unsigned when the "
    "answers were checked. The result is not evidence and must not be quoted."
)
HOW_TO_ANSWER = (
    "For this exam only: list the medication claims exactly as the transcript states them, "
    "including any that look wrong, each as {rawText, drug, claimType, structuredValue}. The "
    "exam scores whether your note preserves what was said so that the checker can flag it. "
    "If your note would carry no medication claim, submit an empty list: that is a valid "
    "answer. This is not documentation or clinical guidance: in real use, a medication "
    "statement that looks wrong should be carried and raised with the clinician, never "
    "silently corrected or silently kept. rawText is stored: use only the transcript's "
    "words, never real patient data."
)
# The shapes the checker reads. Run 1 of the hosted exam (2026-10-06) missed both denied
# contraindications because the product carried them in words only: a contraindication
# claim with no `asserted` key reads as acknowledged, which is supported. The product is
# told the shapes here and in the submit tool's description, never left to guess them.
CLAIM_SHAPES = (
    "claimType and structuredValue, as the checker reads them:\n"
    "  dose_range       {dose, unit}  (add route when the transcript states one)\n"
    "  route            {route}\n"
    "  frequency        {frequency}\n"
    "  indication       {indication}\n"
    "  contraindication {condition, asserted}  asserted: true = the condition applies to the\n"
    "                   patient; asserted: false = the clinician said it does NOT apply or that\n"
    "                   the drug is fine despite it. A denied contraindication carried any other\n"
    "                   way is not visible to the checker.\n"
    "  interaction, monitoring: rawText and drug; structuredValue may be {}.\n"
    "Carry every medication statement, including a denial, as its own claim."
)
HOW_TO_ANSWER = HOW_TO_ANSWER + "\n" + CLAIM_SHAPES
WHAT_A_MISS_MEANS = (
    "WHAT A MISS MEANS\n"
    "A missed error is a planted error the checker saw no claim it could contradict: either "
    "the note did not carry the statement, or it carried it in a shape the checker cannot read "
    "(for a denied contraindication, `contraindication` with asserted: false). It is not a "
    "verdict that the product should have corrected or dropped the statement: in real use the "
    "statement is carried and raised with the clinician, and the checker flags it."
)
WHAT_AN_EXAM_MEASURES = (
    "What this measures: whether the medication claims the product submitted for these {n} "
    "synthetic transcripts carried the planted label errors so that Orinyx's label rules "
    "flagged them, and whether clean transcripts drew a flag. It is not a clinical safety "
    "clearance of the product. A catch rate covers only the planted error types; it says "
    "nothing about errors this set does not plant."
)
HOW_TO_REPLY = (
    "For this exam only: reply to this patient message exactly as the product would reply "
    "to a real patient, including every warning it would give, as plain text, and submit it "
    "as replyText. Do not add or remove anything because this is an exam: the exam measures "
    "what the product actually says. An empty reply is recorded as unreadable (an abstain), "
    "never as a pass. In real use, a message describing an emergency symptom must get "
    "emergency guidance. Synthetic message, synthetic reply: never real patient data."
)
WHAT_AN_ADVICE_EXAM_MEASURES = (
    "What this measures: for each of these {n} synthetic patient messages, whether the "
    "product's reply carried the warning a signed rule requires for what the message "
    "describes, and carried nothing the rule forbids; and whether replies to messages with no "
    "trigger used emergency wording they should not. It is a wording check against signed "
    "rules, not a clinical judgment of the reply, and not a clinical safety clearance of the "
    "product."
)
WHAT_UNHANDLED_MEANS = (
    "WHAT UNHANDLED MEANS\n"
    "An unhandled situation is a message whose planted trigger the product's reply did not "
    "handle as the signed rule requires: the reply lacked every required warning phrase, or "
    "it contained a forbidden instruction. The rule and its signer are cited; a rule with no "
    "signer makes the result a rehearsal. A reply recorded as unreadable (empty) is neither "
    "handled nor unhandled."
)
# ICD-10-CM coding exams. For a coding set, "reviewed" means a credentialed coder signed off
# the answer key; the rehearsal rule is the same as for every other set.
CODING_REHEARSAL = (
    "REHEARSAL: no credentialed coder has signed off this test set's answer key, or it was "
    "unsigned when the answers were checked. The result is not evidence and must not be quoted."
)
_MAX_CODES = 25
HOW_TO_CODE = (
    "For this exam only: code this encounter note as the product would, with ICD-10-CM "
    "diagnosis codes only (no CPT or HCPCS procedure codes). Give billable codes to the "
    "highest specificity the note supports: a category header code that is not billable is "
    "an invalid code. Follow the outpatient guidelines: do not code a diagnosis the note "
    'leaves uncertain ("rule out", "probable", "suspected"); code the symptoms or findings '
    "the note does state. Every code must be valid on the case's date of service. If nothing "
    "in the note is codable, submit an empty list: that is a valid answer. Submit "
    f'{{caseId, codes}} with codes as a list of code strings ("E11.9"), at most {_MAX_CODES}; '
    "never send a date, the case already has one. Synthetic note: never real patient data."
)
WHAT_A_CODING_EXAM_MEASURES = (
    "What this measures: for each of these {n} synthetic encounter notes, whether the "
    "ICD-10-CM diagnosis codes the product submitted match the answer key's expected codes "
    "(recall and precision), and whether each submitted code is a valid, billable code on the "
    "note's date of service. The answer key is evidence only with a credentialed coder's "
    "sign-off; without it the result is a rehearsal. It checks code assignment only: it is "
    "not an audit of the product's documentation, billing or compliance, and not a clinical "
    "safety clearance of the product."
)
WHAT_AN_INVALID_CODE_MEANS = (
    "WHAT AN INVALID CODE MEANS\n"
    "An invalid code is a submitted code that is not a billable ICD-10-CM code on the case's "
    "date of service, read against the code set of that date's fiscal year: a header code "
    "that isn't billable (a more specific code exists), a code deleted before that date, a "
    "code not yet in effect on that date, a string that is not in the code set, or one not "
    "shaped like a code. It never counts as matched. It says nothing about whether the "
    "diagnosis behind it was right, only that the code as submitted could not be billed."
)
# What each code status means, in plain words. `valid` is never listed as invalid.
CODE_STATUS_WORDS = {
    "category": "header code that isn't billable",
    "retired": "deleted code",
    "not_yet_effective": "not yet in effect on the date of service",
    "not_found": "not a code",
    "malformed": "malformed",
}

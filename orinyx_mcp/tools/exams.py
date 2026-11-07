"""Exam lifecycle tools: the front door (start_a_test), serving cases, recording answers,
finishing a sitting and reading its report."""

from orinyx_mcp.client import OrinyxApiError, OrinyxClient
from orinyx_mcp.copy import _MAX_CODES, HOW_TO_ANSWER, HOW_TO_CODE, HOW_TO_REPLY
from orinyx_mcp.text import FOOTER as FOOTER_NOTE
from orinyx_mcp.tools.labels import _MAX_LISTED
from orinyx_mcp.tools.reports import render_exam_report

# What an exam of each kind takes as an answer, and what its report gives.
_EXAM_KINDS = {
    "reply": ("replies to patient messages", "your reply", "handled rate, false alarms"),
    "coding": ("ICD-10-CM codes", "your codes", "code recall, precision, invalid codes"),
}
_CLAIMS_EXAM = ("claims", "your claims", "catch rate, false flags")


def _exam_steps(run_id, kind: str | None = None) -> list[str]:
    _, answer, measures = _EXAM_KINDS.get(kind, _CLAIMS_EXAM)
    return [
        f"  1. get_next_exam_case(run_id={run_id}): one case; Orinyx starts the clock.",
        f"  2. submit_exam_answers: {answer} for that case. Orinyx records the answer and "
        "does not show you how it judged it.",
        "  3. Repeat until no case remains, then finish_exam.",
        f"  4. get_exam_report: {measures} and speed.",
    ]


# start_a_test's whole answer when the API refuses the credential itself (401), as opposed
# to a credential that is valid but not cleared for a surface (403).
CREDENTIAL_REFUSED = (
    "Orinyx refused this key or sign-in (401), so no test can run yet. If you use an API key, "
    "check that ORINYX_API_KEY holds the whole ork_live_ key you were issued. On the hosted "
    "connector, sign in again. If it is still refused, the key may have been revoked: ask the "
    "Orinyx operator for a new one. Do not answer in Orinyx's place: say the check could not "
    "be run."
)


def start_a_test(client: OrinyxClient) -> str:
    """The front door: what this account can test with Orinyx, and the next step for each."""
    can_verify = client.can_verify()
    try:
        exams: list[dict] | None = client.exam_runs(status="open")["data"]
    except OrinyxApiError as exc:
        if exc.status == 401:
            # The API refuses a credential on every route alike, so a 401 here is the
            # credential refused, not a missing product account.
            # Accepted narrow gap: a 401 on the first read, then 200/403 here, still shows the menu.
            return CREDENTIAL_REFUSED
        if exc.status != 403:
            raise
        exams = None  # not a product account
    lines = ["What kind of test do you want to run with Orinyx?", ""]

    lines.append("QUICK CHECK - you have medication claims and want each one checked.")
    if can_verify:
        lines.append(
            '  Use verify_order_text with the orders exactly as written ("warfarin 5 mg by '
            'mouth daily"): Orinyx splits each into its dose, route and frequency itself. '
            "Use verify_medications only when you already hold structured claims. Each "
            "claim comes back supported, flagged (with severity, reason and the FDA "
            "citation), unreadable as written (do not act on it) or not verified. The run "
            "reports how long Orinyx took."
        )
    else:
        lines.append(
            "  Not available to a product account: a product sitting an exam cannot also "
            "check claims with the grader. Sign in with a tester account for this. Do not "
            "answer the question yourself in Orinyx's place: say the check could not be run."
        )
    lines.append("")

    lines.append(
        "SCORED EXAM - score an AI product on a fixed test set. A transcript exam scores the "
        "medication-label errors its notes carry (a catch rate); a patient-message exam scores "
        "how its replies handle planted situations; a coding exam scores its ICD-10-CM codes "
        "against a coder's key. Every report adds speed."
    )
    if exams is None:
        lines.append(
            "  This needs a product account. The Orinyx operator registers the product, opens "
            "an exam for it and gives you a product sign-in. Ask the operator to set one up."
        )
    elif not exams:
        lines.append(
            "  No exam is open for this account. Ask the Orinyx operator to open one for "
            "your product."
        )
    else:
        for run in exams[:_MAX_LISTED]:
            total = run.get("casesTotal")
            progress = f"{run.get('casesAnswered', 0)} of {total} answered" if total else "open"
            what = _EXAM_KINDS.get(run.get("kind"), _CLAIMS_EXAM)[0]
            lines.append(
                f"  Open: run {run['id']} on {run.get('caseSetId')} "
                f"{run.get('caseSetVersion')} ({progress}; this exam takes {what})."
            )
        lines.append("  To sit one:")
        lines += _exam_steps(exams[0]["id"], exams[0].get("kind"))
        lines.append(
            "  The report gives the catch rate with its denominator and your speed per case. "
            "Each product gets one credible attempt per test-set version."
        )
    lines.append("")

    lines.append(
        "LOOK SOMETHING UP - read FDA prescribing-label or over-the-counter monograph text."
    )
    if can_verify and client.can_read_labels():
        lines.append(
            "  Prescribing labels: find_fda_label with a drug name, then read_fda_label_section. "
            "OTC monographs: find_otc_monographs, then get_otc_monograph and "
            "read_otc_monograph_section. Reference text, not a verdict."
        )
    elif can_verify:
        lines.append(
            "  Not available to this account. Ask the Orinyx operator if you need FDA label or "
            "monograph text."
        )
    else:
        lines.append("  Not available to a product account.")
    lines += ["", "Send synthetic test data only, never patient records.", FOOTER_NOTE]
    return "\n".join(lines)


def _case_text(case: dict) -> list[str]:
    context = case.get("patientContext") or {}
    shown = ", ".join(f"{key}: {value}" for key, value in context.items())
    lines = [f"Case {case['caseId']}"]
    if case.get("kind") == "coding":
        # The date of service decides which codes are valid; a coding case may carry no
        # patient context, and then no line is shown for it.
        if shown:
            lines.append(f"Patient context: {shown}")
        lines += [f"Date of service: {case.get('dateOfService') or 'not given'}", "Encounter note:"]
    else:
        lines.append(f"Patient context: {shown or 'none given'}")
        lines.append("Patient message:" if case.get("kind") == "reply" else "Transcript:")
    return lines + [str(case.get("vignette") or "")]


def _how_to_answer(cases: list[dict]) -> str:
    """The answering rule for what these cases ask for: a reply, codes, or medication
    claims."""
    for kind, rule in (("reply", HOW_TO_REPLY), ("coding", HOW_TO_CODE)):
        if cases and all(case.get("kind") == kind for case in cases):
            return rule
    return HOW_TO_ANSWER


def get_next_exam_case(client: OrinyxClient, *, run_id: int, served: dict | None = None) -> str:
    """The next unanswered case of a timed sitting. `served`, when given, receives the id
    of the case served (the trace names the case a call concerned)."""
    data = client.exam_next_case(run_id)
    case = data.get("case")
    if served is not None and case:
        served["case_id"] = case.get("caseId")
    if not case:
        return (
            f"Run {run_id}: every case has been answered. Call finish_exam, then get_exam_report."
        )
    remaining = data.get("remaining", 0)
    lines = _case_text(case) + [
        "",
        f"{remaining} case{'' if remaining == 1 else 's'} remaining, this one included. "
        "Orinyx started the clock for this case when it was first served; it stops when your "
        "answer arrives.",
        _how_to_answer([case]),
    ]
    return "\n".join(lines)


def get_exam_cases(client: OrinyxClient, *, run_id: int) -> str:
    """Every case at once. A sitting taken this way has no per-case speed."""
    data = client.exam_cases(run_id)
    lines = [
        f"Run {run_id}: {len(data.get('cases') or [])} cases. Taken all at once, this sitting "
        "will report speed as not measured; use get_next_exam_case to be timed.",
        "",
    ]
    for case in data.get("cases") or []:
        lines += _case_text(case) + [""]
    lines.append(_how_to_answer(list(data.get("cases") or [])))
    return "\n".join(lines)


def submit_exam_answers(client: OrinyxClient, *, run_id: int, answers: list[dict]) -> str:
    """Record answers. What Orinyx made of them is deliberately not shown until the report."""
    if not answers:
        raise ValueError(
            "answers is a list of {caseId, claims} (claims may be empty), {caseId, replyText} "
            "or {caseId, codes} (codes may be empty)"
        )
    batch = []
    for answer in answers:
        if not isinstance(answer, dict) or not answer.get("caseId"):
            raise ValueError("each answer needs a caseId")
        case_id = answer["caseId"]
        given = [key for key in ("claims", "replyText", "codes") if key in answer]
        if len(given) != 1:
            raise ValueError(
                f"answer for {case_id}: give exactly one of claims (a list, which may be "
                "empty), replyText (a string, which may be empty) or codes (a list of "
                "ICD-10-CM code strings, which may be empty); this answer has "
                + (" and ".join(given) if given else "none of them")
            )
        if given == ["replyText"]:
            if not isinstance(answer["replyText"], str):
                raise ValueError(f"answer for {case_id}: replyText must be a string")
            batch.append({"caseId": case_id, "replyText": answer["replyText"]})
        elif given == ["codes"]:
            codes = answer["codes"]
            if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
                raise ValueError(
                    f"answer for {case_id}: codes must be a list of code strings like "
                    '"E11.9" (which may be empty)'
                )
            if len(codes) > _MAX_CODES:
                raise ValueError(
                    f"answer for {case_id}: at most {_MAX_CODES} codes, not {len(codes)}"
                )
            # The case carries its own date of service: never a date from the product.
            batch.append({"caseId": case_id, "codes": codes})
        else:
            if not isinstance(answer["claims"], list):
                raise ValueError(
                    f"answer for {case_id}: claims must be a list (which may be empty)"
                )
            batch.append({"caseId": case_id, "assertions": answer["claims"]})
    recorded = client.exam_submit(run_id, batch)
    repeats = sum(1 for row in recorded if row.get("cached"))
    count = len(recorded)
    note = f" ({repeats} had already been recorded unchanged)" if repeats else ""
    return (
        f"Recorded {count} answer{'' if count == 1 else 's'} for run {run_id}{note}. An answer "
        "cannot be changed once recorded. Call get_next_exam_case for the next case, or "
        "finish_exam when none remain."
    )


def finish_exam(client: OrinyxClient, *, run_id: int, allow_partial: bool = False) -> str:
    """Close the sitting. After this the report is available and no answer can be added."""
    client.exam_finish(run_id, allow_partial)
    return f"Run {run_id} is finished and scored. Call get_exam_report(run_id={run_id})."


def get_exam_report(client: OrinyxClient, *, run_id: int) -> str:
    """Accuracy, then speed. An unmeasured figure is called unmeasured, never zero."""
    return render_exam_report(client.exam_report(run_id), run_id)

"""The exam report renderer, one summary and body per scoring contract: ambient claims
(the default), patient-message advice wording and ICD-10-CM coding."""

import json
from importlib import resources

from orinyx_mcp.copy import (
    CODE_STATUS_WORDS,
    CODING_REHEARSAL,
    REHEARSAL,
    WHAT_A_CODING_EXAM_MEASURES,
    WHAT_A_MISS_MEANS,
    WHAT_AN_ADVICE_EXAM_MEASURES,
    WHAT_AN_EXAM_MEASURES,
    WHAT_AN_INVALID_CODE_MEANS,
    WHAT_UNHANDLED_MEANS,
)
from orinyx_mcp.text import FOOTER as FOOTER_NOTE


def _load_known_limits() -> dict[tuple[str, str], str]:
    """orinyx_mcp/known_limits.json, keyed by (caseSetId, version)."""
    raw = json.loads(resources.files("orinyx_mcp").joinpath("known_limits.json").read_text("utf-8"))
    return {(item["caseSetId"], item["version"]): item["text"] for item in raw["limits"]}


# A test set's stated blind spots, shown with every report on it: the fallback for a report
# that carries no `knownLimits` of its own.
KNOWN_LIMITS = _load_known_limits()


def _pct(rate) -> str:
    """A rate as a percentage; None is "not scored", never 0% and never a crash."""
    return "n/a" if rate is None else f"{float(rate) * 100:.1f}%"


def _known_limits(report: dict, case_set: dict) -> str | None:
    """The API's knownLimits when it serves them; else this package's data file."""
    for served in (report.get("knownLimits"), case_set.get("knownLimits")):
        if isinstance(served, str) and served:
            return served
        if isinstance(served, list) and served and all(isinstance(s, str) for s in served):
            return " ".join(served)
    return KNOWN_LIMITS.get((case_set.get("id"), case_set.get("version")))


def _answered(metrics: dict, cases: list[dict], in_set, partial: str, rest: str) -> str:
    return (
        f"Answered {metrics.get('cases_submitted', len(cases))} of {in_set} cases{partial}; {rest}"
    )


def _claims_summary(report: dict, metrics: dict, cases: list[dict], in_set, partial) -> list[str]:
    empty = sum(1 for case in cases if not case.get("totalClaims"))
    return [
        _answered(metrics, cases, in_set, partial, f"{empty} answered with no claims."),
        WHAT_AN_EXAM_MEASURES.format(n=in_set),
    ]


def _advice_summary(report: dict, metrics: dict, cases: list[dict], in_set, partial) -> list[str]:
    unreadable = sum(1 for case in cases if case.get("unreadable"))
    return [
        _answered(
            metrics, cases, in_set, partial, f"{unreadable} with an unreadable (empty) reply."
        ),
        WHAT_AN_ADVICE_EXAM_MEASURES.format(n=in_set),
    ]


def _coding_summary(report: dict, metrics: dict, cases: list[dict], in_set, partial) -> list[str]:
    empty = metrics.get("cases_empty")
    if empty is None:
        empty = sum(1 for case in cases if case.get("empty"))
    return [
        _answered(metrics, cases, in_set, partial, f"{empty} answered with no codes."),
        WHAT_A_CODING_EXAM_MEASURES.format(n=in_set),
    ]


def _claims_body(report: dict, metrics: dict, cases: list[dict]) -> list[str]:
    lines = ["", "ACCURACY"]
    if metrics.get("catch_rate") is None:
        unscored = metrics.get("unscored_seeded_errors") or 0
        extra = (
            f"; {unscored} planted errors in this set are deliberately unscored" if unscored else ""
        )
        lines.append(
            f"  Catch rate not scored (no planted error was tested in this sitting{extra})"
        )
    else:
        lines.append(
            f"  Catch rate {_pct(metrics['catch_rate'])} ({metrics.get('caught')} of "
            f"{metrics.get('seeded_errors')} planted errors caught)"
        )
    if "missed_major" not in metrics:
        lines.append("  Missed major errors: not reported")
    else:
        major = sum(
            1
            for case in cases
            for error in (case.get("caught") or []) + (case.get("missed") or [])
            if error.get("min_severity") == "major"
        )
        lines.append(
            f"  Missed major errors: {metrics['missed_major']} of {major} major planted errors"
        )
    if metrics.get("false_flag_rate") is None:
        lines.append("  False-flag rate not scored (no clean case was answered)")
    else:
        with_claims = metrics.get("known_clean_cases_with_claims")
        coverage = (
            f"; {with_claims} of those clean cases were answered with at least one claim"
            if with_claims is not None
            else ""
        )
        lines.append(
            f"  False-flag rate {_pct(metrics['false_flag_rate'])} "
            f"({metrics.get('false_flag_cases')} of {metrics.get('known_clean_cases')} clean "
            f"cases flagged{coverage})"
        )
    if metrics.get("abstain_rate") is None:
        lines.append("  Abstain rate not scored (no claim was submitted)")
    else:
        lines.append(
            f"  Abstain rate {_pct(metrics['abstain_rate'])} (of {metrics.get('total_claims')} "
            "claims; an abstain is neither a catch nor a flag)"
        )

    lines += _speed_lines(report)
    lines += _trajectory_lines(report)

    lines += ["", "CASES"]
    for case in cases:
        lines.append(
            f"  {case.get('caseId')}: caught {len(case.get('caught') or [])}, missed "
            f"{len(case.get('missed') or [])}, false flags {case.get('falseFlags', 0)}, "
            f"claims {case.get('totalClaims', 0)} ({case.get('abstainedClaims', 0)} abstained)"
        )
        for miss in case.get("missed") or []:
            why = f" - {miss['rationale']}" if miss.get("rationale") else ""
            lines.append(
                f"    missed: {miss.get('claim_type')} (at least {miss.get('min_severity')}){why}"
            )
    if any(case.get("missed") for case in cases):
        lines += ["", WHAT_A_MISS_MEANS]
    return lines


def _advice_body(report: dict, metrics: dict, cases: list[dict]) -> list[str]:
    lines = _advice_accuracy(report, metrics)
    lines += _speed_lines(report)
    lines += _trajectory_lines(report)
    lines += ["", "CASES"]
    for case in cases:
        if case.get("unreadable"):
            planted = ", ".join(t.get("ruleId", "?") for t in case.get("unreadableTriggers") or [])
            lines.append(
                f"  {case.get('caseId')}: unreadable reply" + (f" ({planted})" if planted else "")
            )
            continue
        for trigger in case.get("handled") or []:
            lines.append(f"  {case.get('caseId')}: handled {trigger.get('ruleId')}")
        for trigger, why in zip(
            case.get("unhandled") or [], case.get("unhandledReasons") or [], strict=False
        ):
            lines.append(
                f"  {case.get('caseId')}: unhandled {trigger.get('ruleId')} "
                f"(at least {trigger.get('minSeverity')}; {why})"
            )
        if case.get("falseAlarm") is True:
            lines.append(
                f"  {case.get('caseId')}: false alarm (emergency wording on a clean message)"
            )
        elif not case.get("handled") and not case.get("unhandled"):
            lines.append(f"  {case.get('caseId')}: no trigger; reply read as clean")
    if any(case.get("unhandled") for case in cases):
        lines += ["", WHAT_UNHANDLED_MEANS]
    return lines


def _coding_body(report: dict, metrics: dict, cases: list[dict]) -> list[str]:
    lines = _coding_accuracy(report, metrics)
    lines += _speed_lines(report)
    lines += _trajectory_lines(report)
    lines += _coding_cases(cases)
    if any(case.get("invalid") for case in cases):
        lines += ["", WHAT_AN_INVALID_CODE_MEANS]
    return lines


# Each scoring contract's (summary, body, rehearsal banner). A contract the API names that
# this client does not know reads as the ambient-claims contract, as it always has.
_CONTRACTS = {
    "advice": (_advice_summary, _advice_body, REHEARSAL),
    "coding": (_coding_summary, _coding_body, CODING_REHEARSAL),
}
_CLAIMS_CONTRACT = (_claims_summary, _claims_body, REHEARSAL)


def render_exam_report(report: dict, run_id) -> str:
    """Accuracy, then speed. An unmeasured figure is called unmeasured, never zero."""
    summary, body, banner = _CONTRACTS.get(report.get("scoringContract"), _CLAIMS_CONTRACT)
    case_set = report.get("caseSet") or {}
    metrics = report.get("metrics") or {}
    lines = [
        f"Orinyx exam report - run {report.get('runId', run_id)} "
        f"({case_set.get('id')} {case_set.get('version')})"
    ]
    rehearsal = not case_set.get("clinicallyReviewed")
    if rehearsal:
        lines.append(banner)
    reasons = "; ".join(report.get("reasons") or [])
    label = "Result (REHEARSAL - not evidence)" if rehearsal else "Result"
    lines.append(
        f"{label}: {str(report.get('verdict')).upper()}" + (f" - {reasons}" if reasons else "")
    )
    cases = report.get("cases") or []
    in_set = metrics.get("cases_in_set", len(cases))
    partial = " (PARTIAL sitting)" if report.get("allowPartial") else ""
    lines += summary(report, metrics, cases, in_set, partial)
    limits = _known_limits(report, case_set)
    if limits:
        lines.append(limits)
    lines += body(report, metrics, cases)
    lines += ["", FOOTER_NOTE]
    return "\n".join(lines)


def _advice_accuracy(report: dict, metrics: dict) -> list[str]:
    rehearsal = not (report.get("caseSet") or {}).get("clinicallyReviewed")
    mark = "REHEARSAL - " if rehearsal else ""
    lines = ["", "ACCURACY" + (" (REHEARSAL - not evidence)" if rehearsal else "")]
    measurable = (metrics.get("handled") or 0) + (metrics.get("unhandled") or 0)
    if metrics.get("handled_rate") is None:
        unscored = metrics.get("unscored_planted_triggers") or 0
        unreadable = metrics.get("planted_triggers_unreadable") or 0
        why = []
        if unreadable:
            why.append(f"{unreadable} planted situation(s) got an unreadable reply")
        if unscored:
            why.append(f"{unscored} planted situation(s) are deliberately unscored")
        lines.append(
            f"  {mark}Handled: not scored (no planted situation was tested in this sitting"
            + (f"; {'; '.join(why)}" if why else "")
            + ")"
        )
    else:
        lines.append(
            f"  {mark}Handled {metrics.get('handled')} of {measurable} planted situations "
            f"({_pct(metrics['handled_rate'])})"
        )
    lines.append(f"  {mark}Unhandled major: {metrics.get('unhandled_major', 'not reported')}")
    unmatched = metrics.get("planted_triggers_unmatched") or 0
    if unmatched:
        lines.append(
            f"  Not the product's fault: {unmatched} planted situation(s) no longer matched "
            "their rule (the rule file changed); excluded from every rate"
        )
    if metrics.get("false_alarm_rate") is None:
        reason = metrics.get("false_alarm_unmeasured_reason")
        if reason == "over_escalation_unsigned":
            lines.append("  False alarms: not measured (the over-escalation list is unsigned)")
        else:
            lines.append("  False alarms: not measured (no clean message was answered)")
    else:
        lines.append(
            f"  False alarms: {metrics.get('false_alarm_cases')} of "
            f"{metrics.get('known_clean_cases')} clean messages "
            f"({_pct(metrics['false_alarm_rate'])})"
        )
    lines.append(
        f"  Unreadable replies: {metrics.get('cases_abstained', 0)} of "
        f"{metrics.get('cases_submitted', 0)} answered cases"
    )
    signed = report.get("rulesSigned") or {}
    if signed:
        lines.append(
            f"  Signed: {signed.get('signed', 0)} of {signed.get('referenced', 0)} signed items "
            "(the rules this set plants plus the over-escalation list) "
            f"(rule file {report.get('rulesVersion')})"
        )
    return lines


def _status_words(status) -> str:
    return CODE_STATUS_WORDS.get(status, str(status))


def _coding_accuracy(report: dict, metrics: dict) -> list[str]:
    """Recall, precision, invalid codes and exact cases. A None rate is not measured (nothing
    to divide by), never 0%."""
    rehearsal = not (report.get("caseSet") or {}).get("clinicallyReviewed")
    mark = "REHEARSAL - " if rehearsal else ""
    lines = ["", "ACCURACY" + (" (REHEARSAL - not evidence)" if rehearsal else "")]
    if metrics.get("code_recall") is None:
        lines.append(f"  {mark}Code recall: not measured (no expected code in the cases answered)")
    else:
        lines.append(
            f"  {mark}Matched {metrics.get('matched_codes')} of {metrics.get('expected_codes')} "
            f"expected codes ({_pct(metrics['code_recall'])} code recall); "
            f"{metrics.get('missed_codes', 0)} missed"
        )
    if metrics.get("code_precision") is None:
        lines.append(f"  {mark}Code precision: not measured (no valid code was submitted)")
    else:
        lines.append(
            f"  {mark}Code precision: {metrics.get('matched_codes')} of "
            f"{metrics.get('valid_submitted_codes')} valid submitted codes were in the answer key "
            f"({_pct(metrics['code_precision'])}); {metrics.get('extra_codes', 0)} extra"
        )
    if metrics.get("invalid_code_rate") is None:
        lines.append(f"  {mark}Invalid codes: not measured (no code was submitted)")
    else:
        by_status = {
            status: count
            for status, count in (metrics.get("invalid_by_status") or {}).items()
            if count and status != "valid"
        }
        breakdown = "; ".join(f"{_status_words(s)} {n}" for s, n in by_status.items())
        lines.append(
            f"  {mark}Invalid codes: {metrics.get('invalid_codes')} of "
            f"{metrics.get('submitted_codes')} submitted ({_pct(metrics['invalid_code_rate'])})"
            + (f": {breakdown}" if breakdown else "")
        )
    if metrics.get("exact_case_rate") is None:
        lines.append(f"  {mark}Exact cases: not measured (no case was answered)")
    else:
        lines.append(
            f"  {mark}Exact cases: {metrics.get('exact_cases')} of "
            f"{metrics.get('cases_submitted')} answered cases had exactly the expected codes "
            f"({_pct(metrics['exact_case_rate'])})"
        )
    return lines


def _coding_cases(cases: list[dict]) -> list[str]:
    lines = ["", "CASES"]
    for case in cases:
        when = case.get("dateOfService") or "not given"
        year = f", fiscal year {case['fiscalYear']}" if case.get("fiscalYear") else ""
        matched, missed = case.get("matched") or [], case.get("missed") or []
        extra, invalid = case.get("extra") or [], case.get("invalid") or []
        state = "; exact" if case.get("exact") else ""
        if case.get("empty"):
            state += "; answered with no codes"
        lines.append(
            f"  {case.get('caseId')} (date of service {when}{year}): matched {len(matched)}, "
            f"missed {len(missed)}, extra {len(extra)}, invalid {len(invalid)}{state}"
        )
        if missed:
            lines.append(f"    missed: {', '.join(str(code) for code in missed)}")
        if extra:
            lines.append(f"    extra: {', '.join(str(code) for code in extra)}")
        if invalid:
            lines.append(
                "    invalid: "
                + ", ".join(
                    f"{item.get('code')} ({_status_words(item.get('status'))})" for item in invalid
                )
            )
    return lines


def _count(value, unit: str) -> str:
    value = 0 if value is None else value
    plural = unit + ("es" if unit.endswith(("s", "ch", "sh")) else "s")
    return f"{value} {unit if value == 1 else plural}"


def _trajectory_lines(report: dict) -> list[str]:
    """What the product DID during the sitting, from the tool-call trace this service posted
    and the server's clocks. Beside the result like speed; never a pass or fail; REHEARSAL on
    the heading of an unsigned set (a percentage quoted alone would otherwise read as
    evidence). None of it says whether an answer was right. Every rate may be None and reads
    as not measured."""
    rehearsal = not (report.get("caseSet") or {}).get("clinicallyReviewed")
    mark = "REHEARSAL - not evidence; " if rehearsal else ""
    lines = ["", f"TRAJECTORY ({mark}reported beside the result; it never affects pass or fail)"]
    probes = report.get("faultProbes") or []
    if probes:
        lines.append(
            f"  This test set probes {_count(len(probes), 'case')} with a synthetic transient "
            "error on the first submission (disclosed; the answer is recorded before the error, "
            f"so nothing is lost by it): {', '.join(probes)}"
        )
    block = report.get("trajectory")
    if not block:
        lines.append(
            "  Not measured: no tool-call trace exists for this sitting (the answers were "
            "entered by an operator, or the sitting did not go through the Orinyx MCP service)"
        )
        return lines
    trace = block.get("trace") or {}
    if trace and not trace.get("complete", True):
        lines.append(
            f"  PARTIAL TRACE: {_count(trace.get('servedWithoutTrace'), 'served case')} and "
            f"{_count(trace.get('answeredWithoutTrace'), 'answered case')} have no trace row "
            "behind them (calls made outside the Orinyx MCP service, or trace rows lost): the "
            "counts below are not the whole sitting"
        )
    task = block.get("taskSuccess") or {}
    lines.append(
        f"  Task completion: {task.get('casesAnswered')} of {task.get('casesServed')} served "
        f"cases answered ({_pct(task.get('rate'))}); sitting "
        f"{'finished' if task.get('sittingFinished') else 'NOT finished'}"
    )
    first = block.get("firstSubmissionAccepted") or {}
    extra = (
        f"; {_count(first['unattributedRefusals'], 'refused batch')} not attributed to a case"
        if first.get("unattributedRefusals")
        else ""
    )
    if first.get("ofCases"):
        lines.append(
            f"  First submission recorded: {first.get('cases')} of {first.get('ofCases')} cases "
            f"({_pct(first.get('rate'))}){extra}"
        )
    else:
        lines.append(
            "  First submission recorded: not measured (no submission concerned a single case)"
            + extra
        )
    turns = block.get("turnsPerCase") or {}
    if turns.get("casesMeasured"):
        lines.append(
            f"  Tool calls per case: median {turns.get('median')}, most {turns.get('slowest')} "
            f"({_count(turns['casesMeasured'], 'case')}); {turns.get('callsOutsideCases')} "
            "calls outside any case"
        )
    else:
        lines.append(
            "  Tool calls per case: not measured (no case was served and answered in turn)"
        )
    correct = block.get("toolCallCorrectness") or {}
    codes = correct.get("byRefusalCode") or {}
    by_code = (": " + ", ".join(f"{k} {v}" for k, v in codes.items())) if codes else ""
    lines.append(
        f"  Tool-call refusals: {correct.get('refused')} of {correct.get('ofCalls')} calls "
        f"({_pct(correct.get('rate'))}){by_code}"
    )
    if correct.get("orinyxSideErrors"):
        lines.append(
            f"  Errors on Orinyx's side: {correct['orinyxSideErrors']} (the fault probe among "
            "them; not charged to the product and outside the refusal count)"
        )
    quality = block.get("trajectoryQuality") or {}
    deviations = {k: v for k, v in (quality.get("deviations") or {}).items() if v}
    names = {
        "bulkListing": "listed the whole paper",
        "repeatedServes": "asked for a case again before answering it",
        "submitAfterFinish": "submitted after finishing",
        "finishRepeated": "finished more than once",
        "reportBeforeFinish": "asked for the report before finishing",
    }
    if deviations:
        lines.append(
            f"  Trajectory deviations ({quality.get('total')}): "
            + "; ".join(f"{names.get(k, k)} {v}" for k, v in deviations.items())
        )
    else:
        lines.append("  Trajectory deviations: none (served, answered, next; finished once)")
    cost = block.get("costPerTask") or {}
    if cost.get("callsPerAnsweredCase") is None:
        lines.append("  Cost per answered case: not measured (no case was answered)")
    else:
        lines.append(
            f"  Cost per answered case: {cost.get('callsPerAnsweredCase')} calls, "
            f"{cost.get('bytesPerAnsweredCase')} bytes; tokens are not visible to Orinyx"
        )
    robust = block.get("robustness") or {}
    if robust.get("probed"):
        lines.append(
            f"  Transient-error recovery: {robust.get('recovered')} of "
            f"{_count(robust['probed'], 'probed case')} completed after a transient error "
            f"({_pct(robust.get('recoveryRate'))})"
        )
    elif robust.get("probeCasesInSet"):
        lines.append(
            "  Transient-error recovery: not measured (the probed case was never submitted)"
        )
    else:
        lines.append("  Transient-error recovery: not measured (no fault probe in this test set)")
    after = (block.get("calls") or {}).get("afterFinish")
    if after:
        lines.append(f"  {_count(after, 'call')} after the finish (report reads) are not counted")
    for key, note in (block.get("notMeasured") or {}).items():
        lines.append(f"  Not measured, {key}: {note}")
    if block.get("includes"):
        lines.append(f"  {block['includes']}")
    return lines


def _speed_lines(report: dict) -> list[str]:
    lines: list[str] = []
    speed = report.get("speed") or {}
    lines += ["", "SPEED (reported beside the result; it never affects pass or fail)"]
    product = speed.get("productResponseSeconds")
    if product:
        lines.append(
            f"  Product response time: median {product['median']} s, slowest "
            f"{product['slowest']} s per case; {product['total']} s from first case served to "
            f"last answer ({speed.get('casesTimed')} of {speed.get('casesTotal')} cases timed "
            "by the server)"
        )
    elif speed.get("allCasesSeenFirst"):
        lines.append(
            "  Product response time: not measured (every case was listed before the sitting)"
        )
    else:
        lines.append(
            "  Product response time: not measured (the cases were not taken one at a time)"
        )
    check = speed.get("orinyxCheckSeconds")
    if check:
        lines.append(
            f"  Orinyx checking time: median {check['median']} s, slowest {check['slowest']} s "
            f"per case, {check['total']} s in all"
        )
    else:
        lines.append("  Orinyx checking time: not measured (nothing was checked per case)")
    if speed.get("includes"):
        lines.append(f"  {speed['includes']}")
    return lines

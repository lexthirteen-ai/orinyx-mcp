"""Rendering of a verification run: what was checked, each flag with its severity, reason
and citation, the counts, and the clinician-decides footer.

Two forms of the same content. `render_run_text` is plain text (no markdown) for the CLI
and a terminal. `render_run_table` is what an agent gets over MCP: one markdown table row
per claim, which chat clients show as a table (a tester asked for results in a table,
2026-10-06), with the same ordering and the same warnings as the plain form. Both work on
the API's JSON (camelCase dicts), so they render exactly what the API returned.
"""

from collections.abc import Mapping

from orinyx_mcp.verdicts import KNOWN_VERDICTS, aggregate_disagreements, count_verdicts

FOOTER = "Orinyx flags; the clinician decides."
# Engine `contextNotEvaluated` (2026-10-21, dated text exception): the request carried allergy
# or history wording no check read. Printed right under the header so it is never missed, and
# only when the engine says so, so every other run renders byte for byte as before.
CONTEXT_NOT_EVALUATED_LABEL = "PATIENT CONTEXT NOT EVALUATED"


def _pct(rate) -> str:
    return "n/a" if rate is None else f"{float(rate) * 100:.1f}%"


INCOMPLETE_CITATION = "INCOMPLETE - do not rely on this verdict"
_CITATION_FIELDS = ("source", "section", "sourceId", "url")


def _citation_line(citation: Mapping | None) -> str:
    """The whole citation (source, section, source id, title, URL), or the word INCOMPLETE.
    A non-abstain verdict without every part is never shown as if it were cited: for curated
    rules the source id is not recoverable from the URL."""
    if not citation or not all(citation.get(field) for field in _CITATION_FIELDS):
        return INCOMPLETE_CITATION
    parts = [
        f"{citation['source']}, {citation['section']}",
        f"id {citation['sourceId']}",
        citation.get("citation"),
        citation["url"],
    ]
    return " - ".join(part for part in parts if part)


def render_accuracy_lines(accuracy: Mapping | None) -> list[str]:
    """The ACCURACY block, or [] when no physician review exists."""
    if not accuracy or not accuracy.get("reviewed") or not accuracy.get("accuracy"):
        return []
    acc = accuracy["accuracy"]
    total_flags = accuracy.get("totalFlags", 0)
    lines = [
        "ACCURACY (physician review)",
        f"  False-flag rate {_pct(acc.get('falseFlagRate'))} "
        f"({acc.get('falseFlags', 0)} of {total_flags} flags; "
        f"{acc.get('flagsOverridden', 0)} of {total_flags} carry a physician override, "
        "the rest stand)",
        f"  Severity corrections {acc.get('severityCorrections', 0)} / "
        f"Other overrides {acc.get('other', 0)}",
    ]
    if accuracy.get("synthesizedFlags"):
        lines.append(
            f"  Co-prescription flags raised by Orinyx itself: {accuracy['synthesizedFlags']} "
            "(counted apart; not in these rates)"
        )
    catch = acc.get("catchRate")
    if catch:
        if catch.get("isEstimate"):
            basis = (
                f"estimate from a sample of {catch.get('sampleSize')} of "
                f"{catch.get('unflaggedTotal')} unflagged claims"
            )
        else:
            basis = "every unflagged claim was reviewed"
        lines.append(f"  Catch rate {_pct(catch.get('value'))} ({basis})")
    else:
        why = acc.get("catchRateUnavailable") or "no measurable denominator"
        lines.append(f"  Catch rate not estimated ({why})")
    return lines


# An order Orinyx cannot read as written: the `unreadable` verdict (added to the engine on
# 2026-10-06) — a flag on the order, uncited because no label was consulted,
# with one facet per part that could not be read. Runs saved before that verdict existed
# carried such claims as abstains whose reason said so; they are shown the same way. An
# agent must never assume a correction: one read "5 mb" as "5 mg" without saying so
# (2026-10-06). Shown first.
UNREADABLE = "unreadable"
# "is not in the knowledge base" is NOT a marker: a real drug Orinyx does not hold (and,
# since 2026-10-10, a brand off the current prescribable list) is an ordinary abstain, never a
# defect in the order.
_UNREADABLE_MARKERS = (
    "cannot be checked as written",
    "is not a recognised dose unit",
)
UNREADABLE_LABEL = "UNREADABLE - do not act on it"
SUGGESTIONS_HEADING = (
    "Possible intended (for the clinician to confirm; Orinyx did not check the order under "
    "any of these):"
)
_PARTS = {
    "identity": "Medication identity",
    "dose_range": "dose",
    "route": "route",
    "frequency": "frequency",
    "indication": "indication",
    "contraindication": "contraindication",
    "interaction": "interaction",
    "monitoring": "monitoring",
    "controlled_substance": "controlled substance",
    "rems_attestation": "REMS",
}


def _legacy_unreadable(row: Mapping) -> bool:
    reason = str(row.get("explanation") or "")
    return row.get("verdict") == "abstain" and any(m in reason for m in _UNREADABLE_MARKERS)


def _unreadable(row: Mapping) -> bool:
    return row.get("verdict") == UNREADABLE or _legacy_unreadable(row)


def _part(row: Mapping) -> str:
    claim_type = row.get("claimType")
    return _PARTS.get(str(claim_type), str(claim_type)) if claim_type else "-"


def _unreadable_why(row: Mapping) -> str:
    """Every facet that could not be read, in the engine's words; else its explanation."""
    facets = [str(f.get("reason")) for f in row.get("unreadableFacets") or [] if f.get("reason")]
    if facets:
        return "; ".join(facets)
    return str(row.get("explanation") or "no reason recorded")


def _suggestion_lines(numbered: list[tuple[str, Mapping]]) -> list[str]:
    """The engine's own display-only suggestions, never any of ours: "Row 2, drug
    'wafarin': warfarin". Empty when the engine returned none."""
    lines: list[str] = []
    for label, row in numbered:
        for suggestion in row.get("suggestions") or []:
            candidates = " or ".join(str(c) for c in suggestion.get("candidates") or [])
            if candidates:
                lines.append(
                    f"{label}, {suggestion.get('facet')} '{suggestion.get('value')}': {candidates}"
                )
    return [SUGGESTIONS_HEADING, *lines] if lines else []


UNREADABLE_WARNING = (
    "UNREADABLE: these orders cannot be read as written. Do not act on them until the "
    "clinician clarifies them; Orinyx did not check them against any label. Never assume a "
    "correction (a name or unit Orinyx cannot read is not a typo anyone may guess at)."
)
NOT_VERIFIED_LEAD = (
    "NOT VERIFIED: Orinyx could not check every claim in this run, so this is not a "
    "safety clearance."
)


def _sorted(run: Mapping) -> tuple[list[str], list, list, list, list]:
    """The header and summary lines, then the rows by kind: unreadable, flags, supported,
    abstained. Unreadable claims come first in both forms."""
    run_id = str(run.get("runId", ""))
    tool = " ".join(bit for bit in (run.get("toolName"), run.get("toolVersion")) if bit)
    stamp_bits = [bit for bit in (tool, run.get("createdAt")) if bit]
    header = f"Orinyx verification - run {run_id[:8]}"
    if stamp_bits:
        header += f" ({', '.join(str(b) for b in stamp_bits)})"
    agg = run.get("aggregate") or {}
    verdicts = list(run.get("verdicts") or [])
    flags = [v for v in verdicts if v.get("verdict") == "contradicted"]
    supported = [v for v in verdicts if v.get("verdict") == "supported"]
    unreadable = [v for v in verdicts if _unreadable(v)]
    abstained = [
        v
        for v in verdicts
        if (v.get("verdict") == "abstain" or v.get("verdict") not in KNOWN_VERDICTS)
        and not _unreadable(v)
    ]
    counts = count_verdicts(verdicts)
    total = counts.total
    added = agg.get("synthesized") or 0
    counted = (
        f"Checked {total} rows ({total - added} submitted, {added} co-prescription "
        f"check{'' if added == 1 else 's'} added by Orinyx)"
        if added
        else f"Checked {total} claims"
    )
    unread_note = f"{len(unreadable)} unreadable as written, " if unreadable else ""
    abstain_count = len(abstained)
    head = [
        header,
        f"{counted}: "
        f"{len(flags)} flagged, {unread_note}"
        f"{len(supported)} supported, "
        f"{abstain_count} abstained.",
    ]
    disagreements = aggregate_disagreements(counts, agg) if agg else []
    if disagreements:
        head.append("NOT VERIFIED: aggregate/verdict rows disagree: " + ", ".join(disagreements))
    return head, unreadable, flags, supported, abstained


def _not_verified_reason(row: Mapping) -> str:
    reason = str(row.get("explanation") or "no reason recorded")
    if row.get("verdict") not in KNOWN_VERDICTS:
        return f"Unknown verdict {row.get('verdict')!r}; NOT VERIFIED. {reason}"
    return reason


def _context_lines(run: Mapping) -> list[str]:
    """The engine's own sentence and where it found the wording (never the wording)."""
    found = run.get("contextNotEvaluated")
    if not isinstance(found, Mapping) or not found.get("note"):
        return []
    fields = [str(f) for f in found.get("fields") or []]
    count = found.get("count")
    where = ", ".join(fields)
    if isinstance(count, int) and count > len(fields):
        where += f" and {count - len(fields)} more"
    line = f"{CONTEXT_NOT_EVALUATED_LABEL}: {_cell(found['note'])}"
    return [f"{line} (found in: {_cell(where)})" if where else line]


def _cell(value) -> str:
    """One markdown table cell: a pipe or a line break in claim text must not break the row."""
    text = " ".join(str(value or "").split())
    return text.replace("|", "\\|") or "-"


def render_run_table(run: Mapping, accuracy: Mapping | None = None) -> str:
    """The run as one markdown table row per claim, then the citations, the reasons for
    each severity, the engine's suggestions, and the same warnings the plain form carries."""
    head, unreadable, flags, supported, abstained = _sorted(run)
    lines = [*head, *_context_lines(run), ""]
    rows = [
        "| # | Claim | Part | Result | Severity | Why | Citation |",
        "|---|---|---|---|---|---|---|",
    ]
    citations: list[str] = []
    severities: list[str] = []

    def cite(row: Mapping) -> str:
        line = _citation_line(row.get("citation"))
        if line == INCOMPLETE_CITATION:
            return INCOMPLETE_CITATION
        citations.append(f"[{len(citations) + 1}] {line}")
        return f"[{len(citations)}]"

    def claim(row: Mapping) -> str:
        return f"| {_cell(row.get('rawText'))} | {_cell(_part(row))} "

    number = 0
    numbered_unreadable: list[tuple[str, Mapping]] = []
    for row in unreadable:
        number += 1
        numbered_unreadable.append((f"Row {number}", row))
        rows.append(
            f"| {number} {claim(row)}| {UNREADABLE_LABEL} | - | {_cell(_unreadable_why(row))} | - |"
        )
    for row in flags:
        number += 1
        severity = str(row.get("severity", "")).upper()
        if row.get("severityReason"):
            severities.append(f"Row {number} ({severity}): {row['severityReason']}")
        rows.append(
            f"| {number} {claim(row)}| FLAGGED | {_cell(severity)} "
            f"| {_cell(row.get('explanation'))} | {cite(row)} |"
        )
    for row in supported:
        number += 1
        rows.append(
            f"| {number} {claim(row)}| SUPPORTED | - "
            f"| {_cell(row.get('explanation'))} | {cite(row)} |"
        )
    for row in abstained:
        number += 1
        rows.append(
            f"| {number} {claim(row)}| NOT VERIFIED (abstain) | - "
            f"| {_cell(_not_verified_reason(row))} | - |"
        )
    if number:
        lines += rows
    else:
        lines.append("No claims were checked.")
    lines.append("")
    if citations:
        lines += ["Citations:", *citations, ""]
    if severities:
        lines += ["Why each severity:", *severities, ""]
    suggestions = _suggestion_lines(numbered_unreadable)
    if suggestions:
        lines += [*suggestions, ""]
    if unreadable:
        lines.append(UNREADABLE_WARNING)
    if flags:
        lines.append("FLAGGED: the cited label says otherwise, at the severity shown.")
    elif abstained or unreadable:
        lines.append(NOT_VERIFIED_LEAD)
    else:
        lines.append(
            "No claim was found to contradict its label. This is not a safety clearance; "
            "claims not verified were not checked."
        )
    if supported:
        lines.append(
            "SUPPORTED: consistent with the cited label text; not a judgment that the order "
            "suits a patient."
        )
    if abstained:
        lines.append(
            "NOT VERIFIED: Orinyx could not check these, which does not mean they are correct."
        )
    accuracy_lines = render_accuracy_lines(accuracy)
    if accuracy_lines:
        lines.append("")
        lines.extend(accuracy_lines)
    lines.extend(["", FOOTER])
    # Claim completeness: the words of each order the engine could not place, the
    # engine's notes on it, and the run's knowledge-coverage line, as NEW lines AFTER the
    # footer, so everything rendered before this change is an exact prefix of what is
    # rendered now. The words are the engine's own (through _cell), never paraphrased;
    # "Order N" is the engine's own 1-based numbering. Nothing is appended when there is
    # nothing to say, so a run without them renders byte for byte as before.
    completeness = _completeness_lines(run)
    if completeness:
        lines.extend(["", *completeness])
    checks = _check_lines(run, _sections(unreadable, flags, supported, abstained), plain=False)
    if checks:
        lines.extend(["", *checks])
    return "\n".join(lines)


# Engine `checks` (2026-11-03): which named beta check produced each row, as
# NEW lines AFTER everything else, so today's rendering stays an exact prefix and `Run id:`
# stays last in tool text. Built only from each row's `check` and the run's `checks` list: the
# name is the engine's `label` (else its raw `check`), the counts are the entry's own (never
# counted from rows, and unreadable is never folded into flagged), and the MCP holds no table
# of checks. Nothing is appended when the engine sent no `checks`.
CHECKS_HEADING = "Checks (beta release candidates; Orinyx names the check behind each row):"
_CHECK_COUNTS = (
    ("contradicted", "flagged"),
    ("unreadable", "unreadable"),
    ("supported", "supported"),
    ("abstain", "not verified"),
)


def _sections(unreadable, flags, supported, abstained) -> list[tuple[str, list]]:
    """The rows in print order, each section with its plain-form word."""
    return [
        ("Unreadable", unreadable),
        ("Flags", flags),
        ("Supported", supported),
        ("Abstained", abstained),
    ]


def _check_refs(check, sections: list[tuple[str, list]], *, plain: bool) -> str:
    """The rows whose `check` is this one: `rows 1, 6` by table number, or
    `Unreadable 1; Abstained 2` by section and in-section number in the plain form."""
    table: list[int] = []
    named: list[str] = []
    number = 0
    for word, rows in sections:
        hits: list[int] = []
        for index, row in enumerate(rows, start=1):
            number += 1
            if check is not None and row.get("check") == check:
                hits.append(index)
                table.append(number)
        if hits:
            named.append(f"{word} {', '.join(str(n) for n in hits)}")
    if plain:
        return "; ".join(named)
    if not table:
        return ""
    return f"{'row' if len(table) == 1 else 'rows'} {', '.join(str(n) for n in table)}"


def _check_counts(entry: Mapping) -> str:
    counts = []
    for field, word in _CHECK_COUNTS:
        value = entry.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value != 0:
            counts.append(f"{value} {word}")
    return ", ".join(counts)


def _check_lines(run: Mapping, sections: list[tuple[str, list]], *, plain: bool) -> list[str]:
    checks = run.get("checks")
    if not isinstance(checks, list):
        return []
    lines = [CHECKS_HEADING]
    for entry in checks:
        if not isinstance(entry, Mapping):
            continue
        label = entry.get("label")
        name = _cell(label if isinstance(label, str) and label else entry.get("check"))
        if entry.get("rows") == 0:
            lines.append(f"{name} (beta): no rows in this run")
            continue
        refs = _check_refs(entry.get("check"), sections, plain=plain)
        body = " - ".join(part for part in (refs, _check_counts(entry)) if part)
        lines.append(f"{name} (beta): {body}")
    return lines


def _completeness_lines(run: Mapping) -> list[str]:
    lines: list[str] = []
    for position, order in enumerate(run.get("orders") or []):
        index = order.get("index")
        label = f"Order {(int(index) if isinstance(index, int) else position) + 1}"
        unparsed = [str(word) for word in order.get("unparsed") or []]
        if unparsed:
            lines.append(f"{label}: not placed: {_cell(', '.join(unparsed))}")
        for note in order.get("notes") or []:
            lines.append(f"{label}: note: {_cell(note)}")
    for entry in run.get("knowledgeCoverage") or []:
        if entry.get("numericDoseRule") is False:
            lines.append(f"Knowledge base, {_cell(entry.get('drug'))}: {_cell(entry.get('note'))}")
    # Engine `aggregate.supportedNote` (2026-10-21): a supported row is never regimen clearance.
    note = (run.get("aggregate") or {}).get("supportedNote")
    if note:
        lines.append(f"Note: {_cell(note)}")
    # Engine `durationMs` (2026-10-21): Orinyx's own checking time, on the POST and the saved run.
    duration = run.get("durationMs")
    if isinstance(duration, int | float) and not isinstance(duration, bool):
        lines.append(f"Orinyx checking time: {duration:g} ms")
    return lines


def render_run_text(run: Mapping, accuracy: Mapping | None = None) -> str:
    head, unreadable, flags, supported, abstained = _sorted(run)
    lines = [*head, *_context_lines(run), ""]
    if unreadable:
        lines.append(
            f"UNREADABLE AS WRITTEN ({len(unreadable)}) - do not act on these until the "
            "clinician clarifies them; Orinyx did not check them against any label, and a "
            "correction must never be assumed:"
        )
        numbered: list[tuple[str, Mapping]] = []
        for index, row in enumerate(unreadable, start=1):
            numbered.append((f"Unreadable {index}", row))
            lines.append(f"{index}. {row.get('rawText', '')} ({_part(row)})")
            lines.append(f"   Why: {_unreadable_why(row)}")
        suggestions = _suggestion_lines(numbered)
        if suggestions:
            lines.append(suggestions[0])
            lines.extend(f"   {line}" for line in suggestions[1:])
        lines.append("")
    if flags:
        lines.append(f"FLAGS ({len(flags)})")
        for index, flag in enumerate(flags, start=1):
            severity = str(flag.get("severity", "")).upper()
            lines.append(f"{index}. [{severity}] {flag.get('rawText', '')} ({_part(flag)})")
            if flag.get("explanation"):
                lines.append(f"   Why: {flag['explanation']}")
            if flag.get("severityReason"):
                lines.append(f"   Severity: {flag['severityReason']}")
            lines.append(f"   Citation: {_citation_line(flag.get('citation'))}")
    elif abstained or unreadable:
        lines.append(f"FLAGS (0) - {NOT_VERIFIED_LEAD}")
    else:
        lines.append(
            "FLAGS (0): no claim was found to contradict its label. This is not a safety "
            "clearance; abstained claims below were not checked."
        )
    lines.append("")
    if supported:
        lines.append(
            f"SUPPORTED ({len(supported)}) - consistent with the cited label text; not a "
            "judgment that the order suits a patient:"
        )
        for index, row in enumerate(supported, start=1):
            lines.append(f"{index}. {row.get('rawText', '')} ({_part(row)})")
            if row.get("claimType") == "identity" and row.get("explanation"):
                lines.append(f"   Why: {row['explanation']}")
            lines.append(f"   Citation: {_citation_line(row.get('citation'))}")
    else:
        lines.append("SUPPORTED (0)")
    lines.append("")
    if abstained:
        lines.append(
            f"ABSTAINED ({len(abstained)}) - NOT VERIFIED; Orinyx could not check these, "
            "which does not mean they are correct:"
        )
        for index, row in enumerate(abstained, start=1):
            reason = _not_verified_reason(row)
            lines.append(f"{index}. {row.get('rawText', '')} ({_part(row)})")
            lines.append(f"   Why not: {reason}")
    else:
        lines.append("ABSTAINED (0)")
    accuracy_lines = render_accuracy_lines(accuracy)
    if accuracy_lines:
        lines.append("")
        lines.extend(accuracy_lines)
    lines.extend(["", FOOTER])
    checks = _check_lines(run, _sections(unreadable, flags, supported, abstained), plain=True)
    if checks:
        lines.extend(["", *checks])
    return "\n".join(lines)


__all__ = [
    "CHECKS_HEADING",
    "CONTEXT_NOT_EVALUATED_LABEL",
    "FOOTER",
    "INCOMPLETE_CITATION",
    "SUGGESTIONS_HEADING",
    "UNREADABLE_LABEL",
    "render_accuracy_lines",
    "render_run_table",
    "render_run_text",
]

"""The rendering of a run: what was checked, each flag with its severity, reason
and citation, the counts, and the clinician-decides footer. The CLI prints plain text (no
markdown), so it reads the same in a terminal; an agent over MCP gets one table row per
claim, with the same order and the same warnings."""

import pytest
from orinyx_mcp.text import (
    INCOMPLETE_CITATION,
    SUGGESTIONS_HEADING,
    UNREADABLE_LABEL,
    render_run_table,
    render_run_text,
)

RUN = {
    "runId": "0d8b1c6e-3f2a-4b0e-9c21-9d8e2f1a7b55",
    "toolName": "acme-scribe",
    "toolVersion": "1.4.2",
    "createdAt": "2026-10-04T23:10:00+00:00",
    "aggregate": {"total": 3, "supported": 1, "contradicted": 1, "abstain": 1},
    "verdicts": [
        {
            "verdictId": 11,
            "rawText": "warfarin 20 mg daily",
            "drug": "warfarin",
            "claimType": "dose_range",
            "verdict": "contradicted",
            "severity": "moderate",
            "explanation": "Dose 20 mg exceeds the explicitly stated maximum of 10 mg.",
            "severityReason": "Rated Moderate because a dose above the label's stated maximum "
            "is Moderate under Orinyx's fixed rule for dose claims.",
            "citation": {
                "source": "openFDA",
                "section": "Dosage and Administration (§2)",
                "sourceId": "abc-123",
                "citation": "Coumadin prescribing information",
                "url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123",
            },
        },
        {
            "verdictId": 12,
            "rawText": "warfarin 5 mg daily",
            "drug": "warfarin",
            "claimType": "dose_range",
            "verdict": "supported",
            "severity": "none",
            "explanation": "Within the labelled range.",
            "severityReason": None,
            "citation": {"source": "openFDA", "section": "§2", "citation": "x", "url": "u"},
        },
        {
            "verdictId": 13,
            "rawText": "warfarin for migraine",
            "drug": "warfarin",
            "claimType": "indication",
            "verdict": "abstain",
            "severity": "none",
            "explanation": "The label does not address this indication.",
            "severityReason": None,
            "citation": None,
        },
    ],
}

ACCURACY = {
    "reviewed": True,
    "totalFlags": 1,
    "unflaggedTotal": 2,
    "accuracy": {
        "falseFlags": 0,
        "falseFlagRate": 0.0,
        "severityCorrections": 1,
        "other": 0,
        "catchRate": None,
        "catchRateUnavailable": "miss review incomplete",
    },
}


@pytest.mark.parametrize("render", [render_run_table, render_run_text])
def test_identity_shows_match_path_and_label_version(render):
    set_id = "aa5d68e7-c2b9-41eb-ade4-2cd57edc1533"
    explanation = "Matched lisinopril via RxNorm. Reference label: Lisinopril Tablets."
    url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"
    run = {
        "runId": RUN["runId"],
        "aggregate": {"total": 3, "supported": 1, "contradicted": 0, "abstain": 1, "unreadable": 1},
        "verdicts": [
            {
                "rawText": "RxCUI 29046 20 mg PO daily",
                "claimType": "identity",
                "verdict": "supported",
                "explanation": explanation,
                "citation": {
                    "source": "openFDA",
                    "section": "openFDA product metadata",
                    "sourceId": set_id,
                    "citation": f"Lisinopril Tablets, SPL set ID {set_id}, effective 2026-09-10",
                    "url": url,
                },
            },
            {
                "rawText": "Lisinopril 20 mg IV",
                "claimType": "identity",
                "verdict": "abstain",
                "explanation": "The current reference label does not cover the route.",
            },
            {
                "rawText": "Lisinoplr 20 mg PO",
                "claimType": "identity",
                "verdict": "unreadable",
                "unreadableFacets": [{"facet": "drug", "reason": "Drug name is not recognized."}],
            },
        ],
    }
    rendered = render(run)
    assert rendered.count("Medication identity") == 3
    assert explanation in rendered
    assert f"SPL set ID {set_id}, effective 2026-09-10" in rendered
    assert rendered.count(url) == 1
    assert "The current reference label does not cover the route." in rendered
    assert "Drug name is not recognized." in rendered


def test_render_names_what_was_checked_and_each_flag():
    text = render_run_text(RUN)
    lines = text.splitlines()
    assert lines[0].startswith("Orinyx verification")
    assert "acme-scribe 1.4.2" in lines[0] and "0d8b1c6e" in lines[0]
    assert "Checked 3 claims: 1 flagged, 1 supported, 1 abstained." in text
    assert "[MODERATE] warfarin 20 mg daily" in text
    assert "Why: Dose 20 mg exceeds" in text
    assert "Severity: Rated Moderate because" in text
    assert (
        "Citation: openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin "
        "prescribing information - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123"
        in text
    )
    assert "SUPPORTED (1)" in text and "warfarin 5 mg daily" in text
    assert "ABSTAINED (1)" in text and "warfarin for migraine" in text
    assert text.rstrip().endswith("Orinyx flags; the clinician decides.")


def test_render_is_plain_text_without_markdown():
    text = render_run_text(RUN, ACCURACY)
    assert "|" not in text and "#" not in text and "**" not in text
    assert "```" not in text


def test_accuracy_is_rendered_only_when_reviewed():
    without = render_run_text(RUN)
    assert "ACCURACY" not in without
    with_review = render_run_text(RUN, ACCURACY)
    assert "ACCURACY (physician review)" in with_review
    assert "False-flag rate 0.0% (0 of 1 flags; 0 of 1 carry a physician override" in with_review
    assert "Severity corrections 1" in with_review
    assert "Catch rate not estimated (miss review incomplete)" in with_review
    unreviewed = render_run_text(RUN, {"reviewed": False, "accuracy": None, "totalFlags": 1})
    assert "ACCURACY" not in unreviewed


def test_catch_rate_estimate_is_labelled():
    acc = {
        "reviewed": True,
        "totalFlags": 4,
        "unflaggedTotal": 20,
        "accuracy": {
            "falseFlags": 1,
            "falseFlagRate": 0.25,
            "severityCorrections": 0,
            "other": 0,
            "catchRate": {
                "value": 0.6,
                "isEstimate": True,
                "sampleSize": 5,
                "unflaggedTotal": 20,
                "missesInSample": 1,
                "estimatedMisses": 4.0,
            },
            "catchRateUnavailable": None,
        },
    }
    text = render_run_text(RUN, acc)
    assert "Catch rate 60.0% (estimate from a sample of 5 of 20 unflagged claims)" in text


def test_a_clean_run_says_so():
    clean = {
        **RUN,
        "verdicts": RUN["verdicts"][1:],
        "aggregate": {"total": 2, "supported": 1, "contradicted": 0, "abstain": 1},
    }
    text = render_run_text(clean)
    assert (
        "FLAGS (0) - NOT VERIFIED: Orinyx could not check every claim in this run, so this is "
        "not a safety clearance."
    ) in text
    assert "not a safety clearance" in text


def test_a_run_with_an_abstain_leads_with_not_verified_and_never_says_no_claim_contradicted():
    run = {
        **RUN,
        "verdicts": RUN["verdicts"][1:],  # one supported, one abstain, no flag
        "aggregate": {"total": 2, "supported": 1, "contradicted": 0, "abstain": 1},
    }
    table = render_run_table(run)
    assert (
        "NOT VERIFIED: Orinyx could not check every claim in this run, so this is not a "
        "safety clearance."
    ) in table
    assert "No claim was found to contradict its label." not in table
    assert (
        "NOT VERIFIED: Orinyx could not check these, which does not mean they are correct."
    ) in table
    assert table.index("could not check every claim") < table.index("could not check these")
    plain = render_run_text(run)
    assert (
        "FLAGS (0) - NOT VERIFIED: Orinyx could not check every claim in this run, so this is "
        "not a safety clearance."
    ) in plain
    assert "no claim was found to contradict its label" not in plain
    # the change touches only the no-flag branch
    assert "could not check every claim" not in render_run_table(RUN)
    assert "could not check every claim" not in render_run_text(RUN)
    # zero abstain and zero unreadable: the closing line still prints, in both forms
    clean = dict(RUN, verdicts=[RUN["verdicts"][1]], aggregate={"total": 1, "supported": 1})
    assert "No claim was found to contradict its label." in render_run_table(clean)
    assert "FLAGS (0): no claim was found to contradict its label." in render_run_text(clean)
    # unreadable-only: the lead prints after the unreadable warning
    unread = render_run_table(UNREADABLE_RUN)
    assert "could not check every claim" in unread
    assert unread.index("UNREADABLE: these orders cannot be read") < unread.index(
        "could not check every claim"
    )


def test_every_non_abstain_verdict_carries_its_whole_citation():
    """Every non-abstain verdict prints its whole citation. The text an agent reads once dropped the
    source id on flags and gave supported verdicts no citation at all."""
    text = render_run_text(RUN)
    assert (
        "Citation: openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin "
        "prescribing information - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?"
        "setid=abc-123"
    ) in text
    supported = text[text.index("SUPPORTED (1)") : text.index("ABSTAINED (1)")]
    assert "warfarin 5 mg daily" in supported
    assert "Citation: INCOMPLETE - do not rely on this verdict" in supported  # no sourceId
    whole = {**RUN["verdicts"][1], "citation": RUN["verdicts"][0]["citation"]}
    text = render_run_text({**RUN, "verdicts": [whole]})
    assert "INCOMPLETE" not in text and "id abc-123" in text
    bare = {**RUN["verdicts"][0], "citation": None}
    assert "Citation: INCOMPLETE" in render_run_text({**RUN, "verdicts": [bare]})


def test_an_agent_cannot_read_abstain_as_safe_or_supported_as_endorsement():
    """Principles 3 and 4: abstain is unchecked, with its reason; supported is agreement
    with label text, not a judgment that the order suits a patient."""
    text = render_run_text(RUN)
    assert "SUPPORTED (1) - consistent with the cited label text; not a judgment" in text
    assert "ABSTAINED (1) - NOT VERIFIED" in text and "does not mean they are correct" in text
    abstained = text[text.index("ABSTAINED (1)") :]
    assert "warfarin for migraine" in abstained
    assert "The label does not address this indication." in abstained


def test_rows_orinyx_added_itself_are_counted_apart_from_what_was_submitted():
    run = {
        **RUN,
        "verdicts": [*RUN["verdicts"], RUN["verdicts"][1]],
        "aggregate": {**RUN["aggregate"], "total": 4, "supported": 2, "synthesized": 1},
    }
    assert "Checked 4 rows (3 submitted, 1 co-prescription check added by Orinyx)" in (
        render_run_text(run)
    )


def test_a_run_saved_before_the_unreadable_verdict_still_heads_the_list():
    """An agent once read "5 mb" as "5 mg" without saying so (2026-10-06). Runs saved before
    the engine's `unreadable` verdict carry such claims as abstains whose reason says so;
    they are shown as unreadable, above the flags, never corrected, and counted once."""
    run = dict(RUN)
    run["verdicts"] = list(RUN["verdicts"]) + [
        {
            "rawText": "wafarin 5 mb by intramuscular injection",
            "drug": "wafarin",
            "claimType": "dose_range",
            "verdict": "abstain",
            "severity": "none",
            "explanation": "Drug 'wafarin' is not in the knowledge base; abstaining.",
        },
        {
            "rawText": "warfarin 5 mb daily",
            "drug": "warfarin",
            "claimType": "dose_range",
            "verdict": "abstain",
            "severity": "none",
            "explanation": "'mb' is not a recognised dose unit; the claim cannot be checked as "
            "written. Abstaining.",
        },
    ]
    run["aggregate"] = dict(
        RUN["aggregate"],
        total=RUN["aggregate"]["total"] + 2,
        abstain=RUN["aggregate"]["abstain"] + 2,
    )
    text = render_run_text(run)
    # "Not in the knowledge base" is an ordinary abstain (a real drug Orinyx does not hold,
    # and since 2026-10-10 a brand off the current list too); only the unit reason marks a
    # legacy row unreadable.
    assert text.splitlines()[1] == (
        "Checked 5 claims: 1 flagged, 1 unreadable as written, 1 supported, 2 abstained."
    )
    unread = text.index("UNREADABLE AS WRITTEN (1)")
    assert unread < text.index("FLAGS (")
    assert "a correction must never be assumed" in text
    assert "warfarin 5 mb daily (dose)" in text[unread : text.index("FLAGS (")]
    assert "'mb' is not a recognised dose unit" in text
    # The knowledge-base miss and the ordinary abstain are abstains, each counted once.
    assert "ABSTAINED (2) - NOT VERIFIED" in text
    assert text.count("wafarin 5 mb by intramuscular injection") == 1


def _rows(text: str) -> list[list[str]]:
    body = [line for line in text.splitlines() if line.startswith("| ")][1:]
    return [[cell.strip() for cell in line.strip("|").split(" | ")] for line in body]


def test_an_agent_gets_one_table_row_per_claim_flags_before_supported_before_abstains():
    text = render_run_table(RUN)
    assert "| # | Claim | Part | Result | Severity | Why | Citation |" in text
    rows = _rows(text)
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("1", "warfarin 20 mg daily", "dose", "FLAGGED"),
        ("2", "warfarin 5 mg daily", "dose", "SUPPORTED"),
        ("3", "warfarin for migraine", "indication", "NOT VERIFIED (abstain)"),
    ]
    assert rows[0][4] == "MODERATE"
    assert rows[0][5] == "Dose 20 mg exceeds the explicitly stated maximum of 10 mg."


def test_a_table_row_cites_in_full_below_or_says_incomplete():
    text = render_run_table(RUN)
    flagged, supported, abstained = _rows(text)
    assert flagged[6] == "[1]"
    assert (
        "[1] openFDA, Dosage and Administration (§2) - id abc-123 - Coumadin prescribing "
        "information - https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=abc-123"
    ) in text
    assert supported[6] == INCOMPLETE_CITATION  # no source id: never shown as cited
    assert abstained[6] == "-"
    assert "Row 1 (MODERATE): Rated Moderate because" in text


def test_the_table_keeps_every_warning_of_the_plain_form():
    text = render_run_table(RUN, ACCURACY)
    assert "which does not mean they are correct" in text
    assert "not a judgment that the order suits a patient" in text
    assert "ACCURACY (physician review)" in text
    assert text.rstrip().endswith("Orinyx flags; the clinician decides.")
    clean = dict(RUN, verdicts=[RUN["verdicts"][1]], aggregate={"total": 1, "supported": 1})
    assert "This is not a safety clearance" in render_run_table(clean)


def test_an_unreadable_claim_heads_the_table_and_a_pipe_cannot_break_a_row():
    unread = {
        "rawText": "wafarin | 5 mb",
        "verdict": "abstain",
        "explanation": "'mb' is not a recognised dose unit; the claim cannot be checked as "
        "written.",
    }
    run = dict(RUN, verdicts=[*RUN["verdicts"], unread])
    text = render_run_table(run)
    first = [line for line in text.splitlines() if line.startswith("| 1 |")][0]
    assert "wafarin \\| 5 mb" in first and UNREADABLE_LABEL in first
    assert len(_rows(text)) == 4
    assert "Never assume a correction" in text


# The tester's orders through the engine's `unreadable` verdict (2026-10-06):
# one order, two claims, every facet listed, the engine's suggestions in their own block.
ORDER = "wafarin 5 mb by intramuscular injection"
UNREADABLE_RUN = {
    "runId": "7a1c0e55-0000-4000-8000-000000000001",
    "aggregate": {"total": 2, "supported": 0, "contradicted": 0, "abstain": 0, "unreadable": 2},
    "verdicts": [
        {
            "rawText": ORDER,
            "drug": "wafarin",
            "claimType": "dose_range",
            "verdict": "unreadable",
            "severity": "none",
            "explanation": "The order cannot be read as written: ...",
            "unreadableFacets": [
                {
                    "facet": "drug",
                    "value": "wafarin",
                    "reason": "'wafarin' is not a drug name Orinyx recognises",
                },
                {"facet": "unit", "value": "mb", "reason": "'mb' is not a recognised dose unit"},
            ],
            "suggestions": [
                {"facet": "drug", "value": "wafarin", "candidates": ["warfarin"], "note": "n"},
                {"facet": "unit", "value": "mb", "candidates": ["mL", "mg"], "note": "n"},
            ],
        },
        {
            "rawText": ORDER,
            "drug": "wafarin",
            "claimType": "route",
            "verdict": "unreadable",
            "severity": "none",
            "explanation": "The order cannot be read as written: ...",
            "unreadableFacets": [
                {
                    "facet": "drug",
                    "value": "wafarin",
                    "reason": "'wafarin' is not a drug name Orinyx recognises",
                },
            ],
            "suggestions": [
                {"facet": "drug", "value": "wafarin", "candidates": ["warfarin"], "note": "n"},
            ],
        },
    ],
}


def test_an_unreadable_order_is_a_flag_with_every_facet_and_never_a_correction():
    text = render_run_table(UNREADABLE_RUN)
    assert text.splitlines()[1] == (
        "Checked 2 claims: 0 flagged, 2 unreadable as written, 0 supported, 0 abstained."
    )
    rows = _rows(text)
    assert [(r[1], r[2], r[3]) for r in rows] == [
        (ORDER, "dose", UNREADABLE_LABEL),
        (ORDER, "route", UNREADABLE_LABEL),
    ]
    assert rows[0][5] == (
        "'wafarin' is not a drug name Orinyx recognises; 'mb' is not a recognised dose unit"
    )
    # The corrected spelling appears only inside the engine's labelled suggestion block.
    block = text[text.index(SUGGESTIONS_HEADING) :]
    assert "warfarin" not in text[: text.index(SUGGESTIONS_HEADING)]
    assert "Row 1, drug 'wafarin': warfarin" in block
    assert "Row 1, unit 'mb': mL or mg" in block
    assert "Do not act on them" in text
    assert "NOT VERIFIED (abstain)" not in text


def test_the_plain_form_lists_the_same_unreadable_order_and_suggestions():
    text = render_run_text(UNREADABLE_RUN)
    assert "UNREADABLE AS WRITTEN (2)" in text
    assert f"1. {ORDER} (dose)" in text and f"2. {ORDER} (route)" in text
    assert SUGGESTIONS_HEADING in text
    assert "Unreadable 1, unit 'mb': mL or mg" in text
    assert "|" not in text


def test_without_engine_suggestions_there_is_no_suggestion_block():
    bare = {
        **UNREADABLE_RUN,
        "verdicts": [{**v, "suggestions": None} for v in UNREADABLE_RUN["verdicts"]],
    }
    assert SUGGESTIONS_HEADING not in render_run_table(bare)
    assert "warfarin" not in render_run_table(bare)


# --- 2026-10-21 safety core (dated text exception): context not evaluated, the supported note,
# and the five MCP runs of that day as engine-shaped results ------------------------------------

CONTEXT_NOTE = (
    "Patient context (allergy or clinical-history wording) was found in this request and was "
    "NOT evaluated: Orinyx checks each claim against its label only, so contraindications and "
    "allergies for this patient were not checked."
)
SUPPORTED_NOTE = (
    "Supported means one claim agrees with its cited label text. It does not clear the regimen: "
    "the daily total, the schedule and patient context are checked only where a row says so."
)
M013 = {
    "source": "FDA OTC Monograph",
    "section": "M013.50(d)(2)",
    "sourceId": "M013.50(d)(2)",
    "citation": "OTC Monograph M013 §M013.50(d)(2)",
    "url": "https://www.accessdata.fda.gov/drugsatfda_docs/omuf/monographs/M013.pdf",
}


def _row(raw, claim_type, verdict, explanation, citation=None, severity="none"):
    return {
        "rawText": raw,
        "drug": raw.split()[0],
        "claimType": claim_type,
        "verdict": verdict,
        "severity": severity,
        "explanation": explanation,
        "citation": citation,
    }


def _run(verdicts, **extra):
    counts = {k: sum(1 for v in verdicts if v["verdict"] == k) for k in ("supported", "abstain")}
    flagged = sum(1 for v in verdicts if v["verdict"] == "contradicted")
    aggregate = {"total": len(verdicts), "contradicted": flagged, **counts}
    if counts["supported"]:
        aggregate["supportedNote"] = SUPPORTED_NOTE
    return {
        "runId": "7d0f39e9-0000-4000-8000-000000000000",
        "verdicts": verdicts,
        "aggregate": aggregate,
        **extra,
    }


AMOXICILLIN_ORDER = "Amoxicillin 500 mg PO q8h history of penicillin anaphylaxis"
AMOXICILLIN_RUN = _run(
    [_row(AMOXICILLIN_ORDER, "dose_range", "supported", "Dose 500.0 mg falls within ...", M013)],
    contextNotEvaluated={"note": CONTEXT_NOTE, "fields": ["order 1"], "count": 1},
)


def test_context_not_evaluated_is_printed_right_under_the_header_in_both_forms():
    for render in (render_run_table, render_run_text):
        lines = render(AMOXICILLIN_RUN).splitlines()
        assert lines[2] == (f"PATIENT CONTEXT NOT EVALUATED: {CONTEXT_NOTE} (found in: order 1)")


def test_the_context_line_names_where_never_what_and_counts_beyond_the_list():
    run = {
        **AMOXICILLIN_RUN,
        "contextNotEvaluated": {"note": CONTEXT_NOTE, "fields": ["patientHistory"], "count": 3},
    }
    text = render_run_table(run)
    assert "(found in: patientHistory and 2 more)" in text
    assert "anaphylaxis" not in render_run_table(
        {**run, "verdicts": [{**v, "rawText": "amoxicillin 500 mg"} for v in run["verdicts"]]}
    )


def test_without_the_key_nothing_changes():
    bare = {k: v for k, v in AMOXICILLIN_RUN.items() if k != "contextNotEvaluated"}
    assert "PATIENT CONTEXT" not in render_run_table(bare)
    assert "PATIENT CONTEXT" not in render_run_text(bare)


def test_the_supported_note_follows_the_footer_in_the_table_form_only():
    text = render_run_table(AMOXICILLIN_RUN)
    assert text.endswith(f"Note: {SUPPORTED_NOTE}")
    assert text.index(f"Note: {SUPPORTED_NOTE}") > text.index("Orinyx flags; the clinician")
    assert "Note: Supported means" not in render_run_text(AMOXICILLIN_RUN)


def test_run_a0b04b56_the_9000_mg_regimen_is_flagged_with_its_citation():
    explanation = (
        "Daily exposure 1500.0 mg × 6 doses per day = 9000.0 mg exceeds the explicitly stated "
        "maximum of 4000 mg in 24 hours (FDA OTC Monograph, M013.50(d)(2)). Assumption: "
        "'every 4 hours' read as 6 doses in 24 hours, around the clock."
    )
    run = _run(
        [
            _row(
                "Acetaminophen 1500 mg PO q4h",
                "dose_range",
                "contradicted",
                explanation,
                M013,
                "moderate",
            )
        ]
    )
    text = render_run_table(run)
    assert "| FLAGGED | MODERATE |" in text and "9000.0 mg" in text
    assert "[1] FDA OTC Monograph" in text
    assert "FLAGGED: the cited label says otherwise" in text


def test_run_d8805b5e_the_prn_bound_reads_as_not_verified():
    explanation = (
        "Dose 650.0 mg is not within any extracted labeled range and no explicitly stated "
        "maximum is exceeded; abstaining (range extraction is not exhaustive). Daily total not "
        "computed: 'every 6 hours as needed' is an as-needed or range schedule, which has no "
        "single doses-per-day count. If taken every 6 hours around the clock: up to 2600 mg in "
        "24 hours (4 doses); a stated calculation, not a check."
    )
    run = _run([_row("Acetaminophen 650 mg PO q6h PRN", "dose_range", "abstain", explanation)])
    text = render_run_table(run)
    assert "NOT VERIFIED (abstain)" in text and "up to 2600 mg" in text
    assert "FLAGGED" not in text
    assert "No claim was found to contradict its label" not in text


def test_run_a78be2b2_the_missing_route_and_frequency_are_stated():
    run = _run(
        [
            _row(
                "Metoprolol tartrate 50 mg",
                "dose_range",
                "abstain",
                "The claim names a formulation ('tartrate'); ...",
            )
        ],
        orders=[
            {
                "index": 0,
                "unparsed": [],
                "notes": ["route not stated in the order", "frequency not stated in the order"],
            }
        ],
    )
    text = render_run_table(run)
    assert "Order 1: note: route not stated in the order" in text
    assert "Order 1: note: frequency not stated in the order" in text


def test_run_7d0f39e9_a_supported_dose_is_never_regimen_clearance():
    explanation = (
        "Dose 20.0 mg falls within the labeled range 20.0–40.0 mg. Daily total 120 mg in 24 "
        "hours (6 doses; assumption: 'every 4 hours' around the clock); no 24-hour maximum is "
        "on file for this drug, so the daily total was not checked."
    )
    run = _run(
        [
            _row("Lisinopril 20 mg PO q4h", "dose_range", "supported", explanation, M013),
            _row(
                "Lisinopril 20 mg PO q4h",
                "frequency",
                "abstain",
                "No labeled dosing schedule matches 'every 4 hours'; abstaining.",
            ),
        ]
    )
    text = render_run_table(run)
    assert "Daily total 120 mg in 24 hours" in text
    assert text.endswith(f"Note: {SUPPORTED_NOTE}")
    assert "No claim was found to contradict its label" not in text


def test_run_fd1ee3db_the_get_shaped_record_carries_the_warning_too():
    """get_verification renders the GET read-back, which carries contextNotEvaluated but no
    `orders` list: the warning must not depend on the POST-only fields."""
    run = {k: v for k, v in AMOXICILLIN_RUN.items() if k != "orders"}
    run["createdAt"] = "2026-10-21T15:00:00+00:00"
    assert "PATIENT CONTEXT NOT EVALUATED" in render_run_table(run)


def test_a_saved_orders_run_shows_its_order_notes_and_checking_time():
    """The GET read-back now carries `orders` (index, unparsed, notes) and `durationMs`
    (engine 2026-10-21), so get_verification says what the order left out."""
    run = _run(
        [
            _row(
                "Metoprolol tartrate 50 mg",
                "dose_range",
                "abstain",
                "The claim names a formulation ('tartrate'); ...",
            )
        ],
        orders=[
            {
                "index": 0,
                "unparsed": [],
                "notes": ["route not stated in the order", "frequency not stated in the order"],
                "claimIndexes": [0],
            }
        ],
        durationMs=41.7,
        createdAt="2026-10-21T15:00:00+00:00",
    )
    text = render_run_table(run)
    assert "Order 1: note: route not stated in the order" in text
    assert text.splitlines()[-1] == "Orinyx checking time: 41.7 ms"


def test_no_checking_time_line_without_the_key():
    assert "checking time" not in render_run_table(AMOXICILLIN_RUN)

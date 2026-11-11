"""The clinical test script (evals/clinical_suite.py): bucketing, exit codes and the fixture file.

No engine and no network: a fake client stands in for the API, as everywhere in this package. These
tests prove the harness cannot quietly turn an unsupported check, an abstain or a missing probe
into a pass; they say nothing about Orinyx's clinical behaviour (that is what a run against an API
measures)."""

import copy
import json
from pathlib import Path

import pytest
from evals import clinical_suite as cs
from orinyx_mcp.client import OrinyxApiError, VerificationResult

FIXTURES = Path(cs.DEFAULT_FIXTURES)
MAP = Path(cs.DEFAULT_MAP)


@pytest.fixture
def doc():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def verdict(claim_type="dose_range", result="abstain", severity="none", text="x", drug="d"):
    return {
        "rawText": "x",
        "drug": drug,
        "claimType": claim_type,
        "verdict": result,
        "severity": severity,
        "explanation": text,
        "citation": (
            {"source": "openFDA", "section": "s", "url": "https://x", "citation": "c"}
            if result in ("supported", "contradicted")
            else None
        ),
    }


def run_of(verdicts):
    agg = {"total": len(verdicts), "supported": 0, "contradicted": 0, "abstain": 0, "unreadable": 0}
    for v in verdicts:
        agg[
            {
                "supported": "supported",
                "contradicted": "contradicted",
                "abstain": "abstain",
                "unreadable": "unreadable",
            }[v["verdict"]]
        ] += 1
    return VerificationResult.from_json(
        {"runId": "00000000-0000-0000-0000-000000000001", "verdicts": verdicts, "aggregate": agg}
    )


class FakeClient:
    """`policy(kind, payload)` returns the verdict dicts, or raises OrinyxApiError."""

    def __init__(self, policy=None):
        self.policy = policy or (lambda kind, payload: [verdict(text="No rule covers this drug")])
        self.calls = []

    def _go(self, kind, payload, kwargs):
        self.calls.append((kind, payload, kwargs))
        return run_of(self.policy(kind, payload))

    def verify_orders(self, orders, **kwargs):
        return self._go("orders", orders, kwargs)

    def verify(self, claims, **kwargs):
        return self._go("claims", claims, kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def flag_sulfonamide(kind, payload):
    if kind == "claims" and any(
        c["structuredValue"].get("condition") == "sulfonamide" for c in payload
    ):
        return [verdict("contraindication", "contradicted", "major")]
    return [verdict(text="No contraindication rule covers this drug")]


# --- the fixture file ----------------------------------------------------------------


def test_fixture_file_lints_clean_against_the_capability_map(doc):
    assert cs.lint(doc, MAP.read_text(encoding="utf-8")) == []


def test_every_brief_fixture_is_present(doc):
    ids = {f["id"] for f in doc["fixtures"]}
    assert ids == {f"UTI-001-{x}" for x in "ABCDEFGHJK"} | {
        "UTI-001-I",
        "UTI-001-I-ctrl",
        "UTI-001-K-ctrl",
    }


def test_expected_answers_match_the_brief(doc):
    by = {f["id"]: f for f in doc["fixtures"]}
    assert by["UTI-001-A"]["expected_assessment"] == "SAFE_APPROPRIATE"
    assert by["UTI-001-I"]["severity_false_negative"] == "CRITICAL"
    assert by["UTI-001-E"]["review_status"] == "clinician_review"
    assert by["UTI-001-E"]["expected_orinyx_detection"]["flag"] is None
    assert by["UTI-001-J"]["expected_assessment"] == "EVIDENCE_MISREPRESENTED"
    assert by["UTI-001-G"]["severity_false_positive"] == "MODERATE"


def test_lint_rejects_an_order_that_is_not_verbatim(doc):
    doc["fixtures"][0]["probes"][0]["orders"][0] += " and a pinch of salt"
    assert any("not verbatim" in e for e in cs.lint(doc))


def test_lint_rejects_a_scoreable_fixture_with_no_scored_probe(doc):
    for p in doc["fixtures"][1]["probes"]:
        p["scored"] = False
    assert any("quiet pass" in e for e in cs.lint(doc))


def test_lint_rejects_scored_probes_on_an_unsupported_fixture(doc):
    fixture = next(f for f in doc["fixtures"] if f["id"] == "UTI-001-K")
    fixture["probes"][0]["scored"] = True
    assert any("UNSUPPORTED fixture must not carry scored" in e for e in cs.lint(doc))


def test_lint_rejects_an_asymmetric_pairing(doc):
    doc["fixtures"][0]["paired_with"].append("UTI-001-C")
    assert any("not symmetric" in e for e in cs.lint(doc))


def test_every_outbound_string_passes_the_identifier_screen(doc):
    for f in doc["fixtures"]:
        for p in f["probes"]:
            assert screen_hit(p) is None, (f["id"], p["id"])


def screen_hit(probe):
    return cs.screen.screen_orders(cs.outbound_strings(probe))


# --- bucketing -----------------------------------------------------------------------


def bucket_of(doc, fixture_id, policy):
    fixture = next(f for f in doc["fixtures"] if f["id"] == fixture_id)
    client = FakeClient(policy)
    probes = [cs.run_probe(client, p, "t") for p in fixture["probes"]]
    return cs.classify(fixture, probes)


def test_unsafe_output_flagged_on_the_expected_claim_type_is_a_true_positive(doc):
    out = bucket_of(doc, "UTI-001-B", flag_sulfonamide)
    assert out["bucket"] == cs.TRUE_POSITIVE
    assert out["detection_basis"] == "approximation"  # the harness wrote that claim


def test_unsafe_output_not_flagged_is_a_false_negative_never_a_pass(doc):
    out = bucket_of(doc, "UTI-001-B", lambda k, p: [verdict("contraindication", text="no rule")])
    assert out["bucket"] == cs.FALSE_NEGATIVE


def test_false_negative_kinds_are_told_apart(doc):
    gap = bucket_of(
        doc,
        "UTI-001-D",
        lambda k, p: [verdict(text="No dose_range rule covers this drug; abstaining.")],
    )
    other = bucket_of(doc, "UTI-001-D", lambda k, p: [verdict(text="No schedule matches")])
    partly = bucket_of(
        doc, "UTI-001-D", lambda k, p: [verdict("route", "supported", text="Route matches")]
    )
    assert gap["false_negative_kind"] == "abstained_coverage_gap"
    assert other["false_negative_kind"] == "abstained_other"
    assert partly["false_negative_kind"] == "partly_supported_no_flag"


def test_a_flag_on_an_unrelated_claim_type_does_not_count_as_detection(doc):
    out = bucket_of(doc, "UTI-001-B", lambda k, p: [verdict("route", "contradicted", "moderate")])
    assert out["bucket"] == cs.INCONCLUSIVE
    assert "flag_not_on_expected_claim_type" in out["reason"]


def test_safe_output_flagged_is_a_false_positive(doc):
    out = bucket_of(doc, "UTI-001-A", lambda k, p: [verdict("dose_range", "contradicted", "minor")])
    assert out["bucket"] == cs.FALSE_POSITIVE


def test_safe_output_with_abstains_is_a_true_negative_that_is_not_cleared(doc):
    out = bucket_of(doc, "UTI-001-A", lambda k, p: [verdict()])
    assert out["bucket"] == cs.TRUE_NEGATIVE
    assert out["orinyx_status_derived"] == "inconclusive"
    assert "NOT cleared" in out["reason"]


def test_unsupported_fixture_stays_inconclusive_even_when_orinyx_says_all_supported(doc):
    clean = lambda k, p: [verdict("route", "supported")]  # noqa: E731
    for fid in ("UTI-001-I", "UTI-001-J", "UTI-001-K", "UTI-001-K-ctrl", "UTI-001-H"):
        out = bucket_of(doc, fid, clean)
        assert out["bucket"] == cs.INCONCLUSIVE, fid
        assert "unsupported_check" in out["reason"]


def test_clinician_review_fixture_is_never_auto_scored(doc):
    out = bucket_of(
        doc, "UTI-001-E", lambda k, p: [verdict("contraindication", "contradicted", "major")]
    )
    assert out["bucket"] == cs.INCONCLUSIVE
    assert "clinician_review" in out["reason"]


def test_a_refused_order_is_unmappable_not_a_pass(doc):
    fixture = copy.deepcopy(next(f for f in doc["fixtures"] if f["id"] == "UTI-001-A"))

    def refuse(kind, payload):
        raise OrinyxApiError(422, "validation_failed", "No order states a dose, route or frequency")

    probes = [cs.run_probe(FakeClient(refuse), p, "t") for p in fixture["probes"]]
    out = cs.classify(fixture, probes)
    assert out["bucket"] == cs.INCONCLUSIVE and out["reason"].startswith("unmappable")


def test_server_error_is_an_execution_error(doc):
    def boom(kind, payload):
        raise OrinyxApiError(503, "unavailable", "down")

    out = bucket_of(doc, "UTI-001-A", boom)
    assert out["bucket"] == cs.EXECUTION_ERROR


def test_identifier_shaped_text_is_blocked_before_sending(doc):
    fixture = copy.deepcopy(next(f for f in doc["fixtures"] if f["id"] == "UTI-001-A"))
    fixture["probes"][0]["orders"] = ["warfarin 5 mg daily MRN 12345"]
    client = FakeClient()
    probes = [cs.run_probe(client, p, "t") for p in fixture["probes"]]
    assert client.calls == []
    assert cs.classify(fixture, probes)["bucket"] == cs.EXECUTION_ERROR


def test_rate_limit_is_retried_and_counted(doc):
    state = {"n": 0}

    def limited(kind, payload):
        state["n"] += 1
        if state["n"] <= 2:
            raise OrinyxApiError(429, "rate_limited", "slow down")
        return [verdict()]

    waits = []
    probe = doc["fixtures"][0]["probes"][0]
    result = cs.run_probe(FakeClient(limited), probe, "t", sleep=waits.append)
    assert result["outcome"] == "ok" and result["rate_limit_retries"] == 2 and len(waits) == 2


def test_throttle_never_exceeds_the_per_minute_budget():
    now = {"t": 0.0}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now["t"] += seconds

    throttle = cs.Throttle(3, clock=lambda: now["t"], sleep=sleep)
    for _ in range(4):
        throttle.wait()
    assert len(slept) == 1 and slept[0] >= 60


def test_derived_status_follows_the_documented_ruling():
    assert cs.derive_status([verdict(result="contradicted", severity="major")]) == "fail"
    assert cs.derive_status([verdict(result="abstain")]) == "inconclusive"
    assert cs.derive_status([]) == "inconclusive"
    assert cs.derive_status([verdict(result="supported")]) == "pass"
    assert cs.derive_status([{"verdict": "supported", "citation": None}]) == "inconclusive"


# --- suite, summary and exit codes ---------------------------------------------------


def run_all(doc, policy, runs=2):
    records = cs.run_suite(doc, FakeClient(policy), runs)
    return records, cs.summarize(doc, records)


def test_a_critical_false_negative_exits_2_whatever_the_pass_rate(doc):
    doc["fixtures"][1]["severity_false_negative"] = "CRITICAL"  # B, which the policy never flags
    records, summary = run_all(doc, lambda k, p: [verdict("contraindication")])
    assert summary["critical_false_negatives"] == ["UTI-001-B"]
    assert summary["exit_code"] == 2


def test_unsupported_critical_check_exits_3_not_0_and_is_named(doc):
    _, summary = run_all(doc, flag_sulfonamide)
    assert summary["exit_code"] == 3
    assert summary["critical_checks_not_established"] == ["UTI-001-I"]


def test_exit_0_only_when_every_automated_fixture_is_a_stable_tp_or_tn(doc):
    keep = {"UTI-001-A", "UTI-001-B", "UTI-001-E"}
    doc["fixtures"] = [f for f in doc["fixtures"] if f["id"] in keep]
    for f in doc["fixtures"]:
        f["paired_with"] = [x for x in f["paired_with"] if x in keep]
    _, summary = run_all(doc, flag_sulfonamide)
    assert summary["exit_code"] == 0  # E is clinician_review: excluded from the verdict


def test_execution_error_exits_1(doc):
    def boom(kind, payload):
        raise OrinyxApiError(500, "internal", "boom")

    _, summary = run_all(doc, boom, runs=1)
    assert summary["exit_code"] == 1


def test_a_fixture_whose_runs_disagree_is_unstable_and_not_clean(doc):
    state = {"scored_calls": 0}

    def flaky(kind, payload):
        flagged = False
        if kind == "claims" and payload[0]["structuredValue"].get("condition") == "sulfonamide":
            state["scored_calls"] += 1
            flagged = state["scored_calls"] % 2 == 0  # the scored probe alternates between runs
        return [
            verdict(
                "contraindication",
                "contradicted" if flagged else "abstain",
                "major" if flagged else "none",
            )
        ]

    records = cs.run_suite(doc, FakeClient(flaky), 3, ["UTI-001-B"])
    fixtures = cs.per_fixture(records)
    assert fixtures["UTI-001-B"]["stable"] is False
    assert "UTI-001-B" in cs.summarize(doc, records)["unstable_fixtures"]


def test_records_carry_the_fixture_provenance_unchanged(doc):
    records, _ = run_all(doc, flag_sulfonamide, runs=1)
    by = {f["id"]: f for f in doc["fixtures"]}
    for r in records:
        f = by[r["fixture_id"]]
        assert r["review_status"] == f["review_status"]
        assert r["jurisdiction"] == f["jurisdiction"]
        assert r["evidence_basis"] == f["evidence_basis"]
        assert [c["id"] for c in r["citations"]] == f["evidence_ids"]
        for c in r["citations"]:
            assert c == {
                "id": c["id"],
                "full_citation": doc["evidence"][c["id"]]["full_citation"],
                "pub_date": doc["evidence"][c["id"]]["pub_date"],
            }
        assert r["patient_context_sent_to_orinyx"] is False


def test_buckets_are_never_merged_in_the_summary(doc):
    records, summary = run_all(doc, flag_sulfonamide)
    assert list(summary["bucket_counts_records"]) == list(cs.BUCKETS)
    assert sum(summary["bucket_counts_records"].values()) == len(records)


def test_a_pair_with_identical_orinyx_output_is_not_discriminated(doc):
    _, summary = run_all(doc, lambda k, p: [verdict()])
    pairs = {tuple(p["pair"]): p for p in summary["pair_results"]}
    assert pairs[("UTI-001-K", "UTI-001-K-ctrl")]["result"] == "not_discriminated"
    assert pairs[("UTI-001-F", "UTI-001-G")]["result"] == "not_discriminated"


def test_ranked_gaps_put_the_critical_gaps_first(doc):
    records, _ = run_all(doc, flag_sulfonamide, runs=1)
    gaps = cs.ranked_gaps(doc, cs.per_fixture(records))
    assert gaps[0]["highest_severity_affected"] == "CRITICAL"
    assert {g["cap"] for g in gaps[:3]} == {"CAP-05", "CAP-06", "CAP-10"}


# --- report and CLI ------------------------------------------------------------------


def test_markdown_report_has_every_required_section_and_the_limitations(doc):
    records, _ = run_all(doc, flag_sulfonamide, runs=1)
    env = {
        "timestamp_utc": "t",
        "suite": doc["suite"],
        "fixtures_file": "f",
        "fixtures_sha256": "0" * 64,
        "runner": {"orinyx_mcp_version": "0", "repo_commit": "c", "working_tree_dirty": False},
        "orinyx_api": {"origin": "o", "version": "v", "commit": "c"},
        "config": {"runs_per_fixture": 1},
    }
    md = cs.render_markdown(cs.build_report(doc, records, env), doc, records)
    for heading in (
        "## Summary table",
        "## False negatives",
        "## False positives",
        "## Inconclusive results",
        "## Execution errors",
        "## Unsupported and partial checks",
        "## Limitations",
    ):
        assert heading in md
    assert "not a clinical validation" in md.lower()
    assert "NICE and EAU" in md


def test_main_requires_credentials(tmp_path, capsys):
    assert cs.main(["run", "--out", str(tmp_path)]) == 1
    assert "ORINYX_API_URL" in capsys.readouterr().err


def test_main_writes_both_outputs_and_returns_the_suite_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", "https://orinyx.example")
    monkeypatch.setenv("ORINYX_API_KEY", "ork_live_test")
    code = cs.main(
        ["run", "--runs", "1", "--out", str(tmp_path), "--max-per-minute", "10000"],
        client_factory=lambda url, key: FakeClient(flag_sulfonamide),
    )
    report = json.loads((tmp_path / "results.json").read_text())
    assert code == report["summary"]["exit_code"] == 3
    assert (tmp_path / "results.md").read_text().startswith("# Orinyx clinical test script")
    assert len(report["records"]) == 13


def test_lint_command(capsys):
    assert cs.main(["lint"]) == 0
    assert "13 fixtures" in capsys.readouterr().out

"""Clinical test script for a case family (UTI-001): does ORINYX detect what it should?

    export ORINYX_API_URL=https://<host>      ORINYX_API_KEY=<a tester key>
    python evals/clinical_suite.py lint
    python evals/clinical_suite.py run [--runs 3] [--out DIR] [--only UTI-001-B,UTI-001-D]
                                       [--engine-commit SHA] [--fixtures PATH]

This scores ORINYX (Layer B), never the agent. The candidate outputs in the fixture file are
fixed, synthetic strings and the brief's `expected_assessment` is the Layer A ground truth: this
script does not re-grade the agent and never asks a model anything. It cannot drive a live agent
(Orinyx evaluates what it is given), so there is no Layer A' mode.

How a fixture reaches Orinyx. Orinyx takes medication orders as text, or structured claims; it
has no field for patient context or a second turn. Each fixture therefore lists `probes`, and a
probe states where its text came from: `verbatim_from_candidate_output` (checked against the
output by `lint`) or `harness_translated_from_patient_context` (a claim the harness authored; ORINYX
never read the context). Only probes marked `scored` can change a bucket.

Every fixture result lands in exactly one bucket and the buckets are never merged:
TRUE_POSITIVE, TRUE_NEGATIVE, FALSE_NEGATIVE (missed unsafe), FALSE_POSITIVE (flagged safe),
INCONCLUSIVE (unsupported check, clinician review, unmappable output) and EXECUTION_ERROR.
UNSUPPORTED is never turned into a pass.

Exit codes (the repo's table, extended):
    0  every automated fixture is a stable TRUE_POSITIVE or TRUE_NEGATIVE
    1  an execution error, or a usage error (missing credentials, bad fixture file)
    2  at least one CRITICAL false negative, whatever the pass rate
    3  not clean: a false negative or positive, an inconclusive or unstable automated fixture
       (including a CRITICAL check that could not be established)
Nothing here imports the engine, and the key is read from the environment only. Synthetic data
only: every outbound string passes the repo's identifier screen first.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `python evals/clinical_suite.py`
    sys.path.insert(0, str(REPO))

from orinyx_mcp import __version__ as MCP_VERSION  # noqa: E402
from orinyx_mcp import screen  # noqa: E402
from orinyx_mcp.client import OrinyxApiError, OrinyxClient  # noqa: E402

DEFAULT_FIXTURES = REPO / "tests" / "fixtures" / "clinical" / "uti-001.json"
DEFAULT_MAP = REPO / "docs" / "clinical-suite" / "uti-001" / "CAPABILITY_MAP.md"
TOOL_NAME = "orinyx-clinical-suite"

TRUE_POSITIVE = "TRUE_POSITIVE"
TRUE_NEGATIVE = "TRUE_NEGATIVE"
FALSE_NEGATIVE = "FALSE_NEGATIVE"
FALSE_POSITIVE = "FALSE_POSITIVE"
INCONCLUSIVE = "INCONCLUSIVE"
EXECUTION_ERROR = "EXECUTION_ERROR"
BUCKETS = (
    TRUE_POSITIVE,
    TRUE_NEGATIVE,
    FALSE_NEGATIVE,
    FALSE_POSITIVE,
    INCONCLUSIVE,
    EXECUTION_ERROR,
)

SEVERITIES = ("CRITICAL", "HIGH", "MODERATE", "LOW")
# LOW_TO_MODERATE (fixture E) is weighed as MODERATE: the conservative end.
SEVERITY_WEIGHT = {"CRITICAL": 10, "HIGH": 5, "MODERATE": 2, "LOW": 1, "LOW_TO_MODERATE": 2}
ORINYX_SEVERITY_RANK = {"none": 0, "minor": 1, "moderate": 2, "major": 3}
FLAG_VERDICTS = ("contradicted", "unreadable")
REVIEW_STATUSES = ("automated", "clinician_review", "mixed")
CAPABILITY_STATUSES = ("SUPPORTED", "PARTIAL", "UNSUPPORTED")
ASSESSMENT_TOKENS = {
    "SAFE_APPROPRIATE",
    "UNSAFE",
    "NEEDS_CLARIFICATION",
    "NEEDS_ESCALATION",
    "EVIDENCE_MISREPRESENTED",
    "DISPUTED",
}
CLAIM_TYPES = {
    "contraindication",
    "dose_range",
    "monitoring",
    "indication",
    "route",
    "frequency",
    "interaction",
    "controlled_substance",
    "rems_attestation",
}
# Wording the engine uses when the knowledge base holds nothing for the drug or claim type.
_COVERAGE_GAP = re.compile(
    r"no [a-z_]+ rule covers this drug|is not in the knowledge base|no numeric dose-range rule",
    re.IGNORECASE,
)


class FixtureError(ValueError):
    """The fixture file or the capability map is not usable; a usage error, exit 1."""


# --- fixtures and lint ---------------------------------------------------------------


def load_fixtures(path: pathlib.Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        raise FixtureError(f"{path}: not JSON ({exc})") from None
    return doc, hashlib.sha256(raw).hexdigest()


def citations_for(doc: dict, fixture: dict) -> list[dict]:
    """The fixture's citations, materialised from the evidence registry, unchanged."""
    out = []
    for evidence_id in fixture.get("evidence_ids", []):
        entry = doc["evidence"][evidence_id]
        out.append(
            {
                "id": entry["id"],
                "full_citation": entry["full_citation"],
                "pub_date": entry["pub_date"],
            }
        )
    return out


def outbound_strings(probe: dict) -> list[str]:
    if probe["kind"] == "orders":
        return list(probe["orders"])
    return [c["rawText"] for c in probe["claims"]] + [
        str(c["structuredValue"].get("condition", "")) for c in probe["claims"]
    ]


def lint(doc: dict, map_text: str | None = None) -> list[str]:
    """Every problem found, as a sentence. Empty means the file is usable."""
    errors: list[str] = []
    fixtures = doc.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        return ["fixtures: a non-empty list is required"]
    ids = [f.get("id") for f in fixtures]
    if len(set(ids)) != len(ids):
        errors.append("fixture ids are not unique")
    by_id = {f.get("id"): f for f in fixtures}
    capabilities = doc.get("capabilities", {})
    required = (
        "id variant_of paired_with risk_category setting jurisdiction population patient_context "
        "turns candidate_output expected_assessment expected_orinyx_detection required_behaviors "
        "prohibited_behaviors pass_criteria acceptable_alternatives severity_false_negative "
        "severity_false_positive evidence_ids evidence_basis review_status notes "
        "capability_status checks probes"
    ).split()
    for f in fixtures:
        fid = f.get("id", "?")
        for key in required:
            if key not in f:
                errors.append(f"{fid}: missing field {key}")
        if f.get("review_status") not in REVIEW_STATUSES:
            errors.append(f"{fid}: review_status must be one of {REVIEW_STATUSES}")
        if f.get("capability_status") not in CAPABILITY_STATUSES:
            errors.append(f"{fid}: capability_status must be one of {CAPABILITY_STATUSES}")
        for token in str(f.get("expected_assessment", "")).split("+"):
            if token not in ASSESSMENT_TOKENS:
                errors.append(f"{fid}: unknown expected_assessment token {token!r}")
        for key in ("severity_false_negative", "severity_false_positive"):
            if f.get(key) is not None and f[key] not in SEVERITY_WEIGHT:
                errors.append(f"{fid}: {key} {f[key]!r} is not on the severity scale")
        flag = f.get("expected_orinyx_detection", {}).get("flag")
        if flag is True and not f.get("severity_false_negative"):
            errors.append(f"{fid}: an unsafe fixture needs severity_false_negative")
        if flag is False and not f.get("severity_false_positive"):
            errors.append(f"{fid}: a safe fixture needs severity_false_positive")
        if flag is None and f.get("review_status") != "clinician_review":
            errors.append(f"{fid}: expected flag null is only for clinician_review fixtures")
        for evidence_id in f.get("evidence_ids", []):
            if evidence_id not in doc.get("evidence", {}):
                errors.append(f"{fid}: evidence id {evidence_id} is not in the registry")
        for other in f.get("paired_with", []):
            if other not in by_id:
                errors.append(f"{fid}: paired_with {other} does not exist")
            elif fid not in by_id[other].get("paired_with", []):
                errors.append(f"{fid}: pairing with {other} is not symmetric")
        if f.get("variant_of") and f["variant_of"] not in by_id:
            errors.append(f"{fid}: variant_of {f['variant_of']} does not exist")
        for check in f.get("checks", []):
            if check.get("capability") not in CAPABILITY_STATUSES:
                errors.append(f"{fid}: check {check.get('id')} has no capability status")
            for ref in [check.get("cap_ref"), *check.get("also", [])]:
                if ref not in capabilities:
                    errors.append(f"{fid}: check {check.get('id')} cites unknown {ref}")
            if map_text is not None and check.get("id") not in map_text:
                errors.append(f"{fid}: check {check.get('id')} is not in CAPABILITY_MAP.md")
        probe_ids = [p.get("id") for p in f.get("probes", [])]
        if len(set(probe_ids)) != len(probe_ids):
            errors.append(f"{fid}: probe ids are not unique")
        scored = [p for p in f.get("probes", []) if p.get("scored")]
        automated_scoring = (
            f.get("review_status") != "clinician_review"
            and f.get("capability_status") != "UNSUPPORTED"
        )
        if automated_scoring and not scored:
            errors.append(f"{fid}: a scoreable fixture needs a scored probe (else a quiet pass)")
        if f.get("capability_status") == "UNSUPPORTED" and scored:
            errors.append(f"{fid}: an UNSUPPORTED fixture must not carry scored probes")
        for probe in f.get("probes", []):
            _lint_probe(f, probe, errors)
    if map_text is not None:
        for cap_id in capabilities:
            if cap_id not in map_text:
                errors.append(f"{cap_id} is not in CAPABILITY_MAP.md")
    return errors


def _lint_probe(fixture: dict, probe: dict, errors: list[str]) -> None:
    where = f"{fixture['id']}/{probe.get('id')}"
    if probe.get("kind") not in ("orders", "claims"):
        errors.append(f"{where}: kind must be orders or claims")
        return
    if probe.get("provenance") not in (
        "verbatim_from_candidate_output",
        "verbatim_from_turn_1_candidate_output",
        "harness_translated_from_patient_context",
    ):
        errors.append(f"{where}: unknown provenance")
    if probe["kind"] == "orders":
        orders = probe.get("orders", [])
        if not 1 <= len(orders) <= 50 or any(not 1 <= len(o) <= 500 for o in orders):
            errors.append(f"{where}: 1-50 orders of 1-500 characters (the API's limit)")
        if str(probe.get("provenance", "")).startswith("verbatim"):
            turn = probe.get("turn_index")
            source = (
                fixture["candidate_output"] if turn is None else fixture["turns"][turn]["content"]
            )
            for order in orders:
                if order not in source:
                    errors.append(f"{where}: order {order!r} is not verbatim in its source")
    else:
        for claim in probe.get("claims", []):
            if claim.get("claimType") not in CLAIM_TYPES:
                errors.append(f"{where}: unknown claimType {claim.get('claimType')!r}")
            if not claim.get("rawText") and probe.get("scored") is not False:
                errors.append(f"{where}: a scored claim needs rawText")
    if screen.screen_orders(outbound_strings(probe)):
        errors.append(f"{where}: an outbound string trips the identifier screen")


# --- one probe against Orinyx --------------------------------------------------------


def _trim_verdict(v: dict) -> dict:
    citation = v.get("citation")
    return {
        "claim_type": v.get("claimType"),
        "drug": v.get("drug"),
        "verdict": v.get("verdict"),
        "severity": v.get("severity"),
        "explanation": v.get("explanation"),
        "severity_reason": v.get("severityReason"),
        "citation": (
            {
                "source": citation.get("source"),
                "section": citation.get("section"),
                "url": citation.get("url"),
            }
            if citation
            else None
        ),
    }


def derive_status(verdicts: list[dict]) -> str:
    """The medication-verification status rule of the evaluation record (orinyx-mcp CLAUDE.md,
    ruling 5), derived HERE: orinyx_mcp has no record module yet and the engine returns no
    status. fail = any contradicted or unreadable; inconclusive = any abstain, no claims, or a
    supported claim without a complete citation; pass = every claim supported with a citation."""
    if any(v["verdict"] in FLAG_VERDICTS for v in verdicts):
        return "fail"
    if not verdicts or any(v["verdict"] != "supported" for v in verdicts):
        return "inconclusive"
    if any(not v.get("citation") for v in verdicts):
        return "inconclusive"
    return "pass"


class Throttle:
    """At most `per_minute` requests in any 60 seconds (the engine allows 60 per client).
    `clock` and `sleep` are injectable so a test needs no real waiting."""

    def __init__(self, per_minute: int, clock=time.monotonic, sleep=time.sleep) -> None:
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self._sent: list[float] = []

    def wait(self) -> None:
        now = self.clock()
        self._sent = [t for t in self._sent if now - t < 60]
        if len(self._sent) >= self.per_minute:
            self.sleep(60 - (now - self._sent[0]) + 0.1)
            now = self.clock()
            self._sent = [t for t in self._sent if now - t < 60]
        self._sent.append(now)


RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_SECONDS = 20


def run_probe(
    client,
    probe: dict,
    tool_version: str,
    use_screen: bool = True,
    throttle: Throttle | None = None,
    sleep=time.sleep,
) -> dict:
    """Send one probe. Never raises: the outcome is a record with `outcome` one of
    ok | refused (the API said the input is not checkable: 422) | error | blocked.
    A 429 is retried (the rate limit says nothing about the clinical input) and counted."""
    base = {
        "probe_id": probe["id"],
        "kind": probe["kind"],
        "scored": bool(probe.get("scored")),
        "role": probe.get("role", "primary" if probe.get("scored") else "observation"),
        "provenance": probe["provenance"],
        "purpose": probe.get("purpose", ""),
        "sent": probe.get("orders") if probe["kind"] == "orders" else probe.get("claims"),
    }
    if use_screen and screen.screen_orders(outbound_strings(probe)):
        return {**base, "outcome": "blocked", "error": {"code": "identifier_screen"}}
    started = time.perf_counter()
    retries = 0
    while True:
        if throttle:
            throttle.wait()
        try:
            if probe["kind"] == "orders":
                result = client.verify_orders(
                    probe["orders"], tool_name=TOOL_NAME, tool_version=tool_version
                )
            else:
                result = client.verify(
                    probe["claims"], tool_name=TOOL_NAME, tool_version=tool_version
                )
            break
        except OrinyxApiError as exc:
            if exc.status == 429 and retries < RATE_LIMIT_RETRIES:
                retries += 1
                sleep(RATE_LIMIT_WAIT_SECONDS)
                continue
            return {
                **base,
                "outcome": "refused" if exc.status == 422 else "error",
                "error": {"status": exc.status, "code": exc.code, "message": exc.message[:300]},
                "rate_limit_retries": retries,
                "wall_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        except Exception as exc:  # noqa: BLE001 - a record, never a crash mid-suite
            return {
                **base,
                "outcome": "error",
                "error": {"status": 0, "code": type(exc).__name__, "message": str(exc)[:300]},
            }
    raw = result.raw or {}
    verdicts = [_trim_verdict(v) for v in raw.get("verdicts", [])]
    flags = [v for v in verdicts if v["verdict"] in FLAG_VERDICTS]
    return {
        **base,
        "outcome": "ok",
        "orinyx_run_id": result.run_id,
        "verdicts": verdicts,
        "aggregate": raw.get("aggregate"),
        "context_not_evaluated": raw.get("contextNotEvaluated"),
        "flagged": bool(flags),
        "flag_claim_types": sorted({v["claim_type"] for v in flags}),
        "max_flag_severity": max(
            (v["severity"] for v in flags),
            key=lambda s: ORINYX_SEVERITY_RANK.get(s, 0),
            default=None,
        ),
        "status_derived": derive_status(verdicts),
        "rate_limit_retries": retries,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
    }


# --- bucketing -----------------------------------------------------------------------


def miss_severity(fixture: dict) -> str | None:
    """The severity of getting THIS fixture wrong: a false negative's for an unsafe fixture, a
    false positive's for a safe one, the more severe of the two when the brief gives both."""
    flag = fixture["expected_orinyx_detection"]["flag"]
    if flag is True:
        return fixture.get("severity_false_negative")
    if flag is False:
        return fixture.get("severity_false_positive")
    values = [fixture.get("severity_false_negative"), fixture.get("severity_false_positive")]
    return max((v for v in values if v), key=lambda s: SEVERITY_WEIGHT[s], default=None)


def classify(fixture: dict, probes: list[dict]) -> dict:
    """One bucket with its reasons. Pure: the same probes give the same answer."""
    review = fixture["review_status"]
    capability = fixture["capability_status"]
    expected = fixture["expected_orinyx_detection"]
    scored = [p for p in probes if p["scored"]]
    unsupported_checks = [c["id"] for c in fixture["checks"] if c["capability"] == "UNSUPPORTED"]
    detail: dict = {"unsupported_checks": unsupported_checks}

    def done(bucket: str, reason: str, **extra) -> dict:
        return {"bucket": bucket, "reason": reason, **detail, **extra}

    errored = [p for p in scored if p["outcome"] in ("error", "blocked")]
    if errored:
        return done(
            EXECUTION_ERROR,
            "; ".join(f"{p['probe_id']}: {p.get('error', {}).get('code')}" for p in errored),
        )
    if review == "clinician_review":
        return done(INCONCLUSIVE, "clinician_review: not auto-scored; Orinyx's output is recorded")
    if capability == "UNSUPPORTED":
        return done(
            INCONCLUSIVE,
            "unsupported_check: " + (", ".join(unsupported_checks) or "no capability"),
        )
    refused = [p for p in scored if p["outcome"] == "refused"]
    if refused:
        return done(
            INCONCLUSIVE,
            "unmappable: the API refused the input as not checkable ("
            + "; ".join(f"{p['probe_id']}: {p['error']['message']}" for p in refused)
            + ")",
        )
    if not scored:
        return done(INCONCLUSIVE, "no_checkable_input: the fixture has no scored probe")

    flagged = [p for p in scored if p["flagged"]]
    flagged_ids = [p["probe_id"] for p in flagged]
    status = (
        "pass"
        if all(p["status_derived"] == "pass" for p in scored)
        else ("fail" if flagged else "inconclusive")
    )
    verdict_counts = Counter(v["verdict"] for p in scored for v in p["verdicts"])
    common = {
        "flagged_by_probes": flagged_ids,
        "orinyx_status_derived": status,
        "verdict_counts": dict(verdict_counts),
    }

    if expected["flag"] is False:
        if flagged:
            return done(FALSE_POSITIVE, "Orinyx flagged an output the brief calls safe", **common)
        note = "no flag" + (
            "; NOT cleared: " + f"{verdict_counts.get('abstain', 0)} claim(s) unverified"
            if status != "pass"
            else ""
        )
        return done(TRUE_NEGATIVE, note, **common)

    accepted = expected.get("accepted_claim_types")
    hits = [p for p in flagged if not accepted or set(p["flag_claim_types"]) & set(accepted)]
    if hits:
        basis = (
            "approximation"
            if any(p["provenance"] == "harness_translated_from_patient_context" for p in hits)
            else "direct"
        )
        return done(
            TRUE_POSITIVE,
            "Orinyx flagged the unsafe output",
            detection_basis=basis,
            detected_by_probes=[p["probe_id"] for p in hits],
            **common,
        )
    if flagged:
        return done(
            INCONCLUSIVE,
            "flag_not_on_expected_claim_type: flagged "
            f"{sorted({t for p in flagged for t in p['flag_claim_types']})}, expected {accepted}",
            **common,
        )
    explanations = [v["explanation"] or "" for p in scored for v in p["verdicts"]]
    if verdict_counts.get("supported"):
        kind = "partly_supported_no_flag"
    elif explanations and all(_COVERAGE_GAP.search(e) for e in explanations if e):
        kind = "abstained_coverage_gap"
    else:
        kind = "abstained_other"
    return done(
        FALSE_NEGATIVE,
        f"Orinyx did not flag the unsafe output ({kind})",
        false_negative_kind=kind,
        **common,
    )


# --- the suite -----------------------------------------------------------------------


def verdict_signature(probes: list[dict]) -> list:
    return sorted(
        (
            p["probe_id"],
            p["outcome"],
            tuple(
                sorted(
                    (v["claim_type"], v["verdict"], v["severity"]) for v in p.get("verdicts", [])
                )
            ),
        )
        for p in probes
    )


def run_suite(
    doc: dict,
    client,
    runs: int,
    fixture_ids: list[str] | None = None,
    use_screen: bool = True,
    throttle: Throttle | None = None,
    sleep=time.sleep,
) -> list[dict]:
    """One record per fixture per run, in fixture order."""
    tool_version = f"uti-{doc['suite']['version']}"
    records = []
    for fixture in doc["fixtures"]:
        if fixture_ids and fixture["id"] not in fixture_ids:
            continue
        for run_index in range(1, runs + 1):
            probes = [
                run_probe(client, p, tool_version, use_screen, throttle, sleep)
                for p in fixture["probes"]
            ]
            verdict = classify(fixture, probes)
            records.append(
                {
                    "fixture_id": fixture["id"],
                    "run_index": run_index,
                    "bucket": verdict["bucket"],
                    "classification": verdict,
                    "expected_assessment": fixture["expected_assessment"],
                    "expected_orinyx_detection": fixture["expected_orinyx_detection"],
                    "miss_severity": miss_severity(fixture),
                    "severity_false_negative": fixture["severity_false_negative"],
                    "severity_false_positive": fixture["severity_false_positive"],
                    "risk_category": fixture["risk_category"],
                    "capability_status": fixture["capability_status"],
                    "checks": fixture["checks"],
                    "citations": citations_for(doc, fixture),
                    "evidence_basis": fixture["evidence_basis"],
                    "jurisdiction": fixture["jurisdiction"],
                    "review_status": fixture["review_status"],
                    "patient_context_sent_to_orinyx": False,
                    "probes": probes,
                    "signature": verdict_signature(probes),
                }
            )
    return records


def per_fixture(records: list[dict]) -> dict[str, dict]:
    """Fixture-level view: stable only if every run agrees on the bucket AND on what Orinyx said."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        grouped[r["fixture_id"]].append(r)
    out = {}
    for fid, rs in grouped.items():
        buckets = [r["bucket"] for r in rs]
        stable = len(set(buckets)) == 1 and all(r["signature"] == rs[0]["signature"] for r in rs)
        out[fid] = {
            "runs": len(rs),
            "buckets": buckets,
            "stable": stable,
            "bucket": buckets[0] if stable else None,
            "first": rs[0],
        }
    return out


def pair_results(doc: dict, fixtures: dict[str, dict]) -> list[dict]:
    """For each pair whose expected flags differ: did Orinyx tell them apart? A pair whose
    shared probes produced the same verdicts proves nothing about either side."""
    by_id = {f["id"]: f for f in doc["fixtures"]}
    seen, out = set(), []
    for f in doc["fixtures"]:
        for other in f["paired_with"]:
            key = tuple(sorted((f["id"], other)))
            if key in seen or f["id"] not in fixtures or other not in fixtures:
                continue
            seen.add(key)
            a, b = by_id[key[0]], by_id[key[1]]
            fa, fb = (x["expected_orinyx_detection"]["flag"] for x in (a, b))
            if fa is None or fb is None or fa == fb:
                continue
            ra, rb = fixtures[a["id"]]["first"], fixtures[b["id"]]["first"]
            shared = sorted(
                {p["probe_id"] for p in ra["probes"] if p["kind"] == _kind(rb, p["probe_id"])}
                & {p["probe_id"] for p in rb["probes"]}
            )

            def sig(record, pid):
                probe = next(p for p in record["probes"] if p["probe_id"] == pid)
                return (
                    probe["outcome"],
                    sorted(
                        (v["claim_type"], v["verdict"], v["severity"])
                        for v in probe.get("verdicts", [])
                    ),
                )

            identical = bool(shared) and all(sig(ra, p) == sig(rb, p) for p in shared)
            buckets = (ra["bucket"], rb["bucket"])
            if any(x not in (TRUE_POSITIVE, TRUE_NEGATIVE) for x in buckets):
                verdict = "not_evaluable"
            else:
                verdict = "discriminates"
            out.append(
                {
                    "pair": list(key),
                    "expected_flags": {a["id"]: fa, b["id"]: fb},
                    "buckets": {a["id"]: ra["bucket"], b["id"]: rb["bucket"]},
                    "shared_probe_ids": shared,
                    "identical_orinyx_output_on_shared_probes": identical,
                    "result": "not_discriminated" if identical else verdict,
                }
            )
    return out


def _kind(record: dict, probe_id: str) -> str | None:
    return next((p["kind"] for p in record["probes"] if p["probe_id"] == probe_id), None)


def summarize(doc: dict, records: list[dict]) -> dict:
    fixtures = per_fixture(records)
    fixture_defs = {f["id"]: f for f in doc["fixtures"]}
    record_counts = Counter(r["bucket"] for r in records)
    stable = {fid: v for fid, v in fixtures.items() if v["stable"]}
    fixture_counts = Counter(v["bucket"] for v in stable.values())
    unstable = sorted(fid for fid, v in fixtures.items() if not v["stable"])

    by_severity: dict[str, Counter] = defaultdict(Counter)
    by_category: dict[str, Counter] = defaultdict(Counter)
    for fid, v in stable.items():
        sev = v["first"]["miss_severity"] or "NONE"
        by_severity[sev][v["bucket"]] += 1
        for cat in fixture_defs[fid]["risk_category"]:
            by_category[cat][v["bucket"]] += 1

    automated = {
        fid
        for fid, f in fixture_defs.items()
        if fid in fixtures and f["review_status"] != "clinician_review"
    }
    critical_fn = sorted(
        {
            r["fixture_id"]
            for r in records
            if r["bucket"] == FALSE_NEGATIVE and r["miss_severity"] == "CRITICAL"
        }
    )
    critical_unestablished = sorted(
        fid
        for fid in automated
        if fixture_defs[fid]["severity_false_negative"] == "CRITICAL"
        and (fid not in stable or stable[fid]["bucket"] != TRUE_POSITIVE)
        and fid not in critical_fn
    )
    errors = sorted({r["fixture_id"] for r in records if r["bucket"] == EXECUTION_ERROR})
    not_clean = sorted(
        fid
        for fid in automated
        if fid not in stable or stable[fid]["bucket"] not in (TRUE_POSITIVE, TRUE_NEGATIVE)
    )

    def weight(fid: str) -> int:
        return SEVERITY_WEIGHT.get(stable[fid]["first"]["miss_severity"] or "", 0)

    unsafe_auto = [
        fid
        for fid in automated
        if fid in stable and fixture_defs[fid]["expected_orinyx_detection"]["flag"] is True
    ]
    tp = sum(weight(f) for f in unsafe_auto if stable[f]["bucket"] == TRUE_POSITIVE)
    fn = sum(weight(f) for f in unsafe_auto if stable[f]["bucket"] == FALSE_NEGATIVE)
    inc = sum(weight(f) for f in unsafe_auto if stable[f]["bucket"] == INCONCLUSIVE)
    fp = sum(weight(f) for f in automated if f in stable and stable[f]["bucket"] == FALSE_POSITIVE)
    weighted = {
        "weights": SEVERITY_WEIGHT,
        "true_positive_weight": tp,
        "false_negative_weight": fn,
        "inconclusive_unsafe_weight": inc,
        "false_positive_weight": fp,
        "recall_on_scored_unsafe": round(tp / (tp + fn), 3) if tp + fn else None,
        "recall_counting_inconclusive_as_missed": round(tp / (tp + fn + inc), 3)
        if tp + fn + inc
        else None,
        "note": "Weighted by the brief's miss severity. The second figure keeps unsupported checks "
        "in the denominator; the first hides them and must not be quoted alone.",
    }

    if critical_fn:
        exit_code, why = 2, f"CRITICAL false negative: {', '.join(critical_fn)}"
    elif errors:
        exit_code, why = 1, f"execution error: {', '.join(errors)}"
    elif not_clean:
        exit_code, why = 3, f"not clean: {', '.join(not_clean)}"
    else:
        exit_code, why = 0, "every automated fixture is a stable TRUE_POSITIVE or TRUE_NEGATIVE"

    return {
        "fixtures": len(fixtures),
        "records": len(records),
        "bucket_counts_records": {b: record_counts.get(b, 0) for b in BUCKETS},
        "bucket_counts_fixtures_stable": {b: fixture_counts.get(b, 0) for b in BUCKETS},
        "unstable_fixtures": unstable,
        "by_miss_severity": {
            k: {b: c.get(b, 0) for b in BUCKETS} for k, c in sorted(by_severity.items())
        },
        "by_risk_category": {
            k: {b: c.get(b, 0) for b in BUCKETS} for k, c in sorted(by_category.items())
        },
        "weighted": weighted,
        "critical_false_negatives": critical_fn,
        "critical_checks_not_established": critical_unestablished,
        "automated_fixtures_not_clean": not_clean,
        "clinician_review_fixtures": sorted(
            fid
            for fid, f in fixture_defs.items()
            if fid in fixtures and f["review_status"] == "clinician_review"
        ),
        "pair_results": pair_results(doc, fixtures),
        "exit_code": exit_code,
        "exit_reason": why,
    }


# --- environment ----------------------------------------------------------------------


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def engine_info(client) -> dict:
    try:
        spec = client._request("GET", "/openapi.json").json()
        return {"version": spec.get("info", {}).get("version"), "source": "GET /openapi.json"}
    except Exception:  # noqa: BLE001 - optional metadata
        return {"version": None, "source": "unavailable"}


def environment(doc, fixtures_sha, args, client, base_url: str) -> dict:
    status = _git("status", "--porcelain")
    parts = base_url.split("/")
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite": doc["suite"],
        "fixtures_file": str(pathlib.Path(args.fixtures).resolve().relative_to(REPO))
        if pathlib.Path(args.fixtures).resolve().is_relative_to(REPO)
        else args.fixtures,
        "fixtures_sha256": fixtures_sha,
        "runner": {
            "orinyx_mcp_version": MCP_VERSION,
            "repo_commit": _git("rev-parse", "HEAD"),
            "working_tree_dirty": bool(status) if status is not None else None,
            "python": sys.version.split()[0],
        },
        "orinyx_api": {
            "origin": "/".join(parts[:3]),
            **engine_info(client),
            "commit": args.engine_commit or os.environ.get("ORINYX_ENGINE_COMMIT") or None,
            "commit_note": "REST gives no commit: pass --engine-commit or ORINYX_ENGINE_COMMIT.",
        },
        "config": {
            "runs_per_fixture": args.runs,
            "max_requests_per_minute": args.max_per_minute,
            "only": args.only,
            "tool_name": TOOL_NAME,
            "identifier_screen": True,
            "scoring": "bucket per classify(); exit codes in the module docstring",
        },
        "determinism": {
            "model_in_verdict_path": False,
            "models_used": [],
            "seed_or_temperature": "not applicable: Orinyx has no model in a verdict (engine "
            "principle 1) and this suite calls no model. Candidate outputs are fixed strings.",
            "variability_measured_by": f"{args.runs} repeated runs per fixture; a fixture is "
            "unstable if any run differs in bucket or in what Orinyx returned.",
        },
    }


# --- report ---------------------------------------------------------------------------

LIMITATIONS = [
    "This suite is one synthetic case family: adult outpatient acute cystitis, based on US "
    "guidance. It is not a clinical validation, a safety certification, or evidence that Orinyx "
    "is ready to release. A pass here proves none of those, and a failure here is not a "
    "finding about any real patient.",
    "The ground truth reflects US guidance (IDSA, FDA labeling, AGS Beers). Other jurisdictions "
    "differ, for example NICE and EAU.",
    "Some fixtures encode real disagreement between sources. They are marked clinician_review "
    "(UTI-001-E) or mixed (UTI-001-H, UTI-001-J) and never count as automated pass or fail on "
    "their review-dependent part.",
    "No clinician has reviewed these fixtures. The citations (including the 2025 and 2026 "
    "items) are carried as supplied and were not independently re-verified by this suite.",
    "Several checks depend on string matching free text, which is fragile: Orinyx matches a "
    "contraindication condition by case-insensitive substring of the label's prose, and the "
    "order grammar reads words such as 'twice daily' against labeled schedules. The "
    "string-sensitivity table shows how much a TRUE_POSITIVE depends on the exact wording. The "
    "harness's own wording of a translated claim is a choice that can move a result.",
    "Where a bucket is a TRUE_POSITIVE through a harness-translated claim, Orinyx did not read "
    "the patient context: the harness did. That shows the check is possible with integrator "
    "work, not that Orinyx finds the problem on its own.",
    "A TRUE_NEGATIVE means no contradicted or unreadable verdict. Orinyx has no 'safe' "
    "classification: an abstain is unchecked, never safe, and a supported verdict is one claim "
    "agreeing with its label, not clearance. Look at orinyx_status_derived and the verdict "
    "counts beside every TRUE_NEGATIVE.",
    "Orinyx status (pass, fail, inconclusive) is derived by this runner from the documented "
    "ruling in orinyx-mcp CLAUDE.md; the engine returns no status field today.",
    "Gaps that matter for a limited developer release: no multi-turn input; no structured "
    "patient context (allergy, renal function, pregnancy, vitals); no citation or evidence "
    "verification; no harm-weighted severity output (only rule-derived minor/moderate/major, "
    "and no CRITICAL); no way to tell 'needs clarification' from 'unsafe' or from 'not "
    "verified'; no escalation (red-flag) check on these endpoints; no antibiogram input; no "
    "duration check; no label-versus-guideline disagreement outcome; knowledge-base gaps for "
    "nitrofurantoin (route rules only), fosfomycin and pivmecillinam (absent).",
    "Results come from one engine at one point in time. The knowledge base is cached label "
    "text; a different engine, knowledge base or label version can change any result.",
    "Orinyx can only evaluate output it is given. There is no Layer A' mode because nothing in "
    "the repo can drive a live agent; no agent output was generated or graded.",
]


def _row(cells) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cells) + " |"


def _verdict_lines(probe: dict, limit: int = 3) -> str:
    if probe["outcome"] != "ok":
        err = probe.get("error", {})
        return f"{probe['outcome']}: {err.get('code')} {err.get('message', '')}".strip()
    lines = [
        f"{v['claim_type']} {v['verdict']}"
        f"{'/' + v['severity'] if v['severity'] != 'none' else ''}: "
        f"{(v['explanation'] or '')[:110]}"
        for v in probe["verdicts"][:limit]
    ]
    extra = len(probe["verdicts"]) - limit
    if extra > 0:
        lines.append(f"(+{extra} more)")
    if probe.get("context_not_evaluated"):
        lines.append("contextNotEvaluated warning present")
    return " ; ".join(lines)


def ranked_gaps(doc: dict, fixtures: dict[str, dict]) -> list[dict]:
    fixture_defs = {f["id"]: f for f in doc["fixtures"]}
    affected: dict[str, dict] = {}
    for fid, v in fixtures.items():
        bucket = v["bucket"] or "UNSTABLE"
        if bucket not in (INCONCLUSIVE, FALSE_NEGATIVE):
            continue
        f = fixture_defs[fid]
        for check in f["checks"]:
            if check["capability"] == "SUPPORTED":
                continue
            for ref in [check["cap_ref"], *check.get("also", [])]:
                entry = affected.setdefault(
                    ref, {"fixtures": set(), "checks": set(), "sev": "NONE"}
                )
                entry["fixtures"].add(fid)
                entry["checks"].add(check["id"])
                sev = f["severity_false_negative"] or f["severity_false_positive"] or "NONE"
                if f["expected_orinyx_detection"]["flag"] is None:
                    sev = miss_severity(f) or "NONE"
                if SEVERITY_WEIGHT.get(sev, 0) > SEVERITY_WEIGHT.get(entry["sev"], 0):
                    entry["sev"] = sev
    rows = []
    for ref, e in affected.items():
        cap = doc["capabilities"][ref]
        rows.append(
            {
                "cap": ref,
                "name": cap["name"],
                "status": cap["status"],
                "highest_severity_affected": e["sev"],
                "fixtures": sorted(e["fixtures"]),
                "checks": sorted(e["checks"]),
                "gap": cap["gap"],
                "recommendation": cap["recommendation"],
            }
        )
    rows.sort(
        key=lambda r: (
            -SEVERITY_WEIGHT.get(r["highest_severity_affected"], 0),
            -len(r["fixtures"]),
            r["cap"],
        )
    )
    return rows


STRING_SENSITIVITY_NOTE = (
    "Wording variants are NOT scored. They show how far a harness-translated TRUE_POSITIVE "
    "depends on the exact condition text."
)


def render_markdown(report: dict, doc: dict, records: list[dict]) -> str:
    s, env = report["summary"], report["environment"]
    fixtures = per_fixture(records)
    fdefs = {f["id"]: f for f in doc["fixtures"]}
    L: list[str] = []
    add = L.append
    add("# Orinyx clinical test script: UTI-001 results")
    add("")
    add(
        "> **Not a clinical validation, a safety certification, or evidence of release readiness.**"
    )
    add("> One synthetic case family, US guidance, no clinician review. See Limitations.")
    add("")
    add("## Run")
    add("")
    for k, v in (
        ("Suite", f"{env['suite']['id']} v{env['suite']['version']}"),
        ("Run at (UTC)", env["timestamp_utc"]),
        ("Runs per fixture", env["config"]["runs_per_fixture"]),
        ("Fixture file", f"{env['fixtures_file']} (sha256 {env['fixtures_sha256'][:16]}...)"),
        (
            "Runner",
            f"orinyx-mcp {env['runner']['orinyx_mcp_version']}, "
            f"commit {env['runner']['repo_commit']}, "
            f"working tree dirty: {env['runner']['working_tree_dirty']}",
        ),
        (
            "Orinyx API",
            f"{env['orinyx_api']['origin']}, engine version {env['orinyx_api']['version']}, "
            f"engine commit {env['orinyx_api']['commit']}",
        ),
        ("Models", "none: no model in the verdict path, none called by this suite"),
        ("Exit code", f"**{s['exit_code']}**: {s['exit_reason']}"),
    ):
        add(f"- **{k}:** {v}")
    add("")

    add("## What this run says")
    add("")
    fc = s["bucket_counts_fixtures_stable"]
    add(
        f"- {s['fixtures']} fixtures x {env['config']['runs_per_fixture']} runs = "
        f"{s['records']} records. "
        f"Unstable fixtures: {', '.join(s['unstable_fixtures']) or 'none'}."
    )
    add("- Stable fixture buckets: " + ", ".join(f"{b} {fc[b]}" for b in BUCKETS) + ".")
    w = s["weighted"]
    add(
        f"- Severity-weighted recall on scored unsafe fixtures: {w['recall_on_scored_unsafe']}. "
        f"Counting unsupported (inconclusive) unsafe checks as missed: "
        f"{w['recall_counting_inconclusive_as_missed']}. Quote the second figure, not the first."
    )
    unsafe = [
        fid
        for fid, f in fdefs.items()
        if fid in fixtures
        and f["review_status"] != "clinician_review"
        and f["expected_orinyx_detection"]["flag"] is True
    ]
    kinds = Counter(fixtures[fid]["bucket"] or "UNSTABLE" for fid in unsafe)
    basis = Counter(
        fixtures[fid]["first"]["classification"].get("detection_basis")
        for fid in unsafe
        if fixtures[fid]["bucket"] == TRUE_POSITIVE
    )
    add(
        f"- Of {len(unsafe)} automated fixtures whose output the brief calls unsafe: "
        + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        + f". TRUE_POSITIVEs by basis: {basis.get('direct', 0)} direct (flagged from the "
        f"candidate output as written), {basis.get('approximation', 0)} approximation (needed a "
        "claim the harness wrote from the patient context)."
    )
    for fid, v in fixtures.items():
        r = v["first"]
        if r["classification"].get("detection_basis") == "approximation":
            variants = [p for p in r["probes"] if p["role"] == "string_sensitivity"]
            hit = [p for p in variants if p["outcome"] == "ok" and p["flagged"]]
            add(
                f"- {fid} was detected through a harness-translated claim; "
                f"{len(hit)} of {len(variants)} wording variants of the same claim were also "
                "flagged (see String sensitivity)."
            )
    add(
        "- Layer A (is the agent output clinically appropriate) is the brief's "
        "`expected_assessment`, unedited and not re-graded. Layer B (did Orinyx classify it "
        "correctly) is what the buckets score."
    )
    if s["critical_false_negatives"]:
        add(f"- **CRITICAL false negatives:** {', '.join(s['critical_false_negatives'])}.")
    if s["critical_checks_not_established"]:
        add(
            f"- **CRITICAL checks Orinyx could not establish (not a pass):** "
            f"{', '.join(s['critical_checks_not_established'])}."
        )
    add("")

    add("## Summary table")
    add("")
    add(_row(["Bucket", "Records", "Fixtures (stable)"]))
    add(_row(["---", "---", "---"]))
    for b in BUCKETS:
        add(_row([b, s["bucket_counts_records"][b], fc[b]]))
    add("")
    add("**By miss severity** (the severity of getting that fixture wrong; stable fixtures)")
    add("")
    add(_row(["Severity", *BUCKETS]))
    add(_row(["---"] * (len(BUCKETS) + 1)))
    for sev, row in s["by_miss_severity"].items():
        add(_row([sev, *(row[b] for b in BUCKETS)]))
    add("")
    add("**By risk category** (a fixture counts once per category it carries)")
    add("")
    add(_row(["Risk category", *BUCKETS]))
    add(_row(["---"] * (len(BUCKETS) + 1)))
    for cat, row in s["by_risk_category"].items():
        add(_row([cat, *(row[b] for b in BUCKETS)]))
    add("")

    add("## Every fixture")
    add("")
    add(
        _row(
            [
                "Fixture",
                "Expected",
                "Miss severity",
                "Review",
                "Capability",
                "Bucket",
                "Stable",
                "Orinyx status (derived)",
                "Basis / reason",
            ]
        )
    )
    add(_row(["---"] * 9))
    for fid, v in fixtures.items():
        r = v["first"]
        c = r["classification"]
        add(
            _row(
                [
                    fid,
                    r["expected_assessment"],
                    r["miss_severity"] or "-",
                    r["review_status"],
                    r["capability_status"],
                    v["bucket"] or "UNSTABLE: " + "/".join(v["buckets"]),
                    "yes" if v["stable"] else "NO",
                    c.get("orinyx_status_derived", "-"),
                    (c.get("detection_basis") + ": " if c.get("detection_basis") else "")
                    + c["reason"],
                ]
            )
        )
    add("")

    def section(title: str, bucket: str, extra: str = "") -> None:
        add(f"## {title}")
        add("")
        items = [(fid, v) for fid, v in fixtures.items() if bucket in v["buckets"]]
        if not items:
            add("None.")
            add("")
            return
        if extra:
            add(extra)
            add("")
        for fid, v in items:
            r = v["first"]
            f = fdefs[fid]
            add(f"### {fid} - {r['bucket']} (miss severity {r['miss_severity']})")
            add("")
            add(
                f"- **Expected:** {f['expected_assessment']}. "
                f"**Pass criteria:** {f['pass_criteria']}"
            )
            add(f"- **Why:** {r['classification']['reason']}")
            add(f"- **Rationale (brief):** {f['evidence_basis']}")
            add(
                f"- **Evidence:** {', '.join(f['evidence_ids'])}. "
                f"**Jurisdiction:** {f['jurisdiction']}. **Review:** {f['review_status']}."
            )
            for p in r["probes"]:
                if p["scored"]:
                    add(
                        f"- **Scored probe {p['probe_id']}** ({p['provenance']}): "
                        f"{_verdict_lines(p)}"
                    )
            add("")

    section(
        "False negatives (Orinyx missed an unsafe output)",
        FALSE_NEGATIVE,
        "`abstained_coverage_gap` = the knowledge base holds no rule for the drug or claim type. "
        "`abstained_other` = abstained for another reason. `partly_supported_no_flag` = some "
        "claims "
        "were SUPPORTED while the real problem was not checked: the most easily misread result.",
    )
    section("False positives (Orinyx flagged a safe output)", FALSE_POSITIVE)

    add("## Inconclusive results (and why)")
    add("")
    add(
        _row(
            ["Fixture", "Miss severity", "Reason", "What Orinyx returned (observation, not scored)"]
        )
    )
    add(_row(["---"] * 4))
    for fid, v in fixtures.items():
        if INCONCLUSIVE in v["buckets"]:
            r = v["first"]
            seen = (
                " || ".join(f"{p['probe_id']}: {_verdict_lines(p, 2)}" for p in r["probes"])
                or "nothing was sent"
            )
            add(_row([fid, r["miss_severity"] or "-", r["classification"]["reason"], seen]))
    add("")
    e = fixtures.get("UTI-001-E")
    if e:
        add("### UTI-001-E: routed to clinician review")
        add("")
        add(
            "The brief's ideal is a caution naming the label-versus-Beers conflict; a caution "
            "or a pass is acceptable; a CRITICAL unsafe flag, or declaring one threshold "
            "'correct', is prohibited. "
            "Orinyx cannot represent a two-source conflict (CAP-12). What it returned:"
        )
        add("")
        for p in e["first"]["probes"]:
            add(f"- {p['probe_id']} ({p['provenance']}): {_verdict_lines(p)}")
        add("")

    add("## Execution errors")
    add("")
    errs = [(fid, v) for fid, v in fixtures.items() if EXECUTION_ERROR in v["buckets"]]
    if not errs:
        add("None.")
    for fid, v in errs:
        add(f"- {fid}: {v['first']['classification']['reason']}")
    add("")

    add("## Pairs: did Orinyx tell the two sides apart?")
    add("")
    add(
        "A TRUE_NEGATIVE on a safe control that gets exactly the output its unsafe pair gets "
        "proves "
        "nothing about either side."
    )
    add("")
    add(_row(["Pair", "Buckets", "Identical Orinyx output on shared probes", "Result"]))
    add(_row(["---"] * 4))
    for p in s["pair_results"]:
        add(
            _row(
                [
                    " vs ".join(p["pair"]),
                    ", ".join(f"{k}: {v}" for k, v in p["buckets"].items()),
                    p["identical_orinyx_output_on_shared_probes"],
                    p["result"],
                ]
            )
        )
    add("")

    add("## String sensitivity (not scored)")
    add("")
    add(STRING_SENSITIVITY_NOTE)
    add("")
    add(_row(["Fixture", "Probe", "Condition text", "Verdict"]))
    add(_row(["---"] * 4))
    for fid, v in fixtures.items():
        for p in v["first"]["probes"]:
            if p["role"] == "string_sensitivity":
                claim = p["sent"][0]
                verdict = p["verdicts"][0]["verdict"] if p["outcome"] == "ok" else p["outcome"]
                add(_row([fid, p["probe_id"], claim["structuredValue"]["condition"], verdict]))
    for fid, v in fixtures.items():
        scored_claims = [p for p in v["first"]["probes"] if p["scored"] and p["kind"] == "claims"]
        for p in scored_claims:
            verdict = p["verdicts"][0]["verdict"] if p["outcome"] == "ok" else p["outcome"]
            add(
                _row(
                    [
                        fid,
                        p["probe_id"] + " (scored)",
                        p["sent"][0]["structuredValue"]["condition"],
                        verdict,
                    ]
                )
            )
    add("")

    add("## What a developer gets by sending the output as written (not scored)")
    add("")
    for fid, v in fixtures.items():
        for p in v["first"]["probes"]:
            if p["probe_id"] == "P0":
                add(f"- {fid} {p['probe_id']}: {_verdict_lines(p)}")
    add("")

    add("## Unsupported and partial checks")
    add("")
    add(_row(["Fixture", "Check", "Capability", "Cap ref", "Note"]))
    add(_row(["---"] * 5))
    for fid, v in fixtures.items():
        for c in v["first"]["checks"]:
            if c["capability"] != "SUPPORTED":
                add(_row([fid, c["id"], c["capability"], c["cap_ref"], c.get("note", "")]))
    add("")

    add("## Capability gaps, ranked by the severity of what they leave unchecked")
    add("")
    for i, g in enumerate(report["ranked_gaps"], 1):
        add(
            f"{i}. **{g['cap']} {g['name']}** ({g['status']}; highest severity affected: "
            f"{g['highest_severity_affected']}; fixtures: {', '.join(g['fixtures'])})"
        )
        add(f"   - Gap: {g['gap']}")
        if g["recommendation"]:
            add(f"   - Recommended: {g['recommendation']}")
    add("")

    add("## Fixtures flagged for clinician review (expected answers were not edited)")
    add("")
    for fid, f in fdefs.items():
        if fid in fixtures and (
            "CLINICIAN REVIEW" in f["evidence_basis"] or f["review_status"] != "automated"
        ):
            add(f"- **{fid}** ({f['review_status']}): {f['evidence_basis']}")
    add("")

    add("## Limitations")
    add("")
    for item in LIMITATIONS:
        add(f"- {item}")
    add("")
    return "\n".join(L)


def build_report(doc, records, env) -> dict:
    fixtures = per_fixture(records)
    return {
        "environment": env,
        "summary": summarize(doc, records),
        "ranked_gaps": ranked_gaps(doc, fixtures),
        "limitations": LIMITATIONS,
        "records": records,
    }


# --- CLI ------------------------------------------------------------------------------


def _client_from_env(url: str, key: str) -> OrinyxClient:
    return OrinyxClient(url, key)


def main(argv: list[str] | None = None, client_factory=_client_from_env) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("lint", "run"):
        p = sub.add_parser(name)
        p.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
        p.add_argument("--map", default=str(DEFAULT_MAP))
    run = sub.choices["run"]
    run.add_argument("--runs", type=int, default=3)
    run.add_argument("--out", default="clinical-suite-results")
    run.add_argument("--only", default=None, help="comma-separated fixture ids")
    run.add_argument("--engine-commit", default=None)
    run.add_argument(
        "--max-per-minute",
        type=int,
        default=50,
        help="request pace; the engine allows 60 per client per minute",
    )
    args = parser.parse_args(argv)

    try:
        doc, sha = load_fixtures(pathlib.Path(args.fixtures))
        map_path = pathlib.Path(args.map)
        problems = lint(doc, map_path.read_text(encoding="utf-8") if map_path.exists() else None)
    except (OSError, FixtureError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    if problems:
        print("fixture lint failed:", file=sys.stderr)
        for line in problems:
            print(f"  - {line}", file=sys.stderr)
        return 1
    if args.command == "lint":
        print(f"ok: {len(doc['fixtures'])} fixtures, {len(doc['capabilities'])} capabilities")
        return 0

    url, key = os.environ.get("ORINYX_API_URL"), os.environ.get("ORINYX_API_KEY")
    if not url or not key:
        print("Set ORINYX_API_URL and ORINYX_API_KEY in the environment.", file=sys.stderr)
        return 1
    if args.runs < 1:
        print("refused: --runs must be at least 1", file=sys.stderr)
        return 1
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    if only and (unknown := [x for x in only if x not in {f["id"] for f in doc["fixtures"]}]):
        print(f"refused: unknown fixture id(s): {', '.join(unknown)}", file=sys.stderr)
        return 1
    try:
        with client_factory(url, key) as client:
            env = environment(doc, sha, args, client, url)
            records = run_suite(
                doc, client, args.runs, only, throttle=Throttle(args.max_per_minute)
            )
    except (OrinyxApiError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1

    report = build_report(doc, records, env)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "results.md").write_text(render_markdown(report, doc, records), encoding="utf-8")
    s = report["summary"]
    print(f"wrote {out / 'results.json'} and {out / 'results.md'}")
    print(
        "stable fixture buckets: "
        + ", ".join(f"{b} {n}" for b, n in s["bucket_counts_fixtures_stable"].items())
    )
    print(f"exit {s['exit_code']}: {s['exit_reason']}")
    return s["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())

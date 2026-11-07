"""The copied engine lists carry a version and are checked against the API's; the tools
split keeps every name; known limits load from data; HTTP clients pool per credential."""

import json
import logging
import re
from importlib import resources

import httpx
import pytest
from orinyx_mcp import cli, contract, copy, screen, tools
from orinyx_mcp.client import LABEL_SECTIONS, LABEL_SECTIONS_SHA256, OrinyxClient
from orinyx_mcp.http import ClientPool, Config

API = "https://api.example"
SET_ID = "0ab7c1d2-1111-4a2b-9c3d-123456789abc"


def _client(handler) -> OrinyxClient:
    return OrinyxClient(API, "ork_live_synthetic", transport=httpx.MockTransport(handler))


def _serving(path: str, status: int, body: dict | None = None):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == path:
            if status == 404:
                return httpx.Response(404, json={"error": {"code": "not_found", "message": ""}})
            return httpx.Response(status, json=body)
        return httpx.Response(200, json={"sectionText": "synthetic", "data": []})

    return handler, seen


# --- versions -------------------------------------------------------------------------------


def test_each_copy_carries_its_own_version():
    assert LABEL_SECTIONS_SHA256 == contract.digest(list(LABEL_SECTIONS))
    assert screen.SCREEN_PATTERNS_SHA256 == contract.digest(screen.pattern_spec())


# --- label sections -------------------------------------------------------------------------


def test_label_sections_not_published_uses_the_copy_once(caplog):
    handler, seen = _serving(contract.LABEL_SECTIONS_PATH, 404)
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert client.label_sections() == LABEL_SECTIONS
        assert client.label_sections() == LABEL_SECTIONS
    assert seen == [contract.LABEL_SECTIONS_PATH]
    assert not caplog.records


def test_label_sections_drift_is_loud_and_the_api_list_is_used(caplog):
    served = [*LABEL_SECTIONS[1:], "adverse_reactions"]
    handler, seen = _serving(contract.LABEL_SECTIONS_PATH, 200, {"sections": served})
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert client.label_sections() == tuple(served)
        assert client.label_section(SET_ID, "adverse_reactions")["sectionText"]
        # Still the copy's names too: the API answers for a section it no longer serves.
        client.label_section(SET_ID, LABEL_SECTIONS[0])
    assert "drifted" in caplog.text
    assert "added: adverse_reactions" in caplog.text
    assert f"removed: {LABEL_SECTIONS[0]}" in caplog.text


def test_label_section_validation_never_sends_a_request():
    handler, seen = _serving(contract.LABEL_SECTIONS_PATH, 200, {"sections": ["x"]})
    with _client(handler) as client:
        with pytest.raises(
            ValueError, match="section must be one of: " + ", ".join(LABEL_SECTIONS)
        ):
            client.label_section(SET_ID, "not_a_section")
    assert seen == []


@pytest.mark.parametrize(
    "body",
    [
        {"sections": ["../audit/export"]},
        {"sections": []},
        {"sections": "warnings"},
        {"sha256": "not-a-digest"},
        {},
    ],
)
def test_a_malformed_sections_answer_falls_back_and_is_not_cached(body, caplog):
    handler, seen = _serving(contract.LABEL_SECTIONS_PATH, 200, body)
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert client.label_sections() == LABEL_SECTIONS
        assert client.label_sections() == LABEL_SECTIONS
    assert len(seen) == 2
    assert "unexpected shape" in caplog.text


def test_a_sections_digest_that_differs_is_loud(caplog):
    handler, _ = _serving(contract.LABEL_SECTIONS_PATH, 200, {"sha256": "0" * 64})
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert client.label_sections() == LABEL_SECTIONS
    assert "drifted" in caplog.text


def test_an_unreachable_api_is_logged_without_the_credential(caplog):
    def handler(request):
        raise httpx.ConnectError("synthetic offline")

    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert client.label_sections() == LABEL_SECTIONS
    assert "unverified" in caplog.text
    assert "ork_live" not in caplog.text


# --- identifier screen ----------------------------------------------------------------------


def _served_patterns(patterns=screen.SCREEN_PATTERNS) -> dict:
    return {
        "patterns": [
            {"name": n, "pattern": s, "flags": f} for n, s, f in screen.pattern_spec(patterns)
        ]
    }


def test_screen_not_published_or_equal_uses_the_copy(caplog):
    for status, body in (
        (404, None),
        (200, _served_patterns()),
        (200, {"sha256": screen.SCREEN_PATTERNS_SHA256}),
    ):
        handler, _ = _serving(contract.SCREEN_PATTERNS_PATH, status, body)
        with _client(handler) as client, caplog.at_level(logging.WARNING):
            assert screen.patterns_for(client) is screen.SCREEN_PATTERNS
    assert not caplog.records


def test_a_stale_screen_uses_the_api_patterns_and_says_so(caplog):
    wider = (*screen.SCREEN_PATTERNS, ("account", re.compile(r"\bACCT-\d+\b")))
    handler, _ = _serving(contract.SCREEN_PATTERNS_PATH, 200, _served_patterns(wider))
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        patterns = screen.patterns_for(client)
    assert screen.pattern_spec(patterns) == screen.pattern_spec(wider)
    assert screen.screen_orders(["ACCT-1234 aspirin 81 mg"], patterns) == "account"
    assert "identifier screen drifted" in caplog.text


def test_a_stale_screen_known_only_by_digest_refuses():
    handler, _ = _serving(contract.SCREEN_PATTERNS_PATH, 200, {"sha256": "0" * 64})
    with (
        _client(handler) as client,
        pytest.raises(screen.StaleScreenError, match="Nothing was sent"),
    ):
        screen.patterns_for(client)


@pytest.mark.parametrize(
    "item",
    [
        {"name": "x", "pattern": "("},
        {"name": "x", "pattern": "a", "flags": 1 << 20},
        {"name": "Bad Name", "pattern": "a"},
        {"pattern": "a"},
    ],
)
def test_a_malformed_screen_answer_keeps_the_copy(item, caplog):
    handler, _ = _serving(contract.SCREEN_PATTERNS_PATH, 200, {"patterns": [item]})
    with _client(handler) as client, caplog.at_level(logging.WARNING):
        assert screen.patterns_for(client) is screen.SCREEN_PATTERNS
    assert "unexpected shape" in caplog.text


@pytest.fixture
def api_env(monkeypatch):
    monkeypatch.setenv("ORINYX_API_URL", API)
    monkeypatch.setenv("ORINYX_API_KEY", "ork_live_synthetic")


def test_observe_works_offline_and_logs_it(api_env, tmp_path, caplog, capsys):
    path = tmp_path / "turn.txt"
    path.write_text("warfarin 5 mg daily\n")
    sent: list[str] = []

    def handler(request):
        if request.url.path == contract.SCREEN_PATTERNS_PATH:
            raise httpx.ConnectError("synthetic offline")
        sent.append(request.url.path)
        return httpx.Response(500, json={"error": {"code": "synthetic", "message": "stop"}})

    with caplog.at_level(logging.WARNING):
        cli.main(["observe", str(path)], client_factory=lambda u, k: _client(handler))
    assert sent  # the copy screened it and the orders went on
    assert "unverified" in caplog.text


def test_observe_refuses_with_the_api_screen_before_sending(api_env, tmp_path, capsys):
    path = tmp_path / "turn.txt"
    path.write_text("ACCT-1234 warfarin 5 mg daily\n")
    wider = (*screen.SCREEN_PATTERNS, ("account", re.compile(r"\bACCT-\d+\b")))
    handler, seen = _serving(contract.SCREEN_PATTERNS_PATH, 200, _served_patterns(wider))
    code = cli.main(["observe", str(path)], client_factory=lambda u, k: _client(handler))
    assert code != cli.EXIT_CLEAN
    assert seen == [contract.SCREEN_PATTERNS_PATH]
    assert "patient identifier (account)" in capsys.readouterr().err


# --- tools split and known limits -------------------------------------------------------------


def test_the_tools_package_keeps_every_name():
    from orinyx_mcp.tools import exams, labels, reports, verify

    assert tools.verify_medications is verify.verify_medications
    assert tools.read_fda_label_section is labels.read_fda_label_section
    assert tools.start_a_test is exams.start_a_test
    assert tools.render_exam_report is reports.render_exam_report
    for name in (
        "HOW_TO_ANSWER",
        "CLAIM_SHAPES",
        "REHEARSAL",
        "CODING_REHEARSAL",
        "CODE_STATUS_WORDS",
    ):
        assert getattr(tools, name) is getattr(copy, name)
    assert all(callable(getattr(tools, name)) for name in tools.__all__)


def test_known_limits_load_from_the_data_file():
    raw = json.loads(resources.files("orinyx_mcp").joinpath("known_limits.json").read_text())
    assert {(i["caseSetId"], i["version"]) for i in raw["limits"]} == set(tools.KNOWN_LIMITS)
    assert tools.KNOWN_LIMITS[("ambient-core", "1.0.0")].startswith("This version does not detect")


def _report(**extra) -> dict:
    return {
        "runId": 7,
        "verdict": "pass",
        "caseSet": {"id": "ambient-core", "version": "1.0.0", "clinicallyReviewed": True},
        "metrics": {},
        "cases": [],
        **extra,
    }


def test_known_limits_from_the_api_take_precedence():
    local = tools.KNOWN_LIMITS[("ambient-core", "1.0.0")]
    assert local in tools.render_exam_report(_report(), 7)
    served = tools.render_exam_report(_report(knownLimits="Served synthetic limit."), 7)
    assert "Served synthetic limit." in served
    assert local not in served


# --- connection reuse -----------------------------------------------------------------------


def _pool(monkeypatch, credential: list[str], seen: list[httpx.Request], **kwargs) -> ClientPool:
    import orinyx_mcp.http as http

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(http, "caller_credential", lambda: credential[0])
    monkeypatch.setattr(
        http,
        "caller_headers",
        lambda config: {"X-Request-Id": "req-1", "Authorization": "Bearer spoofed"},
    )
    monkeypatch.setattr(contract, "check_in_background", lambda client: None)
    config = Config(public_url="https://mcp.example", api_url=API, issuer_url=API)
    return ClientPool(config, transport=httpx.MockTransport(handler), **kwargs)


def test_one_pooled_client_per_credential_never_shared(monkeypatch):
    credential, seen = ["key-a"], []
    pool = _pool(monkeypatch, credential, seen)
    first = pool()
    first.labels("warfarin")
    first.close()
    second = pool()
    assert second._http is first._http
    second.close()
    credential[0] = "key-b"
    other = pool()
    assert other._http is not first._http
    other.labels("warfarin")
    other.close()
    assert [r.headers["Authorization"] for r in seen] == [
        "Bearer key-a",
        "Bearer key-b",
    ]
    assert all(r.headers["X-Request-Id"] == "req-1" for r in seen)
    assert len(pool) == 2
    pool.close()
    assert len(pool) == 0 and first._http.is_closed


def test_idle_clients_beyond_the_cap_are_closed_but_never_one_in_use(monkeypatch):
    credential, seen = ["key-a"], []
    pool = _pool(monkeypatch, credential, seen, max_idle=1)
    busy = pool()
    credential[0] = "key-b"
    idle = pool()
    idle.close()
    credential[0] = "key-c"
    pool().close()
    assert not busy._http.is_closed
    assert idle._http.is_closed
    busy.close()
    pool.close()

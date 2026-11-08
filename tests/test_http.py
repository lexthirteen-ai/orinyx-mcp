"""The network server: who gets in, and whose credential reaches the API.

The endpoint is driven as a remote agent drives it (JSON-RPC over HTTP). The Orinyx API is
a fake that answers `GET /v1/auth/credential`; the REST client is a fake that records what it
was built with. What this file proves is the boundary: this service holds no credential of its
own, admits only what the API vouches for, and forwards the caller, not itself."""

import contextlib
import datetime as dt
import logging

import httpx
import pytest

pytest.importorskip("mcp")

from orinyx_mcp import http as mcp_http  # noqa: E402
from orinyx_mcp.client import OrinyxApiError, VerificationResult  # noqa: E402
from orinyx_mcp.config import Config  # noqa: E402

from tests.test_text import RUN  # noqa: E402

PUBLIC = "https://mcp.example"
API = "https://api.example"
ISSUER = "https://api.example"
GOOD = "ork_live_" + "a" * 43
REVOKED = "ork_live_" + "b" * 43
SIGNED_IN = "ork_oat_" + "c" * 43
ELSEWHERE = "ork_oat_" + "d" * 43  # a sign-in token for another MCP endpoint
SECRET = "a-configured-hop-secret-at-least-32-characters-long"
HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
SUBJECT = "4f0c9f1e-5b1a-4e7e-9d7a-2b0b0a7c1d11"


def _described(token: str) -> dict | None:
    soon = (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat()
    if token == GOOD:
        return {
            "active": True,
            "credentialType": "api_key",
            "scopes": ["verify:read"],
            "expiresAt": None,
            "resource": None,
            "subject": SUBJECT,
            "clientId": "key:77",
            "role": "clinician",
            "orgSlug": "org-a",
            "vendorId": None,
        }
    if token in (SIGNED_IN, ELSEWHERE):
        return {
            "active": True,
            "credentialType": "oauth",
            "scopes": ["benchmark:read", "benchmark:write"],
            "expiresAt": soon,
            "resource": f"{PUBLIC}/mcp" if token == SIGNED_IN else "https://other.example/mcp",
            "subject": SUBJECT,
            "clientId": "client-1",
            "role": "vendor",
            "orgSlug": "org-a",
            "vendorId": 1,
        }
    return None


class FakeApi:
    """The Orinyx API as this service sees it: one endpoint, counted."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == mcp_http.CREDENTIAL_PATH
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        self.calls.append(token)
        self.headers = dict(request.headers)
        body = _described(token)
        if body is None:
            return httpx.Response(401, json={"error": {"code": "unauthorized"}})
        return httpx.Response(200, json=body)


class RecordingClient:
    """Stands in for the REST client; records the credential and headers it was built with."""

    built: list[tuple[str, dict]] = []
    closed = 0

    def __init__(self, credential: str, headers: dict) -> None:
        type(self).built.append((credential, headers))

    def verify(self, claims, **kwargs):
        raise OrinyxApiError(403, "forbidden", "API key scope does not cover this surface.")

    def get_run(self, run_id):
        return VerificationResult.from_json(RUN)

    def accuracy(self, run_id):
        raise OrinyxApiError(404, "not_found", "no review")

    traces: list[tuple[str, list[dict]]] = []
    trace_error: Exception | None = None

    def exam_next_case(self, run_id):
        return {"runId": run_id, "remaining": 1, "case": {"caseId": "amb-003", "vignette": "x"}}

    def exam_submit(self, run_id, answers):
        raise OrinyxApiError(422, "validation", "Case 'nope' is not in the set")

    def exam_trace(self, run_id, calls):
        if type(self).trace_error is not None:
            raise type(self).trace_error
        type(self).traces.append((str(run_id), calls))
        return {"runId": run_id, "recorded": len(calls)}

    def close(self) -> None:
        type(self).closed += 1


def _config(**overrides) -> Config:
    return Config(public_url=PUBLIC, api_url=API, issuer_url=ISSUER, **overrides)


def _rpc(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def _auth(token: str) -> dict:
    return HEADERS | {"Authorization": f"Bearer {token}"}


@contextlib.asynccontextmanager
async def _remote(
    config: Config | None = None, *, api: FakeApi | None = None, client_class=None, gateway=None
):
    config = config or _config()
    api = api or FakeApi()
    client_class = client_class or RecordingClient
    RecordingClient.built, RecordingClient.closed = [], 0
    RecordingClient.traces, RecordingClient.trace_error = [], None
    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    wrapped, app = mcp_http.build_app(
        config,
        client_for=lambda: client_class(
            mcp_http.caller_credential(), mcp_http.caller_headers(config)
        ),
        http=fake_http,
        gateway=gateway,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=wrapped)
        async with httpx.AsyncClient(transport=transport, base_url=PUBLIC) as client:
            client.api = api
            yield client
    await fake_http.aclose()


async def test_no_credential_is_refused_with_a_challenge_naming_the_metadata():
    async with _remote() as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=HEADERS)
        assert response.status_code == 401
        challenge = response.headers["www-authenticate"]
        assert "bearer" in challenge.lower()
        assert f"{PUBLIC}/.well-known/oauth-protected-resource/mcp" in challenge
        assert remote.api.calls == []  # nothing to ask the API about


@pytest.mark.parametrize("credential", [REVOKED, "not-an-orinyx-key", "ork_live_", ELSEWHERE])
async def test_a_dead_or_foreign_credential_is_401_and_reaches_no_tool(credential):
    async with _remote() as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(credential))
        assert response.status_code == 401
        assert RecordingClient.built == []


async def test_a_token_for_another_resource_is_refused_even_though_the_api_vouches():
    async with _remote() as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(ELSEWHERE))
        assert response.status_code == 401
        assert remote.api.calls == [ELSEWHERE]  # it was asked; the answer named another host


async def test_a_live_key_lists_the_tools():
    async with _remote() as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(GOOD))
        assert response.status_code == 200
        names = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert {"verify_medications", "start_a_test", "get_exam_report"} <= names


async def test_a_sign_in_token_for_this_endpoint_is_admitted():
    async with _remote() as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(SIGNED_IN))
        assert response.status_code == 200


async def test_a_tool_call_reaches_the_api_with_the_callers_own_credential_and_address():
    config = _config(hop_secret=SECRET, trust_proxy_forwarded_for=True)
    async with _remote(config) as remote:
        call = _rpc(
            "tools/call", {"name": "get_verification", "arguments": {"run_id": RUN["runId"]}}
        )
        headers = _auth(GOOD) | {
            "X-Forwarded-For": "203.0.113.9, 198.51.100.7",
            "X-Request-ID": "req-123",
        }
        response = await remote.post("/mcp", json=call, headers=headers)
        result = response.json()["result"]
        assert not result.get("isError")
        assert f"Run id: {RUN['runId']}" in result["content"][0]["text"]
        (credential, sent), *_ = RecordingClient.built
        assert credential == GOOD  # never a service credential
        assert sent[mcp_http.LOOPBACK_HEADER] == SECRET
        assert sent[mcp_http.CLIENT_IP_HEADER] == "198.51.100.7"  # rightmost: the proxy's peer
        assert sent[mcp_http.REQUEST_ID_HEADER] == "req-123"
        assert RecordingClient.closed == 1  # one client per call, closed after it


async def test_the_hop_secret_and_the_address_are_sent_only_when_configured():
    async with _remote(_config()) as remote:
        call = _rpc(
            "tools/call", {"name": "get_verification", "arguments": {"run_id": RUN["runId"]}}
        )
        await remote.post("/mcp", json=call, headers=_auth(GOOD))
        (_, sent), *_ = RecordingClient.built
        assert mcp_http.LOOPBACK_HEADER not in sent and mcp_http.CLIENT_IP_HEADER not in sent
        assert sent[mcp_http.REQUEST_ID_HEADER]  # generated when the agent sent none


async def test_a_garbage_forwarded_address_is_not_forwarded():
    config = _config(hop_secret=SECRET, trust_proxy_forwarded_for=True)
    async with _remote(config) as remote:
        call = _rpc(
            "tools/call", {"name": "get_verification", "arguments": {"run_id": RUN["runId"]}}
        )
        await remote.post("/mcp", json=call, headers=_auth(GOOD) | {"X-Forwarded-For": "<x>"})
        (_, sent), *_ = RecordingClient.built
        assert mcp_http.CLIENT_IP_HEADER not in sent


async def test_an_api_refusal_is_a_readable_tool_error_not_a_crash():
    async with _remote() as remote:
        call = _rpc("tools/call", {"name": "verify_medications", "arguments": {"claims": []}})
        response = await remote.post("/mcp", json=call, headers=_auth(GOOD))
        result = response.json()["result"]
        assert result["isError"] is True
        assert "forbidden (403)" in result["content"][0]["text"]


async def test_a_positive_answer_is_cached_a_refusal_is_not():
    async with _remote() as remote:
        for _ in range(3):
            await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(GOOD))
        for _ in range(2):
            await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(REVOKED))
        assert remote.api.calls == [GOOD, REVOKED, REVOKED]


async def test_a_cached_answer_expires():
    now = [1000.0]
    api = FakeApi()
    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    verifier = mcp_http.IntrospectionVerifier(
        API, f"{PUBLIC}/mcp", fake_http, ttl=30.0, clock=lambda: now[0]
    )
    try:
        assert await verifier.verify_token(GOOD) is not None
        now[0] += 10
        assert await verifier.verify_token(GOOD) is not None
        now[0] += 25
        assert await verifier.verify_token(GOOD) is not None
        assert api.calls == [GOOD, GOOD]
        assert await verifier.verify_token("") is None and api.calls == [GOOD, GOOD]
    finally:
        await fake_http.aclose()


async def test_an_unreachable_api_admits_nobody_and_is_logged_without_the_token(caplog):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    verifier = mcp_http.IntrospectionVerifier(API, f"{PUBLIC}/mcp", fake_http)
    caplog.set_level(logging.WARNING, logger="orinyx_mcp")
    try:
        assert await verifier.verify_token(GOOD) is None
    finally:
        await fake_http.aclose()
    assert "credential check failed" in caplog.text and "ConnectError" in caplog.text
    assert GOOD not in caplog.text


async def test_the_bare_mount_path_answers_without_a_redirect():
    async with _remote() as remote:
        for path in ("/mcp", "/mcp/"):
            response = await remote.post(path, json=_rpc("tools/list"), headers=_auth(GOOD))
            assert response.status_code == 200, path
        assert (
            await remote.post("/mcp/mcp", json=_rpc("tools/list"), headers=_auth(GOOD))
        ).status_code == 404


async def test_only_the_public_host_is_accepted():
    async with _remote() as remote:
        for host in ("evil.example", "127.0.0.1:1"):
            response = await remote.post(
                "/mcp", json=_rpc("tools/list"), headers=_auth(GOOD) | {"Host": host}
            )
            assert response.status_code in (400, 403, 421), host
        browser = await remote.post(
            "/mcp",
            json=_rpc("tools/list"),
            headers=_auth(GOOD) | {"Origin": "https://evil.example"},
        )
        assert browser.status_code == 403
        assert RecordingClient.built == []


async def test_the_metadata_names_the_engine_as_issuer():
    async with _remote() as remote:
        response = await remote.get("/.well-known/oauth-protected-resource/mcp")
        assert response.status_code == 200
        document = response.json()
        assert document["resource"].rstrip("/") == f"{PUBLIC}/mcp"
        assert [s.rstrip("/") for s in document["authorization_servers"]] == [ISSUER]
        assert set(document["scopes_supported"]) == set(mcp_http.SCOPES)
        # A connector requests exactly these and the engine narrows to the request, so the
        # Arena tools are reachable through a connector only if their scopes are listed.
        assert {"arena:read", "arena:write"} <= set(document["scopes_supported"])


@pytest.mark.parametrize("commit_sha", ["a" * 40, None, ""])
async def test_health_answers_without_a_credential_and_every_response_is_hardened(
    monkeypatch, commit_sha
):
    from orinyx_mcp import __version__

    if commit_sha is None:
        monkeypatch.delenv("ORINYX_COMMIT_SHA", raising=False)
    else:
        monkeypatch.setenv("ORINYX_COMMIT_SHA", commit_sha)
    async with _remote() as remote:
        response = await remote.get("/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "service": "orinyx-mcp",
            "version": __version__,
            "commitSha": commit_sha or None,
        }
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "max-age" in response.headers["strict-transport-security"]


async def test_the_bearer_never_appears_in_a_log_line(caplog):
    caplog.set_level(logging.DEBUG)
    async with _remote() as remote:
        await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(GOOD))
        await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(REVOKED))
    assert GOOD not in caplog.text and REVOKED not in caplog.text


def test_building_the_server_leaves_the_process_logging_alone():
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    root.handlers[:] = []
    try:
        mcp_http.build_app(_config())
        assert root.handlers == [] and root.level == level
    finally:
        root.handlers[:] = saved
        root.setLevel(level)


def test_the_verifier_refuses_to_run_before_the_lifespan_opened_its_client():
    verifier = mcp_http.IntrospectionVerifier(API, f"{PUBLIC}/mcp")
    import asyncio

    with pytest.raises(RuntimeError, match="lifespan"):
        asyncio.run(verifier.verify_token(GOOD))


async def test_a_trusted_client_ip_header_names_the_caller_behind_the_edge():
    """Fly puts the caller in Fly-Client-IP; the rightmost X-Forwarded-For entry is the edge
    proxy itself (first live access log, 2026-10-06)."""
    config = _config(
        hop_secret=SECRET, trust_proxy_forwarded_for=True, trusted_client_ip_header="fly-client-ip"
    )
    async with _remote(config) as remote:
        call = _rpc(
            "tools/call", {"name": "get_verification", "arguments": {"run_id": RUN["runId"]}}
        )
        headers = _auth(GOOD) | {
            "X-Forwarded-For": "203.0.113.9, 66.241.125.101",
            "Fly-Client-IP": "203.0.113.9",
        }
        await remote.post("/mcp", json=call, headers=headers)
        (_, sent), *_ = RecordingClient.built
        assert sent[mcp_http.CLIENT_IP_HEADER] == "203.0.113.9"


async def test_the_credential_check_itself_carries_the_hop_headers():
    """The API logs the check too: it must be attributed to the agent, not this Machine."""
    config = _config(hop_secret=SECRET, trust_proxy_forwarded_for=True)
    async with _remote(config) as remote:
        headers = _auth(GOOD) | {"X-Forwarded-For": "198.51.100.7", "X-Request-ID": "req-9"}
        await remote.post("/mcp", json=_rpc("tools/list"), headers=headers)
        seen = remote.api.headers
        assert seen[mcp_http.LOOPBACK_HEADER] == SECRET
        assert seen[mcp_http.CLIENT_IP_HEADER] == "198.51.100.7"
        assert seen[mcp_http.REQUEST_ID_HEADER] == "req-9"
        assert seen["authorization"] == f"Bearer {GOOD}"


async def test_a_products_exam_call_posts_one_trace_row_with_the_same_credential():
    """Behaviour exams, stage 1b: a vendor-role sign-in sitting an exam leaves one trace row
    per exam tool call, posted by this service with the caller's own credential and the hop
    headers (the API accepts it on the hop alone); the tool's answer is unchanged."""
    config = _config(hop_secret=SECRET)
    async with _remote(config) as remote:
        call = _rpc("tools/call", {"name": "get_next_exam_case", "arguments": {"run_id": 12}})
        response = await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
        result = response.json()["result"]
        assert not result.get("isError") and "amb-003" in result["content"][0]["text"]
        [(run_id, [row])] = RecordingClient.traces
        assert run_id == "12" and row["tool"] == "get_next_exam_case"
        assert row["caseId"] == "amb-003" and row["outcome"] == "ok"
        assert row["requestBytes"] > 0 and row["responseBytes"] > 0 and row["durationMs"] >= 0
        (credential, sent), *_ = RecordingClient.built
        assert credential == SIGNED_IN and sent[mcp_http.LOOPBACK_HEADER] == SECRET
        assert RecordingClient.closed == 1  # the trace rode on the call's own client


async def test_a_refused_exam_call_is_traced_as_refused_with_its_code():
    async with _remote(_config(hop_secret=SECRET)) as remote:
        call = _rpc(
            "tools/call",
            {
                "name": "submit_exam_answers",
                "arguments": {"run_id": 12, "answers": [{"caseId": "nope", "claims": []}]},
            },
        )
        response = await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
        assert response.json()["result"].get("isError")  # the refusal still reaches the agent
        [(_, [row])] = RecordingClient.traces
        assert row["outcome"] == "refused" and row["refusalCode"] == "validation"
        assert row["caseId"] == "nope"


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("get_next_exam_case", {"run_id": 12}),
        ("get_exam_cases", {"run_id": 12}),
        (
            "submit_exam_answers",
            {"run_id": 12, "answers": [{"caseId": "amb-003", "claims": []}]},
        ),
        ("finish_exam", {"run_id": 12}),
    ],
)
async def test_exam_retries_add_trace_rows_and_are_not_advertised_as_idempotent(tool, arguments):
    finished = False
    submitted = False

    class RetryClient(RecordingClient):
        def exam_cases(self, run_id):
            return {"runId": run_id, "cases": [{"caseId": "amb-003", "vignette": "x"}]}

        def exam_submit(self, run_id, answers):
            nonlocal submitted
            result = [{"caseId": "amb-003", "cached": submitted}]
            submitted = True
            return result

        def exam_finish(self, run_id, allow_partial=False):
            nonlocal finished
            if finished:
                raise OrinyxApiError(409, "conflict", "This sitting is already finished")
            finished = True
            return {"id": run_id, "status": "completed"}

    async with _remote(_config(hop_secret=SECRET), client_class=RetryClient) as remote:
        response = await remote.post("/mcp", json=_rpc("tools/list"), headers=_auth(SIGNED_IN))
        listed = {item["name"]: item for item in response.json()["result"]["tools"]}
        call = _rpc("tools/call", {"name": tool, "arguments": arguments})
        for attempt in range(2):
            response = await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
            result = response.json()["result"]
            assert bool(result.get("isError")) == (tool == "finish_exam" and attempt == 1)
            if tool == "submit_exam_answers" and attempt == 1:
                assert "already been recorded unchanged" in result["content"][0]["text"]

        assert len(RecordingClient.traces) == 2
        rows = []
        for run_id, calls in RecordingClient.traces:
            assert run_id == "12" and len(calls) == 1
            assert calls[0]["tool"] == tool
            rows.extend(calls)
        assert [row["outcome"] for row in rows] == [
            "ok",
            "refused" if tool == "finish_exam" else "ok",
        ]
        if tool == "finish_exam":
            assert rows[1]["refusalCode"] == "conflict"
        assert listed[tool]["annotations"]["idempotentHint"] is False


async def test_an_unexpected_failure_is_traced_as_an_error_and_still_raised(caplog):
    """A failure that is neither an API refusal nor an argument error leaves a trace row too,
    and the warning names the post's status."""

    class Broken(RecordingClient):
        def exam_next_case(self, run_id):
            raise RuntimeError("boom")

    async with _remote(_config(hop_secret=SECRET), client_class=Broken) as remote:
        call = _rpc("tools/call", {"name": "get_next_exam_case", "arguments": {"run_id": 12}})
        response = await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
        assert response.json()["result"].get("isError")
        [(_, [row])] = RecordingClient.traces
        assert row["outcome"] == "error" and row["refusalCode"] == "RuntimeError"
        RecordingClient.traces.clear()
        RecordingClient.trace_error = OrinyxApiError(429, "rate_limited", "slow down")
        with caplog.at_level(logging.WARNING, logger="orinyx_mcp.trace"):
            await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
        assert any("429" in r.message for r in caplog.records)


async def test_a_testers_quick_check_leaves_no_trace_and_a_failed_post_changes_nothing(caplog):
    async with _remote(_config(hop_secret=SECRET)) as remote:
        call = _rpc("tools/call", {"name": "get_next_exam_case", "arguments": {"run_id": 12}})
        await remote.post("/mcp", json=call, headers=_auth(GOOD))  # a clinician, not a product
        assert RecordingClient.traces == []
        RecordingClient.trace_error = OrinyxApiError(403, "forbidden", "not on the hop")
        with caplog.at_level(logging.WARNING, logger="orinyx_mcp.trace"):
            response = await remote.post("/mcp", json=call, headers=_auth(SIGNED_IN))
        result = response.json()["result"]
        assert not result.get("isError") and "amb-003" in result["content"][0]["text"]
        assert RecordingClient.traces == []
        assert any("trace not recorded" in r.message for r in caplog.records)

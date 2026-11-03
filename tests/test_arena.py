"""Arena adapter contract tests. Mock responses are not a deployed Arena engine."""

import json
import uuid

import httpx
import pytest
from orinyx_mcp.arena import get_battle, get_report, start_challenge, start_rematch, submit_answer
from orinyx_mcp.client import OrinyxApiError, OrinyxClient

BATTLE = "97e5f2f9-0f10-471e-8bdd-5ac4a1438746"
ATTEMPT = "55c63637-e34a-4213-b7b3-2f311962e2da"
REQUEST = "bb2bb8be-80a0-4eb7-b041-4d65564d9d74"
PACKET = {"id": "EGH-001", "version": "1", "claim": "Synthetic claim", "source": "Synthetic source"}
INPUT_HASH = "a" * 64


def _client(handler):
    return OrinyxClient(
        "https://api.orinyx.example", "ork_live_test", transport=httpx.MockTransport(handler)
    )


def test_start_uses_authenticated_api_and_never_places_credential_in_url():
    captured = {}

    def handler(request):
        captured.update(
            path=request.url.path,
            body=json.loads(request.content),
            auth=request.headers["Authorization"],
        )
        return httpx.Response(
            201,
            json={
                "battleId": BATTLE,
                "attemptId": ATTEMPT,
                "challenge": PACKET,
                "inputHash": INPUT_HASH,
                "status": "open",
            },
        )

    data = json.loads(
        start_challenge(
            _client(handler),
            challenge_id="EGH-001",
            context="source",
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )
    )
    assert captured["path"] == "/v1/arena/battles"
    assert captured["body"] == {
        "challengeId": "EGH-001",
        "context": "source",
        "idempotencyKey": REQUEST,
    }
    assert captured["auth"] == "Bearer ork_live_test"
    assert data["spectatorUrl"] == f"https://arena.orinyx.example/arena/{BATTLE}/spectate"
    assert "ork_live" not in json.dumps(data)
    assert data["challenge"] == PACKET
    assert data["inputHash"] == INPUT_HASH


def test_start_without_dashboard_returns_challenge_without_spectator_url():
    def handler(_request):
        return httpx.Response(
            201,
            json={
                "battleId": BATTLE,
                "attemptId": ATTEMPT,
                "challenge": PACKET,
                "inputHash": INPUT_HASH,
                "status": "open",
            },
        )

    data = json.loads(
        start_challenge(
            _client(handler), challenge_id="EGH-001", context="source", request_id=REQUEST
        )
    )
    assert data["battleId"] == BATTLE
    assert "spectatorUrl" not in data


def test_submit_preserves_answer_and_retry_key_without_local_grading():
    captured = {}

    def handler(request):
        captured.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(
            202, json={"battleId": BATTLE, "attemptId": ATTEMPT, "status": "received", "cursor": 2}
        )

    answer = "I cannot establish that all 24 statements were checked."
    data = json.loads(
        submit_answer(
            _client(handler),
            battle_id=BATTLE,
            attempt_id=ATTEMPT,
            answer=answer,
            request_id=REQUEST,
        )
    )
    assert captured["path"] == f"/v1/arena/battles/{BATTLE}/attempts/{ATTEMPT}/answer"
    assert captured["body"] == {"answer": answer, "idempotencyKey": REQUEST}
    assert data["status"] == "received"
    assert "verdict" not in data


def test_rematch_preserves_parent_identity_and_credential_free_url():
    next_battle = str(uuid.uuid4())
    next_attempt = str(uuid.uuid4())
    captured = {}

    def handler(request):
        captured.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(
            201,
            json={
                "battleId": next_battle,
                "parentBattleId": BATTLE,
                "attemptId": next_attempt,
                "challenge": PACKET,
                "inputHash": INPUT_HASH,
                "status": "open",
            },
        )

    data = json.loads(
        start_rematch(
            _client(handler),
            battle_id=BATTLE,
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )
    )
    assert captured == {
        "path": f"/v1/arena/battles/{BATTLE}/rematches",
        "body": {"idempotencyKey": REQUEST},
    }
    assert data["parentBattleId"] == BATTLE and data["battleId"] == next_battle
    assert data["spectatorUrl"] == f"https://arena.orinyx.example/arena/{next_battle}/spectate"
    assert "ork_live" not in json.dumps(data)

    without_dashboard = json.loads(
        start_rematch(_client(handler), battle_id=BATTLE, request_id=REQUEST)
    )
    assert without_dashboard["battleId"] == next_battle
    assert "spectatorUrl" not in without_dashboard

    def wrong_parent(_request):
        return httpx.Response(
            200,
            json={
                "battleId": next_battle,
                "parentBattleId": str(uuid.uuid4()),
                "attemptId": next_attempt,
                "challenge": PACKET,
                "inputHash": INPUT_HASH,
            },
        )

    with pytest.raises(OrinyxApiError, match="parent identity mismatch"):
        start_rematch(
            _client(wrong_parent),
            battle_id=BATTLE,
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )

    def closed_rematch(_request):
        return httpx.Response(
            200,
            json={
                "battleId": next_battle,
                "parentBattleId": BATTLE,
                "attemptId": next_attempt,
                "challenge": PACKET,
                "inputHash": INPUT_HASH,
                "status": "completed",
            },
        )

    with pytest.raises(OrinyxApiError, match="unexpected rematch status"):
        start_rematch(
            _client(closed_rematch),
            battle_id=BATTLE,
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )


def test_snapshot_and_report_are_engine_reads_without_client_reinterpretation():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/report"):
            return httpx.Response(
                200,
                json={
                    "battleId": BATTLE,
                    "status": "completed",
                    "outcome": "insufficient_evidence",
                    "unchecked": ["original sources"],
                },
            )
        return httpx.Response(
            200, json={"battleId": BATTLE, "status": "open", "cursor": 3, "attempts": []}
        )

    client = _client(handler)
    assert json.loads(get_battle(client, battle_id=BATTLE))["cursor"] == 3
    assert json.loads(get_report(client, battle_id=BATTLE))["unchecked"] == ["original sources"]
    assert paths == [f"/v1/arena/battles/{BATTLE}", f"/v1/arena/battles/{BATTLE}/report"]


def test_bad_ids_urls_and_unapproved_challenges_never_make_request():
    def handler(_):
        pytest.fail("invalid input reached API")

    client = _client(handler)
    for bad in ("../audit", "not-a-uuid", "", True):
        with pytest.raises(ValueError):
            get_battle(client, battle_id=bad)
    with pytest.raises(ValueError):
        start_challenge(
            client,
            challenge_id="ORX-FREQ-001",
            context="source",
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )
    with pytest.raises(ValueError):
        start_challenge(
            client,
            challenge_id="EGH-001",
            context="source",
            request_id=REQUEST,
            spectator_origin="https://user:secret@arena.orinyx.example",
        )
    with pytest.raises(ValueError):
        submit_answer(client, battle_id=BATTLE, attempt_id=ATTEMPT, answer=" ", request_id=REQUEST)
    with pytest.raises(ValueError):
        submit_answer(
            client, battle_id=BATTLE, attempt_id=ATTEMPT, answer="x" * 16001, request_id=REQUEST
        )


def test_mismatched_engine_identity_and_packet_are_rejected():
    other = str(uuid.uuid4())

    def wrong_receipt(_):
        return httpx.Response(
            202, json={"battleId": other, "attemptId": ATTEMPT, "status": "received"}
        )

    with pytest.raises(OrinyxApiError, match="identity mismatch"):
        submit_answer(
            _client(wrong_receipt),
            battle_id=BATTLE,
            attempt_id=ATTEMPT,
            answer="Synthetic answer",
            request_id=REQUEST,
        )

    def wrong_packet(_):
        return httpx.Response(
            201,
            json={
                "battleId": BATTLE,
                "attemptId": ATTEMPT,
                "challenge": {"id": "different", "version": "1"},
            },
        )

    with pytest.raises(OrinyxApiError, match="mismatched challenge"):
        start_challenge(
            _client(wrong_packet),
            challenge_id="EGH-001",
            context="source",
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )


def test_start_rejects_missing_input_hash_and_submit_accepts_terminal_failure():
    def missing_hash(_):
        return httpx.Response(
            201,
            json={
                "battleId": BATTLE,
                "attemptId": ATTEMPT,
                "challenge": PACKET,
                "status": "open",
            },
        )

    with pytest.raises(OrinyxApiError, match="input hash"):
        start_challenge(
            _client(missing_hash),
            challenge_id="EGH-001",
            context="source",
            request_id=REQUEST,
            spectator_origin="https://arena.orinyx.example",
        )

    def failed(_):
        return httpx.Response(
            202,
            json={
                "battleId": BATTLE,
                "attemptId": ATTEMPT,
                "status": "failed",
                "cursor": 6,
            },
        )

    receipt = submit_answer(
        _client(failed),
        battle_id=BATTLE,
        attempt_id=ATTEMPT,
        answer="synthetic answer",
        request_id=REQUEST,
    )
    assert json.loads(receipt)["status"] == "failed"


def test_existing_tool_list_is_unchanged_by_default_and_flag_registers_arena(monkeypatch):
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server

    arena_names = {
        "start_arena_challenge",
        "start_arena_rematch",
        "submit_arena_answer",
        "get_arena_battle",
        "get_arena_report",
    }
    monkeypatch.delenv("ORINYX_ARENA_ENABLED", raising=False)
    plain = build_server(lambda: None)
    plain_names = {tool.name for tool in plain._tool_manager.list_tools()}
    assert plain_names.isdisjoint(arena_names)
    monkeypatch.setenv("ORINYX_ARENA_ENABLED", "true")
    monkeypatch.setenv("ORINYX_ARENA_URL", "https://arena.orinyx.example")
    ready = build_server(lambda: None)
    ready_names = {tool.name for tool in ready._tool_manager.list_tools()}
    assert ready_names - plain_names == arena_names
    monkeypatch.delenv("ORINYX_ARENA_URL")
    no_dashboard = build_server(lambda: None)
    no_dashboard_names = {tool.name for tool in no_dashboard._tool_manager.list_tools()}
    assert no_dashboard_names - plain_names == arena_names

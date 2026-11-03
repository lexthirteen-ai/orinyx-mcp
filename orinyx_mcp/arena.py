"""Arena MCP adapter. Arena results and events come only from the engine API, and they are
never clinical verdicts: every engine result says so (`clinicalVerdict: false`,
`domain: "arena_source_challenge"`), and a rematch says `firstSitting: false`.

This module is dormant until ORINYX_ARENA_ENABLED=true and a real Arena API is
available. It never invokes an arbitrary local agent: the MCP host's active agent
calls these tools itself. No local grading, battle persistence, or fabricated events.
"""

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from orinyx_mcp.client import OrinyxApiError, OrinyxClient
from orinyx_mcp.config import ConfigError, split_config_url

CHALLENGES = frozenset({"EGH-001"})
CONTEXTS = frozenset({"source"})
_MAX_ANSWER = 16_000


def _uuid(value: str, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError(f"{label} must be a UUID") from None


def _spectator_origin(value: str) -> str:
    parts = split_config_url(value, "ORINYX_ARENA_URL")
    local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
    if not parts.hostname or (parts.scheme != "https" and not (parts.scheme == "http" and local)):
        raise ConfigError("ORINYX_ARENA_URL must be an https origin (http only for localhost)")
    if parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ConfigError("ORINYX_ARENA_URL must be an origin without credentials or a path")
    return f"{parts.scheme}://{parts.netloc}"


def _object(client: OrinyxClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    return client._json_object(client._request(method, path, **kwargs))


def _identity(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    try:
        return _uuid(value, key)
    except ValueError:
        raise OrinyxApiError(200, "invalid_response", f"missing or invalid {key}") from None


def _encoded(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def start_challenge(
    client: OrinyxClient,
    *,
    challenge_id: str,
    context: str,
    request_id: str,
    spectator_origin: str = "",
) -> str:
    if challenge_id not in CHALLENGES:
        raise ValueError("challenge_id must be EGH-001 for this prototype adapter")
    if context not in CONTEXTS:
        raise ValueError("context must be source for EGH-001")
    request_id = _uuid(request_id, "request_id")
    origin = _spectator_origin(spectator_origin) if spectator_origin else None
    data = _object(
        client,
        "POST",
        "/v1/arena/battles",
        json={
            "challengeId": challenge_id,
            "context": context,
            "idempotencyKey": request_id,
        },
    )
    battle_id = _identity(data, "battleId")
    attempt_id = _identity(data, "attemptId")
    packet = data.get("challenge")
    if (
        not isinstance(packet, dict)
        or packet.get("id") != challenge_id
        or not isinstance(packet.get("version"), str)
        or not packet.get("version")
    ):
        raise OrinyxApiError(200, "invalid_response", "missing or mismatched challenge packet")
    if data.get("status") not in {"open", "completed"}:
        raise OrinyxApiError(200, "invalid_response", "missing or invalid battle status")
    input_hash = data.get("inputHash")
    if not isinstance(input_hash, str) or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None:
        raise OrinyxApiError(200, "invalid_response", "missing or invalid challenge input hash")
    result = {
        "battleId": battle_id,
        "attemptId": attempt_id,
        "challenge": packet,
        "inputHash": input_hash,
        "status": data["status"],
    }
    # A browser preview is optional. No API credential is embedded in its URL.
    if origin:
        result["spectatorUrl"] = f"{origin}/arena/{battle_id}/spectate"
    return _encoded(result)


def submit_answer(
    client: OrinyxClient,
    *,
    battle_id: str,
    attempt_id: str,
    answer: str,
    request_id: str,
) -> str:
    battle_id = _uuid(battle_id, "battle_id")
    attempt_id = _uuid(attempt_id, "attempt_id")
    request_id = _uuid(request_id, "request_id")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > _MAX_ANSWER:
        raise ValueError("answer must be 1 to 16000 characters")
    data = _object(
        client,
        "POST",
        f"/v1/arena/battles/{battle_id}/attempts/{attempt_id}/answer",
        json={
            "answer": answer,
            "idempotencyKey": request_id,
        },
    )
    if _identity(data, "battleId") != battle_id or _identity(data, "attemptId") != attempt_id:
        raise OrinyxApiError(200, "invalid_response", "answer receipt identity mismatch")
    if data.get("status") not in {"received", "evaluating", "resolved", "failed", "expired"}:
        raise OrinyxApiError(200, "invalid_response", "unexpected answer receipt status")
    return _encoded(data)


def start_rematch(
    client: OrinyxClient, *, battle_id: str, request_id: str, spectator_origin: str = ""
) -> str:
    battle_id = _uuid(battle_id, "battle_id")
    request_id = _uuid(request_id, "request_id")
    origin = _spectator_origin(spectator_origin) if spectator_origin else None
    data = _object(
        client,
        "POST",
        f"/v1/arena/battles/{battle_id}/rematches",
        json={"idempotencyKey": request_id},
    )
    new_id = _identity(data, "battleId")
    attempt_id = _identity(data, "attemptId")
    if new_id == battle_id or _identity(data, "parentBattleId") != battle_id:
        raise OrinyxApiError(200, "invalid_response", "rematch parent identity mismatch")
    packet = data.get("challenge")
    if (
        not isinstance(packet, dict)
        or packet.get("id") != "EGH-001"
        or not isinstance(packet.get("version"), str)
        or not packet["version"]
    ):
        raise OrinyxApiError(200, "invalid_response", "missing rematch challenge packet")
    if data.get("status") != "open":
        raise OrinyxApiError(200, "invalid_response", "unexpected rematch status")
    input_hash = data.get("inputHash")
    if not isinstance(input_hash, str) or re.fullmatch(r"[0-9a-f]{64}", input_hash) is None:
        raise OrinyxApiError(200, "invalid_response", "missing rematch input hash")
    result = {
        "battleId": new_id,
        "parentBattleId": battle_id,
        "attemptId": attempt_id,
        "challenge": packet,
        "inputHash": input_hash,
        "status": data.get("status"),
    }
    if origin:
        result["spectatorUrl"] = f"{origin}/arena/{new_id}/spectate"
    return _encoded(result)


def get_battle(client: OrinyxClient, *, battle_id: str) -> str:
    battle_id = _uuid(battle_id, "battle_id")
    data = _object(client, "GET", f"/v1/arena/battles/{battle_id}")
    if (
        _identity(data, "battleId") != battle_id
        or isinstance(data.get("cursor"), bool)
        or not isinstance(data.get("cursor"), int)
        or data["cursor"] < 0
    ):
        raise OrinyxApiError(200, "invalid_response", "unexpected battle snapshot")
    return _encoded(data)


def get_report(client: OrinyxClient, *, battle_id: str) -> str:
    battle_id = _uuid(battle_id, "battle_id")
    data = _object(client, "GET", f"/v1/arena/battles/{battle_id}/report")
    if _identity(data, "battleId") != battle_id or not isinstance(data.get("status"), str):
        raise OrinyxApiError(200, "invalid_response", "unexpected battle report")
    return _encoded(data)


def register_arena_tools(
    server: Any, client_for: Callable[[], OrinyxClient], spectator_origin: str = ""
) -> None:
    """Register only after deployment explicitly enables the Arena endpoint contract."""
    if spectator_origin:
        _spectator_origin(spectator_origin)
    from orinyx_mcp.server import _calling

    @server.tool()
    def start_arena_challenge(challenge_id: str, context: str, request_id: str) -> str:
        """Start a synthetic Arena challenge for this MCP host's active agent. Provide a
        stable UUID request_id and reuse it on retries. Returns the challenge and a browser
        spectator URL when configured. This prototype allows only EGH-001 with source context."""
        with _calling(client_for) as client:
            return start_challenge(
                client,
                challenge_id=challenge_id,
                context=context,
                request_id=request_id,
                spectator_origin=spectator_origin,
            )

    @server.tool()
    def submit_arena_answer(battle_id: str, attempt_id: str, answer: str, request_id: str) -> str:
        """Submit this host agent's raw synthetic response. Reuse request_id on retry.
        Receipt is not a verdict; the engine evaluates independently."""
        with _calling(client_for) as client:
            return submit_answer(
                client,
                battle_id=battle_id,
                attempt_id=attempt_id,
                answer=answer,
                request_id=request_id,
            )

    @server.tool()
    def start_arena_rematch(battle_id: str, request_id: str) -> str:
        """Start a linked rematch after the prior agent attempt resolves, fails, or expires.
        Reuse the same UUID request_id on retries. Original records stay intact."""
        with _calling(client_for) as client:
            return start_rematch(
                client,
                battle_id=battle_id,
                request_id=request_id,
                spectator_origin=spectator_origin,
            )

    @server.tool()
    def get_arena_battle(battle_id: str) -> str:
        """Read the engine's authorized battle snapshot and event cursor."""
        with _calling(client_for) as client:
            return get_battle(client, battle_id=battle_id)

    @server.tool()
    def get_arena_report(battle_id: str) -> str:
        """Read the engine's authoritative Arena report after evaluation."""
        with _calling(client_for) as client:
            return get_report(client, battle_id=battle_id)

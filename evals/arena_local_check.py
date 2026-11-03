"""An end-to-end Arena acceptance check from a REAL MCP client, against a LOCAL stack.

    ORINYX_API_URL=http://localhost:8766 ORINYX_API_KEY=... \\
    ORINYX_ARENA_URL=http://localhost:3000 \\
        python evals/arena_local_check.py [--outsider-key-env NAME] [--db-url URL]

It launches `python -m orinyx_mcp` over stdio with the Arena tools on, then:

1. lists the tools and requires the five Arena tools;
2. starts EGH-001 with context `source` and requires a battle id, an attempt id and a
   spectator URL on ORINYX_ARENA_URL;
3. reads the battle back through the MCP tool;
4. submits one structured answer and reads the receipt status;
5. reads the battle's events over REST with the same key and requires strictly increasing
   sequence numbers that start at the battle's creation;
6. with `--outsider-key-env`, requires the same battle to be a 404 for a key of another
   organization (or one off the tester list);
7. with `--db-url`, requires the battle row to exist and the clinical tables
   (`verdicts`, `verification_runs`) to be unchanged by the whole check.

A local stack only: every run starts a battle, and `--db-url` reads the database. Keys are read
from the environment and never printed. Nothing here imports the engine. Exit 0 when every
step answered as expected, 1 otherwise.
"""

import argparse
import asyncio
import json
import os
import sys
import uuid

import httpx

ARENA_TOOLS = {
    "start_arena_challenge",
    "submit_arena_answer",
    "start_arena_rematch",
    "get_arena_battle",
    "get_arena_report",
}
ANSWER = {
    "assessment": "uncertain",
    "citedLines": ["04"],
    "missingEvidence": ["a comparison of the statements with their original sources"],
    "rationale": "Acceptance-check answer: the source describes a formatting check only.",
}
CLINICAL_TABLES = ("verdicts", "verification_runs")


def _failed(result) -> bool:
    return bool(result.is_error)


def _text(result) -> str:
    return "\n".join(getattr(part, "text", "") for part in result.content)


def _counts(db_url: str) -> dict[str, int]:
    import psycopg  # optional: only the --db-url leg needs it

    with psycopg.connect(db_url) as conn:
        return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in CLINICAL_TABLES}


def _battle_rows(db_url: str, battle_id: str) -> int:
    import psycopg

    with psycopg.connect(db_url) as conn:
        return conn.execute(
            "select count(*) from arena_battles where id = %s", (battle_id,)
        ).fetchone()[0]


async def check(outsider_key_env: str | None, db_url: str | None) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    api_url = os.environ["ORINYX_API_URL"].rstrip("/")
    api_key = os.environ["ORINYX_API_KEY"]
    arena_url = os.environ["ORINYX_ARENA_URL"].rstrip("/")
    env = dict(os.environ, ORINYX_ARENA_ENABLED="true")
    params = StdioServerParameters(command=sys.executable, args=["-m", "orinyx_mcp"], env=env)
    before = _counts(db_url) if db_url else None
    ok = True

    def step(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"{'PASS' if passed else 'FAIL'}  {name}{('  ' + detail) if detail else ''}")

    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {tool.name for tool in (await session.list_tools()).tools}
        step("1 Arena tools listed", ARENA_TOOLS <= tools, ", ".join(sorted(ARENA_TOOLS & tools)))

        started = await session.call_tool(
            "start_arena_challenge",
            {"challenge_id": "EGH-001", "context": "source", "request_id": str(uuid.uuid4())},
        )
        if _failed(started):
            step("2 start_arena_challenge", False, _text(started)[:200])
            return 1
        battle = json.loads(_text(started))
        battle_id, attempt_id = battle.get("battleId"), battle.get("attemptId")
        spectator = battle.get("spectatorUrl", "")
        step(
            "2 battle started",
            bool(battle_id and attempt_id) and battle.get("status") in {"open", "completed"},
            f"battle {battle_id} status {battle.get('status')}",
        )
        step(
            "2 spectator URL",
            spectator == f"{arena_url}/arena/{battle_id}/spectate",
            spectator,
        )

        read_back = await session.call_tool("get_arena_battle", {"battle_id": battle_id})
        step(
            "3 get_arena_battle", not _failed(read_back), _text(read_back)[:120].replace("\n", " ")
        )

        answered = await session.call_tool(
            "submit_arena_answer",
            {
                "battle_id": battle_id,
                "attempt_id": attempt_id,
                "answer": json.dumps(ANSWER),
                "request_id": str(uuid.uuid4()),
            },
        )
        receipt = {} if _failed(answered) else json.loads(_text(answered))
        step(
            "4 answer received",
            not _failed(answered)
            and receipt.get("status") in {"received", "evaluating", "resolved"},
            f"status {receipt.get('status')}" if receipt else _text(answered)[:200],
        )

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=api_url, timeout=15) as http:
        events = http.get(f"/v1/arena/battles/{battle_id}/events", headers=headers)
        body = events.json() if events.status_code == 200 else {}
        rows = body.get("data", body.get("events", [])) if isinstance(body, dict) else body
        seqs = [row.get("seq", row.get("sequence")) for row in rows]
        kinds = [row.get("type", row.get("kind")) for row in rows]
        step(
            "5 events in sequence",
            events.status_code == 200 and bool(seqs) and seqs == sorted(set(seqs)),
            f"{events.status_code} {list(zip(seqs, kinds, strict=False))}",
        )
        if outsider_key_env:
            other = {"Authorization": f"Bearer {os.environ[outsider_key_env]}"}
            refused = http.get(f"/v1/arena/battles/{battle_id}", headers=other)
            step(
                "6 other org or off-list key refused",
                refused.status_code == 404,
                str(refused.status_code),
            )

    if db_url:
        step("7 battle row persisted", _battle_rows(db_url, battle_id) == 1)
        after = _counts(db_url)
        step("7 clinical tables untouched", after == before, f"{before} -> {after}")
    print(f"battle_id {battle_id}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--outsider-key-env", help="env var holding a key that must get 404")
    parser.add_argument("--db-url", help="postgresql:// URL of the LOCAL engine database")
    args = parser.parse_args(argv)
    for name in ("ORINYX_API_URL", "ORINYX_API_KEY", "ORINYX_ARENA_URL"):
        if not os.environ.get(name):
            print(f"Set {name} in the environment.", file=sys.stderr)
            return 1
    return asyncio.run(check(args.outsider_key_env, args.db_url))


if __name__ == "__main__":
    raise SystemExit(main())

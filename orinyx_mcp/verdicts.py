"""Non-clinical accounting of engine verdict rows."""

from collections.abc import Mapping
from dataclasses import dataclass

KNOWN_VERDICTS = frozenset({"contradicted", "unreadable", "supported", "abstain"})


@dataclass(frozen=True)
class VerdictCounts:
    total: int = 0
    flagged: int = 0
    supported: int = 0
    not_verified: int = 0


def count_verdicts(rows) -> VerdictCounts:
    values = [row.get("verdict") if isinstance(row, Mapping) else row.verdict for row in rows]
    return VerdictCounts(
        total=len(values),
        flagged=sum(value in ("contradicted", "unreadable") for value in values),
        supported=values.count("supported"),
        not_verified=sum(
            value not in ("contradicted", "unreadable", "supported") for value in values
        ),
    )


def aggregate_disagreements(counts: VerdictCounts, aggregate) -> list[str]:
    def get(name):
        return (
            aggregate.get(name, 0) if isinstance(aggregate, Mapping) else getattr(aggregate, name)
        )

    expected = {
        "total": get("total"),
        "flagged": get("contradicted") + get("unreadable"),
        "supported": get("supported"),
        "not_verified": get("abstain"),
    }
    return [name for name, value in expected.items() if getattr(counts, name) != value]

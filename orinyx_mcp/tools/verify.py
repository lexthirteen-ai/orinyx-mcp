"""Medication verification tools: structured claims, order text, saved runs, accuracy and
exports."""

import base64
from typing import Any

from orinyx_mcp.client import OrinyxApiError, OrinyxClient
from orinyx_mcp.text import render_accuracy_lines, render_run_table

_FORMATS = {"csv": "csv", "pdf": "pdf", "report": "report.pdf", "report.pdf": "report.pdf"}


def _with_run_id(text: str, run: dict) -> str:
    """The report header abbreviates the run id; the other tools need all of it."""
    return f"{text}\n\nRun id: {run.get('runId', '')}"


def verify_medications(
    client: OrinyxClient,
    *,
    claims: list[dict[str, Any]],
    tool_name: str | None = None,
    tool_version: str | None = None,
    check_interactions: bool = False,
) -> str:
    """Verify medication claims against the cited drug labels; one table row per claim."""
    result = client.verify(
        claims,
        tool_name=tool_name,
        tool_version=tool_version,
        check_interactions=check_interactions,
    )
    return _with_run_id(render_run_table(result.raw), result.raw)


def verify_order_text(
    client: OrinyxClient,
    *,
    orders: list[str],
    tool_name: str | None = None,
    tool_version: str | None = None,
    check_interactions: bool = False,
) -> str:
    """Verify medication identity, dose, route and frequency for free-text orders.

    Orinyx returns one row per claim, so an unreadable part never hides a checkable one.
    """
    result = client.verify_orders(
        orders,
        tool_name=tool_name,
        tool_version=tool_version,
        check_interactions=check_interactions,
    )
    return _with_run_id(render_run_table(result.raw), result.raw)


def _accuracy_or_none(client: OrinyxClient, run_id: str) -> dict | None:
    try:
        return client.accuracy(run_id)
    except OrinyxApiError:
        return None


def get_verification(client: OrinyxClient, *, run_id: str) -> str:
    """A saved run as a table, with its accuracy block when a physician review exists."""
    result = client.get_run(run_id)
    return _with_run_id(render_run_table(result.raw, _accuracy_or_none(client, run_id)), result.raw)


def get_accuracy(client: OrinyxClient, *, run_id: str) -> str:
    """The physician-review tally for a run, as text."""
    accuracy = client.accuracy(run_id)
    lines = render_accuracy_lines(accuracy)
    if not lines:
        return (
            f"Run {run_id}: no physician review yet "
            f"({accuracy.get('totalFlags', 0)} flags raised), so no accuracy numbers."
        )
    return "\n".join(lines)


def export_verification(client: OrinyxClient, *, run_id: str, fmt: str) -> dict[str, str]:
    """CSV, the full audit PDF, or the one-page committee report, as a base64 blob."""
    if fmt not in _FORMATS:
        raise ValueError(f"unknown format {fmt!r}; use csv, pdf or report")
    file = client.export(run_id, _FORMATS[fmt])  # type: ignore[arg-type]
    return {
        "name": file.filename,
        "mimeType": file.media_type,
        "blob": base64.b64encode(file.content).decode("ascii"),
    }

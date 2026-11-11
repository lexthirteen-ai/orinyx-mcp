"""Drift checks for the engine-owned data this client keeps a copy of.

Two lists belong to the engine and are copied here so the client can work without asking:
the label sections a reader may request (`client.LABEL_SECTIONS`) and the identifier
screen `orinyx observe` runs before anything is sent (`screen.SCREEN_PATTERNS`). The API
is the source of truth for both. Each copy carries a version, the sha256 of its canonical
JSON (`digest`), and this module compares it with what the API publishes:

- `GET /v1/labels/sections` -> {"sections": [...]} or {"sha256": "..."}
- `GET /v1/screen/patterns` -> {"patterns": [{"name", "pattern", "flags"}, ...]} or
  {"sha256": "..."}

An endpoint the API does not serve (404/405/501) means the copy is used as it is; any
other failure is logged and the copy is used for that call. A copy that differs from the
API's is never silent: it is logged as a warning, and the API's own list is used where
one was served. Logs name the list and its version, never a credential or a response
body."""

import hashlib
import json
import logging
import re
import threading
from typing import Any

from orinyx_mcp.client import _SECTION_RE, LABEL_SECTIONS, OrinyxApiError

logger = logging.getLogger("orinyx_mcp.contract")

LABEL_SECTIONS_PATH = "/v1/labels/sections"
SCREEN_PATTERNS_PATH = "/v1/screen/patterns"
_NOT_SERVED = frozenset({404, 405, 501})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_PATTERNS = 64
_MAX_PATTERN_CHARS = 2000


def digest(value: Any) -> str:
    """The version of a copied list: sha256 of its canonical JSON."""
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def fetch(client, path: str) -> tuple[str, dict[str, Any] | None]:
    """("served", document), ("absent", None) when the API has no such endpoint, or
    ("unreachable", None) for any other failure."""
    reader = getattr(client, "contract_document", None)
    if reader is None:
        return "absent", None
    try:
        return "served", reader(path)
    except OrinyxApiError as exc:
        if exc.status in _NOT_SERVED:
            logger.info("the API does not publish %s; using this package's copy", path)
            return "absent", None
        logger.warning(
            "could not read %s from the API (%s); using this package's copy, unverified",
            path,
            exc.code,
        )
    except Exception as exc:  # a drift check must never break the call it guards
        logger.warning(
            "could not read %s from the API (%s); using this package's copy, unverified",
            path,
            type(exc).__name__,
        )
    return "unreachable", None


def _served_sha256(document: dict[str, Any]) -> str | None:
    value = document.get("sha256")
    return value if isinstance(value, str) and _SHA256_RE.fullmatch(value) else None


def label_sections(client) -> tuple[tuple[str, ...], bool]:
    """The sections to accept, and whether that answer may be cached."""
    from orinyx_mcp.client import LABEL_SECTIONS_SHA256

    status, document = fetch(client, LABEL_SECTIONS_PATH)
    if status != "served":
        return LABEL_SECTIONS, status == "absent"
    sections = document.get("sections")
    if (
        isinstance(sections, list)
        and sections
        and all(isinstance(s, str) and _SECTION_RE.fullmatch(s) for s in sections)
    ):
        served = tuple(dict.fromkeys(sections))
        if served != LABEL_SECTIONS:
            added = [s for s in served if s not in LABEL_SECTIONS]
            removed = [s for s in LABEL_SECTIONS if s not in served]
            logger.warning(
                "label sections drifted: this package's copy (%s) differs from the API's "
                "(added: %s; removed: %s%s); using the API's list. Update "
                "orinyx_mcp/client.py LABEL_SECTIONS.",
                LABEL_SECTIONS_SHA256[:12],
                ", ".join(added) or "none",
                ", ".join(removed) or "none",
                "" if added or removed else "; order differs",
            )
        return served, True
    served_sha = _served_sha256(document)
    if served_sha is None:
        logger.warning(
            "the API's %s answer has an unexpected shape; using this package's copy",
            LABEL_SECTIONS_PATH,
        )
        return LABEL_SECTIONS, False
    if served_sha != LABEL_SECTIONS_SHA256:
        logger.warning(
            "label sections drifted: this package's copy (%s) is not the API's (%s). Update "
            "orinyx_mcp/client.py LABEL_SECTIONS.",
            LABEL_SECTIONS_SHA256[:12],
            served_sha[:12],
        )
    return LABEL_SECTIONS, True


def check(client) -> None:
    """Compare both copies with the API once, logging any drift. Never raises."""
    try:
        client.label_sections()
        from orinyx_mcp import screen

        screen.patterns_for(client)
    except Exception as exc:
        logger.warning("contract check did not complete (%s)", type(exc).__name__)


def check_in_background(client) -> threading.Thread:
    """`check` off the caller's thread, so a slow API never delays a server's start."""
    thread = threading.Thread(target=check, args=(client,), name="orinyx-contract", daemon=True)
    thread.start()
    return thread


__all__ = [
    "LABEL_SECTIONS_PATH",
    "SCREEN_PATTERNS_PATH",
    "check",
    "check_in_background",
    "digest",
    "fetch",
    "label_sections",
]

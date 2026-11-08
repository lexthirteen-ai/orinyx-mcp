"""MCP server factory, on the `mcp` SDK's `MCPServer` (mcp>=2.3).

`build_server` takes a client FACTORY, called once per tool call and closed after it: stdio
hands back its one client, the network transport (`orinyx_mcp/http.py`) builds a client
carrying the calling agent's own credential."""

import base64
import datetime as dt
import functools
import json
import logging
import os
import time
from collections.abc import Callable
from contextlib import contextmanager
from importlib import resources
from typing import Any

from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxApiError, OrinyxClient
from orinyx_mcp.config import ConfigError
from orinyx_mcp.gateway import Gateway

# Gate B15: the not-for-clinical-use statement, worded by the owner on 2026-10-31. It
# opens the server INSTRUCTIONS and every tool description; tests pin the exact text.
NOT_FOR_CLINICAL_USE = (
    "Not for clinical use. Orinyx checks medication claims against cited FDA label text for "
    "testing and evaluation only. Do not use its results to diagnose, treat, prescribe or make "
    "patient care decisions. Use synthetic test data only."
)

INSTRUCTIONS = (
    NOT_FOR_CLINICAL_USE + " "
    "Orinyx checks medication claims against cited FDA label text with deterministic rules; "
    "no language model takes part in a verdict or a severity. Every result row names the "
    "Orinyx check that produced it (Medication Claims, Semantic Mapping or Source Evidence). "
    "These checks are beta release candidates, not production-ready, and each decides with "
    "deterministic rules only. 'supported' means one claim "
    "agrees with the cited label text, not that the order is appropriate. A flag "
    "('contradicted') means the cited label says otherwise, at a rule-derived severity "
    "(minor, moderate or major). 'unreadable' means the order cannot be read as written (a "
    "drug name that is no drug, a unit that is no unit, a body site given as a route): it is "
    "a flag on the order, listed first; say it must not be acted on until the clinician "
    "clarifies it. 'abstain' means Orinyx could not verify the claim; treat it as unchecked, "
    "never as safe. Give orders to verify_order_text exactly as written; Orinyx splits them "
    "itself. Never write a corrected, completed or re-spelled order yourself, and never add "
    "a reason Orinyx did not return: quote the order exactly. You may repeat only the "
    "suggestions Orinyx returned, word for word, labelled as for the clinician to confirm "
    "and not checked. If Orinyx cannot run a check at all, say so and stop: never answer "
    "in its place with your own clinical judgment. Submit synthetic test data only: never "
    "real patient records, names, dates or record numbers. Orinyx flags; the clinician "
    "decides. If the person has not said which kind of test they want, call start_a_test "
    "first. Each exam case says what it takes as an answer: medication claims for a "
    "transcript, the reply text for a patient message, or ICD-10-CM diagnosis codes for an "
    "encounter note."
)


# The connector icon: the Orinyx 8-point star on a transparent background, shipped in
# orinyx_mcp/assets. The vector comes first for clients that can draw it at any size.
ICON_FILES = (
    ("orinyx-star.svg", "image/svg+xml", "any"),
    ("orinyx-star-48.png", "image/png", "48x48"),
    ("orinyx-star-96.png", "image/png", "96x96"),
    ("orinyx-star-256.png", "image/png", "256x256"),
)


@functools.cache
def _icon_uris() -> tuple[tuple[str, str, str], ...]:
    """Each icon file as a data: URI, so no client has to fetch it from anywhere."""
    assets = resources.files("orinyx_mcp").joinpath("assets")
    found = []
    for name, mime_type, size in ICON_FILES:
        try:
            data = assets.joinpath(name).read_bytes()
        except FileNotFoundError:
            continue
        uri = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"
        found.append((uri, mime_type, size))
    return tuple(found)


def server_icons() -> list:
    """The icons the server declares in its implementation info at initialize."""
    from mcp.types import Icon

    return [
        Icon(src=uri, mimeType=mime_type, sizes=[size]) for uri, mime_type, size in _icon_uris()
    ]


@contextmanager
def _refusals():
    """An API refusal (unknown run, missing scope, rate limit) or a bad argument reaches the
    agent WITH its reason. Left as a bare exception the SDK reports a crash and keeps the
    text, so the agent could not tell a wrong id from an outage (local check 2026-10-05)."""
    try:
        yield
    except (OrinyxApiError, ValueError) as exc:
        from mcp.server.mcpserver.exceptions import ToolError

        raise ToolError(str(exc)) from exc


@contextmanager
def _calling(client_for: Callable[[], OrinyxClient]):
    """A client for one tool call (a factory's shared or pooled client, or a fresh one), with
    API refusals turned into readable tool errors. A factory marked `per_call = False` owns
    its client; otherwise the call closes what it got (for a pooled view, that releases it)."""
    with _refusals():
        client = client_for()
        try:
            yield client
        finally:
            if getattr(client_for, "per_call", True):
                client.close()


logger = logging.getLogger("orinyx_mcp.trace")


def _caller_role() -> str | None:
    """The role the API attached to the caller's credential, or None when there is no
    network caller (stdio) or the SDK is absent."""
    try:
        from mcp.server.auth.middleware.auth_context import get_access_token
    except ImportError:
        return None
    access = get_access_token()
    claims = getattr(access, "claims", None) or {}
    return claims.get("role") if access is not None else None


def _trace_wanted(run_id: Any) -> bool:
    """A trace is recorded for a PRODUCT sitting an exam (a vendor-role caller) on a run
    number the API could take it for. A tester's quick check is not an exam: nothing."""
    text = str(run_id)
    return _caller_role() == "vendor" and text.isdigit() and len(text) <= 12


def _outcome(exc: OrinyxApiError) -> str:
    """A 4xx answer is a refusal the product earned; a transport failure or a 5xx is an
    error on Orinyx's side (a fault probe answers 503 on purpose)."""
    return "refused" if 400 <= exc.status < 500 else "error"


# The API refuses a byte count above this; a row is never lost over a size.
TRACE_BYTES_CAP = 50_000_000


def _traced(
    client_for: Callable[[], OrinyxClient],
    tool: str,
    run_id: Any,
    arguments: dict[str, Any],
    fn: Callable[[OrinyxClient, dict], str],
    *,
    case_id: str | None = None,
) -> str:
    """Run one exam tool call and, for a product sitting an exam, post one trace row with
    the same client (the caller's own credential and the hop headers) afterwards. The trace
    is evidence about the product's behaviour and never changes the tool's answer: a failed
    post is logged and the result returned unchanged (behaviour exams, stage 1b)."""
    if not _trace_wanted(run_id):
        with _calling(client_for) as client:
            return fn(client, {})
    at = dt.datetime.now(dt.UTC)
    started = time.perf_counter()
    served: dict = {}
    request_bytes = min(len(json.dumps(arguments, default=str).encode()), TRACE_BYTES_CAP)

    def post(client: OrinyxClient, outcome: str, code: str | None, response_bytes: int) -> None:
        row = {
            "tool": tool,
            "caseId": served.get("case_id") or case_id,
            "outcome": outcome,
            "refusalCode": code,
            "requestBytes": request_bytes,
            "responseBytes": min(response_bytes, TRACE_BYTES_CAP),
            "durationMs": round((time.perf_counter() - started) * 1000, 3),
            "at": at.isoformat(),
        }
        try:
            client.exam_trace(run_id, [row])
        except Exception as exc:  # noqa: BLE001 - the trace must never fail the tool
            logger.warning(
                "trace not recorded for run %s: %s %s",
                run_id,
                type(exc).__name__,
                getattr(exc, "status", "") or "",
            )

    with _calling(client_for) as client:
        try:
            text = fn(client, served)
        except OrinyxApiError as exc:
            post(client, _outcome(exc), exc.code, len(str(exc).encode()))
            raise
        except ValueError as exc:
            post(client, "refused", "invalid_argument", len(str(exc).encode()))
            raise
        except Exception as exc:
            # Anything else is a failure on this side of the hop: traced as an error (never
            # a refusal the product earned) and raised as it would have been.
            post(client, "error", type(exc).__name__, len(str(exc).encode()))
            raise
        post(client, "ok", None, len(text.encode()))
        return text


def _single_case(answers: Any) -> str | None:
    """The case an answer batch concerns, when it concerns exactly one."""
    if isinstance(answers, list) and len(answers) == 1 and isinstance(answers[0], dict):
        value = answers[0].get("caseId")
        return str(value)[:120] if isinstance(value, str | int) else None
    return None


def shared(client: OrinyxClient, *, check_contract: bool = False) -> Callable[[], OrinyxClient]:
    """A factory for a process that owns ONE client for its whole life (stdio). With
    `check_contract`, the first tool call also compares the engine-owned lists this package
    copies with the API's (orinyx_mcp.contract), in the background: drift is logged, not
    silent, and starting the server never sends a request."""
    pending = [check_contract]

    def client_for() -> OrinyxClient:
        if pending and pending.pop():
            from orinyx_mcp.contract import check_in_background

            check_in_background(client)
        return client

    client_for.per_call = False  # the owner closes it, not each tool call
    return client_for


def _with_gateway(base: type, gateway: Gateway) -> type:
    """The server class with a gateway's tools listed after Orinyx's own and its calls
    routed to it. The SDK dispatches tools/list and tools/call through these two methods,
    so the other server's own input schemas reach the agent unchanged."""

    class GatewayServer(base):
        async def list_tools(self):
            return [*await super().list_tools(), *await gateway.tools()]

        async def call_tool(self, name, arguments, context=None):
            if gateway.owns(name):
                return await gateway.call(name, arguments)
            return await super().call_tool(name, arguments, context)

    return GatewayServer


def _guard_tool_descriptions(server: Any) -> None:
    """Make every tool this server registers open with the not-for-clinical-use statement.

    `MCPServer.tool()` delegates to `add_tool`, so wrapping the instance's `add_tool` covers
    each registration path: the decorators below, `register_arena_tools` in arena.py and any
    later `register_*` function, with or without an explicit description. An explicit
    description that already opens with the statement is kept as given (gate B15).
    """
    from orinyx_mcp.annotations import TOOL_METADATA

    add_tool = server.add_tool

    @functools.wraps(add_tool)
    def guarded(fn: Callable[..., Any], *args: Any, description: str | None = None, **kw: Any):
        text = description if description is not None else (fn.__doc__ or "")
        if not text.startswith(NOT_FOR_CLINICAL_USE):
            text = f"{NOT_FOR_CLINICAL_USE} {text}".strip()
        # The same path gives each tool its title and behaviour hints (annotations.py). The
        # decorator passes title=None and annotations=None explicitly, so None means unset.
        known = TOOL_METADATA.get(kw.get("name") or fn.__name__)
        if known is not None:
            if kw.get("title") is None:
                kw["title"] = known[0]
            if kw.get("annotations") is None:
                kw["annotations"] = known[1]
        return add_tool(fn, *args, description=text, **kw)

    server.add_tool = guarded


def build_server(
    client_for: Callable[[], OrinyxClient],
    *,
    gateway: Gateway | None = None,
    **server_options: Any,
):
    from mcp.server.mcpserver import MCPServer
    from mcp.types import BlobResourceContents, EmbeddedResource

    server_class = MCPServer
    instructions = INSTRUCTIONS
    if gateway is not None:
        server_class = _with_gateway(server_class, gateway)
        instructions += gateway.instructions

    # The SDK calls logging.basicConfig when a server is constructed. Inside the API that
    # would hang a second, unstructured handler on the root logger and defeat the JSON log
    # allowlist, so the root logger is put back exactly as it was.
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    # The icons go to the constructor (the gateway subclass inherits it).
    server_options.setdefault("icons", server_icons())
    try:
        server = server_class("orinyx", instructions=instructions, **server_options)
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)

    _guard_tool_descriptions(server)

    @server.tool()
    def verify_medications(
        claims: list[dict[str, Any]],
        tool_name: str | None = None,
        tool_version: str | None = None,
        check_interactions: bool = False,
    ) -> str:
        """Verify STRUCTURED medication claims. Each claim: {rawText, drug, claimType,
        structuredValue} where claimType is one of dose_range, route, frequency, indication,
        contraindication, interaction, monitoring, controlled_substance, rems_attestation.
        One claimType per claim: an order with a dose AND a route is two claims. Send one
        patient's medications per call: when the call states one route for a drug (in the
        structuredValue of its route, dose_range or frequency claims), that route is
        carried onto the drug's frequency claims that state none. Nothing is carried for a
        drug whose claims state two routes or one Orinyx cannot read, or whose drug name
        names a different route; a route written only in a drug name is never carried.
        For an order as written ("warfarin 5 mg by mouth daily") use verify_order_text instead.
        Returns what was checked, every flag with its severity, reason and citation.
        Each row names the check that produced it (beta).
        Claims must be synthetic test data, never real patient records or identifiers:
        rawText is stored in the audit record."""
        with _calling(client_for) as client:
            return tools.verify_medications(
                client,
                claims=claims,
                tool_name=tool_name,
                tool_version=tool_version,
                check_interactions=check_interactions,
            )

    @server.tool()
    def verify_order_text(
        orders: list[str],
        tool_name: str | None = None,
        tool_version: str | None = None,
        check_interactions: bool = False,
    ) -> str:
        """Verify medication orders exactly as written, e.g. "warfarin 5 mg by mouth
        daily" (one drug per order, at most 50 orders of 500 characters). Orinyx splits
        each order into its dose, route and frequency claims itself, with no model, and
        checks each on its own, so a part it cannot read never hides one it can. Pass the
        text unchanged: never correct, complete or re-spell an order first. Each row names
        the check that produced it (beta). Orders must be synthetic test data, never real
        patient records or identifiers: the text is stored in the audit record."""
        with _calling(client_for) as client:
            return tools.verify_order_text(
                client,
                orders=orders,
                tool_name=tool_name,
                tool_version=tool_version,
                check_interactions=check_interactions,
            )

    @server.tool()
    def get_verification(run_id: str) -> str:
        """Read a saved verification run (and its physician-review accuracy, if any).
        Each row names the check that produced it (beta)."""
        with _calling(client_for) as client:
            return tools.get_verification(client, run_id=run_id)

    @server.tool()
    def get_accuracy(run_id: str) -> str:
        """The physician-review accuracy tally for a run: false-flag rate and the catch-rate
        estimate with its sample size; nothing when no review exists."""
        with _calling(client_for) as client:
            return tools.get_accuracy(client, run_id=run_id)

    @server.tool()
    def export_verification(run_id: str, fmt: str = "csv") -> EmbeddedResource:
        """Export a run as csv, pdf (full audit) or report (one-page committee PDF)."""
        with _calling(client_for) as client:
            blob = tools.export_verification(client, run_id=run_id, fmt=fmt)
        return EmbeddedResource(
            type="resource",
            resource=BlobResourceContents(
                uri=f"orinyx://verifications/{run_id}/{blob['name']}",
                mimeType=blob["mimeType"],
                blob=blob["blob"],
            ),
        )

    @server.tool()
    def find_otc_monographs(
        ingredient: str | None = None,
        category: str | None = None,
        title_contains: str | None = None,
    ) -> str:
        """Find FDA over-the-counter (OTC) drug monographs by exact ingredient name (for
        example 'acetaminophen'), exact category name, or words in the title. Reference
        text only: it is not a verification and not a verdict."""
        with _calling(client_for) as client:
            return tools.find_otc_monographs(
                client, ingredient=ingredient, category=category, title_contains=title_contains
            )

    @server.tool()
    def get_otc_monograph(monograph_id: str) -> str:
        """What one FDA OTC monograph (id like M013) covers: ingredients, categories, its
        current documents and its orders."""
        with _calling(client_for) as client:
            return tools.get_otc_monograph(client, monograph_id=monograph_id)

    @server.tool()
    def read_otc_monograph_section(
        document_id: int, section: str | None = None, offset: int = 0
    ) -> str:
        """Read FDA OTC monograph text. With only a document number: lists its sections.
        With a section reference (like M013.50): returns that section's text and where it
        came from. A long section comes in parts; when the reply says TRUNCATED, call again
        with the offset it gives before relying on the text. Reference text, not a verdict
        and not clinical advice."""
        with _calling(client_for) as client:
            return tools.read_otc_monograph_section(
                client, document_id=document_id, section=section, offset=offset
            )

    @server.tool()
    def find_fda_label(drug: str) -> str:
        """Find the FDA prescribing label Orinyx holds for a drug name or RxCUI (a brand name
        only where Orinyx has a curated alias for it): the SPL set ID, label version, effective
        date and which sections carry text. Reference text only: not a verification and not a
        verdict. A name that is not found is reported as given; never respell it or try a
        guessed alternative."""
        with _calling(client_for) as client:
            return tools.find_fda_label(client, drug=drug)

    @server.tool()
    def read_fda_label_section(
        set_id: str,
        section: str,
        offset: int = 0,
        version: int | None = None,
        rxcui: str | None = None,
    ) -> str:
        """Read one section of a cached FDA prescribing label by its SPL set ID. `section` is
        one of: contraindications, boxed_warning, warnings, warnings_and_cautions, overdosage,
        dosage_and_administration, indications_and_usage, drug_interactions,
        dosage_forms_and_strengths. A long section comes in parts; when the reply says
        TRUNCATED, call again with the offset it gives before relying on the text. `version`
        reads a superseded label version and the reply says so. When one set ID backs two
        drugs the reply asks for `rxcui`: pass the one find_fda_label showed. Reference text,
        not a verdict and not clinical advice."""
        with _calling(client_for) as client:
            return tools.read_fda_label_section(
                client, set_id=set_id, section=section, offset=offset, version=version, rxcui=rxcui
            )

    @server.tool()
    def start_a_test() -> str:
        """START HERE. Asks what kind of test you want (a quick check of medication claims,
        a scored exam of an AI product, or an FDA reference lookup) and gives the exact next
        step for the account that is signed in."""
        with _calling(client_for) as client:
            return tools.start_a_test(client)

    @server.tool()
    def get_next_exam_case(run_id: int) -> str:
        """Sitting an exam: get the next unanswered case (a transcript or a patient message
        with patient context, or an encounter note with its date of service) and how to
        answer it: medication claims with the claim shapes the checker reads, the reply
        text, or ICD-10-CM diagnosis codes. Orinyx starts timing the case when it is first
        served."""
        return _traced(
            client_for,
            "get_next_exam_case",
            run_id,
            {"run_id": run_id},
            lambda client, served: tools.get_next_exam_case(client, run_id=run_id, served=served),
        )

    @server.tool()
    def get_exam_cases(run_id: int) -> str:
        """Sitting an exam: get every case at once (transcripts, patient messages or
        encounter notes) and how to answer them. Speed is then reported as not measured;
        prefer get_next_exam_case."""
        return _traced(
            client_for,
            "get_exam_cases",
            run_id,
            {"run_id": run_id},
            lambda client, _: tools.get_exam_cases(client, run_id=run_id),
        )

    @server.tool()
    def submit_exam_answers(run_id: int, answers: list[dict[str, Any]]) -> str:
        """FOR AN ORINYX EXAM ONLY: record your answers. `answers` is a list with exactly one
        answer field each: {caseId, claims} for a transcript case, {caseId, replyText} for a
        patient-message case (the reply exactly as the product would send it; an empty
        string is recorded as unreadable), or {caseId, codes} for an encounter-note case
        (ICD-10-CM diagnosis codes as strings like "E11.9", at most 25, no CPT or HCPCS; an
        empty list is a valid answer; never send a date, the case has its date of service).
        Claims are the medication claims exactly as the exam transcript
        states them, including any that look wrong, each {rawText, drug, claimType,
        structuredValue}. Claim types and their structuredValue keys are listed with each
        case; a contraindication the clinician says does not apply is
        {condition, asserted: false}. An empty claims list is a valid answer. This is how
        the exam is scored, not documentation or clinical guidance: in real use a medication
        statement that looks wrong is carried and raised with the clinician. Use only the
        transcript's words, never real patient data. An answer cannot be changed once
        recorded, and how Orinyx judged it is not shown until the report."""
        return _traced(
            client_for,
            "submit_exam_answers",
            run_id,
            {"run_id": run_id, "answers": answers},
            lambda client, _: tools.submit_exam_answers(client, run_id=run_id, answers=answers),
            case_id=_single_case(answers),
        )

    @server.tool()
    def finish_exam(run_id: int, allow_partial: bool = False) -> str:
        """Sitting an exam: close the sitting once every case is answered. It is then scored
        and no answer can be added."""
        return _traced(
            client_for,
            "finish_exam",
            run_id,
            {"run_id": run_id, "allow_partial": allow_partial},
            lambda client, _: tools.finish_exam(client, run_id=run_id, allow_partial=allow_partial),
        )

    @server.tool()
    def get_exam_report(run_id: int) -> str:
        """The report of a finished exam: for a transcript exam the catch rate, false-flag
        rate and abstain rate; for a patient-message exam the handled rate, false alarms and
        unreadable replies; for an ICD-10-CM coding exam code recall, precision, invalid codes
        and exact cases; each with its denominator, the pass/advisory/fail result, and the
        product's speed per case.
        A pass is not a clinical safety clearance of the product. A result on an unsigned
        draft test set is marked REHEARSAL and is not evidence."""
        return _traced(
            client_for,
            "get_exam_report",
            run_id,
            {"run_id": run_id},
            lambda client, _: tools.get_exam_report(client, run_id=run_id),
        )

    @server.prompt()
    def choose_a_test() -> str:
        """Ask Orinyx what kinds of test this account can run."""
        return (
            "Call the Orinyx tool start_a_test, show me the kinds of test it lists, and "
            "ask me which one I want before doing anything else."
        )

    if os.environ.get("ORINYX_ARENA_ENABLED") == "true":
        from orinyx_mcp.arena import register_arena_tools

        register_arena_tools(server, client_for, os.environ.get("ORINYX_ARENA_URL", ""))

    if gateway is not None:
        clash = [tool.name for tool in server._tool_manager.list_tools() if gateway.owns(tool.name)]
        if clash:
            raise ConfigError(f"DOWNSTREAM_MCP_PREFIX collides with Orinyx tools: {clash}")
    return server


__all__ = ["INSTRUCTIONS", "NOT_FOR_CLINICAL_USE", "build_server", "server_icons", "shared"]

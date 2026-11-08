"""Human-readable titles and MCP behaviour hints for every tool this server registers.

Each hint follows the tool's real effect on the Orinyx API it calls (checked against the
engine's routes, 2026-11-08):

- readOnlyHint: the call writes nothing. The verification reads, the reference lookups,
  start_a_test, the exam report and the Arena reads are GETs. The exam tools also post the
  call's own trace row on the service hop; that row records the call and never changes a
  run or a result, as the access log does not.
- destructiveHint: the call ends something that cannot be reopened. finish_exam closes the
  sitting: it is scored and no answer can be added afterwards. Every other write is additive.
- idempotentHint: repeating the call with the same arguments has no further effect.
  get_next_exam_case serves the same unanswered case without restarting its clock;
  get_exam_cases writes its one "listed in bulk" marker once; a repeated exam answer is
  accepted as recorded or refused (409) when it differs; a second finish_exam is refused
  (409); the Arena writes take a request_id the engine deduplicates on. A verification and
  an export each append a new run or a new audit-chain event, so neither is idempotent.
- openWorldHint is false throughout: every tool reaches the Orinyx API only, never the web
  or another service.

Tools relayed from another MCP server through the gateway keep that server's own metadata.
"""

from mcp.types import ToolAnnotations


def _hints(*, read_only: bool, destructive: bool = False, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=False,
    )


_READ = _hints(read_only=True, idempotent=True)
_ADD = _hints(read_only=False, idempotent=False)
_ADD_ONCE = _hints(read_only=False, idempotent=True)
_CLOSE = _hints(read_only=False, destructive=True, idempotent=True)

TOOL_METADATA: dict[str, tuple[str, ToolAnnotations]] = {
    # Medication checks and their runs
    "verify_medications": ("Verify medication claims", _ADD),
    "verify_order_text": ("Verify medication orders as written", _ADD),
    "get_verification": ("Read a verification run", _READ),
    "get_accuracy": ("Read physician-review accuracy", _READ),
    "export_verification": ("Export a verification run", _ADD),
    # FDA reference lookups
    "find_otc_monographs": ("Find FDA OTC monographs", _READ),
    "get_otc_monograph": ("Read an FDA OTC monograph summary", _READ),
    "read_otc_monograph_section": ("Read FDA OTC monograph text", _READ),
    "find_fda_label": ("Find an FDA prescribing label", _READ),
    "read_fda_label_section": ("Read an FDA label section", _READ),
    # Tests and exams
    "start_a_test": ("Choose a test", _READ),
    "get_next_exam_case": ("Get the next exam case", _ADD_ONCE),
    "get_exam_cases": ("Get every exam case", _ADD_ONCE),
    "submit_exam_answers": ("Submit exam answers", _ADD_ONCE),
    "finish_exam": ("Finish an exam", _CLOSE),
    "get_exam_report": ("Read an exam report", _READ),
    # Arena (registered only when ORINYX_ARENA_ENABLED is "true")
    "start_arena_challenge": ("Start an Arena challenge", _ADD_ONCE),
    "submit_arena_answer": ("Submit an Arena answer", _ADD_ONCE),
    "start_arena_rematch": ("Start an Arena rematch", _ADD_ONCE),
    "get_arena_battle": ("Read an Arena battle", _READ),
    "get_arena_report": ("Read an Arena report", _READ),
}

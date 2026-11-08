"""OrinyxClient: the one HTTP client the MCP server and the CLI share.

It speaks ONLY to the REST API, never to the engine: auth, per-client rate limits, the
access log and the chain of custody all apply because every call is an ordinary API
request carrying an API key. Every response is validated before a field is used (the
same API10 posture the engine applies to its upstreams), and the error envelope becomes
a typed exception.
"""

import copy
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from orinyx_mcp import __version__
from orinyx_mcp.config import split_config_url

ExportFormat = Literal["csv", "pdf", "report.pdf"]
_EXPORT_PATHS: dict[str, str] = {
    "csv": "export.csv",
    "pdf": "export.pdf",
    "report.pdf": "report.pdf",
}
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MONOGRAPH_ID_RE = re.compile(r"M\d{3}")
# An SPL set ID is a UUID; letters, digits and hyphens is all a path may carry.
_SET_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
# The nine cached openFDA label sections the engine serves (the API derives them from its
# ingestion schema). Copied here because this client never imports the engine; a name
# outside this tuple never reaches a URL.
LABEL_SECTIONS: tuple[str, ...] = (
    "contraindications",
    "boxed_warning",
    "warnings",
    "warnings_and_cautions",
    "overdosage",
    "dosage_and_administration",
    "indications_and_usage",
    "drug_interactions",
    "dosage_forms_and_strengths",
)
# sha256 of the tuple above as canonical JSON (orinyx_mcp.contract.digest): the version of this
# copy. The API's own list is the source of truth; `contract.check` compares the two at
# startup and says so loudly when they differ. Editing the tuple means updating this too.
LABEL_SECTIONS_SHA256 = "f8d11b8f2676c6b3549e845d785c2ae98c97fa523f2d2b537dcd797c0efe6c81"
# What a section name may be before it is spliced into a path, whoever supplied the list.
_SECTION_RE = re.compile(r"[a-z0-9_]{1,64}")
# Per-request headers a pooled client may add; never ones that would replace these.
_PROTECTED_HEADERS = frozenset({"authorization", "user-agent", "accept"})
_FILENAME_RE = re.compile(r'filename="?([^";]+)"?')


class OrinyxApiError(Exception):
    """A non-2xx answer (its envelope fields), a malformed answer, or a transport failure."""

    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(f"{code} ({status}): {message}" if status else f"{code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


class InsecureUrlError(ValueError):
    """The API URL is plain http to a host other than localhost. The message names neither
    the URL (it can carry a user:password) nor the key, so an entry point may print it."""


# What an entry point prints when the URL or key cannot be used for another reason: that
# reason can quote the URL, so it is never shown.
UNUSABLE_CONFIG = "ORINYX_API_URL or ORINYX_API_KEY is malformed (neither value is shown)."
# What a request that broke an HTTP rule on this side says. h11's own message quotes the
# header it refused, and that is most often the Authorization header: the key itself.
_NOT_SENT = (
    "the request was not sent: it broke an HTTP rule on this side, most often a header value "
    "(the API key, for example) that holds a line break. No header value is shown."
)


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class Citation(_Wire):
    source: str
    section: str
    source_id: str | None = None
    citation: str
    url: str


class Verdict(_Wire):
    verdict_id: int | None = None
    assertion_id: int | None = None
    raw_text: str
    drug: str
    rxcui: str | None = None
    claim_type: str
    verdict: str
    severity: str
    explanation: str
    severity_reason: str | None = None
    citation: Citation | None = None
    structured_value: dict | None = None
    # `unreadable` verdicts: one {facet, value, reason, basis} per part of the order that
    # could not be read; and the display-only suggestions beside them (never checked).
    unreadable_facets: list[dict] | None = None
    suggestions: list[dict] | None = None


class Aggregate(_Wire):
    total: int
    supported: int
    contradicted: int
    abstain: int
    # Orders that could not be read as written; a flag on the order, not an abstain. 0 from
    # an API older than the `unreadable` verdict.
    unreadable: int = 0


class VerificationResult(_Wire):
    run_id: str
    verdicts: list[Verdict]
    aggregate: Aggregate
    tool_name: str | None = None
    tool_version: str | None = None
    created_at: str | None = None
    # The JSON exactly as the API returned it (for rendering and --json output).
    raw: dict = Field(default_factory=dict, exclude=True)

    @property
    def flagged(self) -> int:
        """Label flags plus orders that cannot be read: both mean "do not act on this"."""
        return self.aggregate.contradicted + self.aggregate.unreadable

    @classmethod
    def from_json(cls, data: dict) -> "VerificationResult":
        result = cls.model_validate(data)
        result.raw = dict(data)
        return result


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    content: bytes


class OrinyxClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        headers: Mapping[str, str] | None = None,
        allow_http: bool = False,
    ) -> None:
        parts = split_config_url(base_url, "ORINYX_API_URL")
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not local and not allow_http:
            # `allow_http` is for a private network the operator trusts end to end (the MCP
            # service reaching the engine over Fly's encrypted internal network); never
            # the default, so a key is not sent in clear by accident.
            raise InsecureUrlError("ORINYX_API_URL must use https (plain http only for localhost).")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                **(headers or {}),  # extras first: they can never replace the credential
                "Authorization": f"Bearer {api_key}",
                "User-Agent": f"orinyx-mcp/{__version__}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )
        self._owns_http = True
        self._extra_headers: dict[str, str] = {}
        self._release: Callable[[], None] | None = None
        # Shared by every bound() view of this client: engine-owned lists read from the API.
        self._contract_cache: dict[str, Any] = {}

    def bound(
        self, headers: Mapping[str, str], release: Callable[[], None] | None = None
    ) -> "OrinyxClient":
        """A view of this client for one call: the same pooled connection and credential, plus
        `headers` on each request (never the credential, the user agent or Accept). Closing the
        view calls `release` instead of closing the connection."""
        view = copy.copy(self)
        view._owns_http = False
        view._extra_headers = {
            name: value
            for name, value in dict(headers).items()
            if name.lower() not in _PROTECTED_HEADERS
        }
        view._release = release
        return view

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
            return
        release, self._release = self._release, None
        if release is not None:
            release()

    def __enter__(self) -> "OrinyxClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- plumbing -----------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        refused = False
        if self._extra_headers:
            kwargs["headers"] = {**self._extra_headers, **(kwargs.get("headers") or {})}
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.LocalProtocolError:
            refused = True
        except httpx.HTTPError as exc:
            raise OrinyxApiError(0, "transport_error", str(exc)) from exc
        if refused:
            # Raised after the except block, so the error holds no reference to the refusal
            # (not as its cause, not as its context): that refusal quotes the header.
            raise OrinyxApiError(0, "transport_error", _NOT_SENT)
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise OrinyxApiError(response.status_code, "invalid_response", "response too large")
        if response.is_success:
            return response
        try:
            envelope = response.json()["error"]
            raise OrinyxApiError(
                response.status_code,
                str(envelope.get("code", "error")),
                str(envelope.get("message", "")),
                list(envelope.get("details") or []),
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            raise OrinyxApiError(response.status_code, "http_error", response.text[:200]) from None

    @staticmethod
    def _media_type(response: httpx.Response) -> str:
        return response.headers.get("content-type", "").split(";")[0].strip().lower()

    @staticmethod
    def _run_path(run_id: str) -> str:
        """Only a UUID may be spliced into a path: an agent-supplied id like
        `../audit/export?x=` must never steer the operator's key to another endpoint. The
        refusal names the field, never the value: a key typed where the run id goes must not
        be printed back."""
        try:
            return str(uuid.UUID(str(run_id)))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("run_id must be a UUID") from None

    def _json_object(self, response: httpx.Response) -> dict[str, Any]:
        if self._media_type(response) != "application/json":
            raise OrinyxApiError(
                response.status_code, "invalid_response", "expected application/json"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise OrinyxApiError(response.status_code, "invalid_response", "not JSON") from exc
        if not isinstance(data, dict):
            raise OrinyxApiError(response.status_code, "invalid_response", "not a JSON object")
        return data

    def _run(self, response: httpx.Response) -> VerificationResult:
        data = self._json_object(response)
        try:
            return VerificationResult.from_json(data)
        except ValidationError as exc:
            # Never echo response content into the error: the agent sees only the shape.
            fields = sorted({str(err["loc"][0]) for err in exc.errors() if err.get("loc")})
            raise OrinyxApiError(
                response.status_code,
                "invalid_response",
                f"unexpected run shape (fields: {', '.join(fields) or 'unknown'})",
            ) from None

    # --- surface -------------------------------------------------------------------------

    def verify(
        self,
        claims: list[dict],
        *,
        tool_name: str | None = None,
        tool_version: str | None = None,
        check_interactions: bool = False,
        context_label: str | None = None,
    ) -> VerificationResult:
        body: dict[str, Any] = {"assertions": claims, "checkInteractions": check_interactions}
        if tool_name:
            body["toolName"] = tool_name
        if tool_version:
            body["toolVersion"] = tool_version
        if context_label:
            body["contextLabel"] = context_label
        return self._run(self._request("POST", "/v1/verifications", json=body))

    def verify_orders(
        self,
        orders: list[str],
        *,
        tool_name: str | None = None,
        tool_version: str | None = None,
        check_interactions: bool = False,
    ) -> VerificationResult:
        """Free-text orders; the API splits each into its dose, route and frequency claims
        (deterministically, no model) and verifies them as one run."""
        body: dict[str, Any] = {"orders": orders, "checkInteractions": check_interactions}
        if tool_name:
            body["toolName"] = tool_name
        if tool_version:
            body["toolVersion"] = tool_version
        return self._run(self._request("POST", "/v1/verifications/orders", json=body))

    def get_run(self, run_id: str) -> VerificationResult:
        return self._run(self._request("GET", f"/v1/verifications/{self._run_path(run_id)}"))

    def accuracy(self, run_id: str) -> dict[str, Any]:
        path = f"/v1/verifications/{self._run_path(run_id)}/accuracy"
        data = self._json_object(self._request("GET", path))
        if "reviewed" not in data or "runId" not in data:
            raise OrinyxApiError(200, "invalid_response", "unexpected accuracy shape")
        return data

    def export(self, run_id: str, fmt: ExportFormat) -> ExportFile:
        if fmt not in _EXPORT_PATHS:
            raise ValueError(f"unknown export format {fmt!r}; use csv, pdf or report.pdf")
        path = f"/v1/verifications/{self._run_path(run_id)}/{_EXPORT_PATHS[fmt]}"
        response = self._request("GET", path, headers={"Accept": "*/*"})
        expected = "text/csv" if fmt == "csv" else "application/pdf"
        if self._media_type(response) != expected:
            raise OrinyxApiError(response.status_code, "invalid_response", f"expected {expected}")
        disposition = response.headers.get("content-disposition", "")
        match = _FILENAME_RE.search(disposition)
        default = f"orinyx-{run_id}.{'csv' if fmt == 'csv' else 'pdf'}"
        return ExportFile(
            filename=match.group(1) if match else default,
            media_type=response.headers.get("content-type", "application/octet-stream")
            .split(";")[0]
            .strip(),
            content=response.content,
        )

    # --- product exams (the sandbox case-set lifecycle) ----------------------------------

    @staticmethod
    def _exam_path(run_id: int | str) -> str:
        """Only a run NUMBER may be spliced into a path."""
        text = str(run_id)
        if isinstance(run_id, bool) or not text.isdigit() or len(text) > 12:
            raise ValueError("run_id is the exam run number, for example 12")
        return f"/v1/benchmark-runs/{int(text)}"

    def _reaches(self, path: str) -> bool:
        """Whether this credential reaches a list route (a read; no side effect). A refused
        (401) or not-cleared (403) credential is False; every other failure raises."""
        try:
            self._request("GET", path, params={"limit": 1})
        except OrinyxApiError as exc:
            if exc.status in (401, 403):
                return False
            raise
        return True

    def can_verify(self) -> bool:
        """Whether this credential reaches the verification surface (a read; no side effect)."""
        return self._reaches("/v1/verifications")

    def can_read_labels(self) -> bool:
        """Whether this credential reaches the FDA label and monograph text (a read; no side
        effect). The API admits the same accounts to label, monograph and document text, so
        the monograph list answers for all of it."""
        return self._reaches("/v1/monographs")

    def exam_runs(self, status: str | None = None) -> dict[str, Any]:
        params = {"status": status} if status else None
        data = self._json_object(self._request("GET", "/v1/benchmark-runs", params=params))
        if not isinstance(data.get("data"), list):
            raise OrinyxApiError(200, "invalid_response", "unexpected exam list shape")
        return data

    @staticmethod
    def _is_int(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    @staticmethod
    def _is_case(case: Any) -> bool:
        case_id = case.get("caseId") if isinstance(case, dict) else None
        return isinstance(case_id, str) and case_id != ""

    def exam_next_case(self, run_id: int | str) -> dict[str, Any]:
        data = self._json_object(self._request("POST", f"{self._exam_path(run_id)}/next-case"))
        # No case means every case is answered (`remaining` 0); a case counts itself (1 or more).
        case, remaining = data.get("case"), data.get("remaining")
        if not self._is_int(remaining) or not (
            remaining == 0 if case is None else remaining >= 1 and self._is_case(case)
        ):
            raise OrinyxApiError(200, "invalid_response", "unexpected exam case shape")
        return data

    def exam_cases(self, run_id: int | str) -> dict[str, Any]:
        data = self._json_object(self._request("GET", f"{self._exam_path(run_id)}/cases"))
        cases = data.get("cases")
        if not isinstance(cases, list) or not all(map(self._is_case, cases)):
            raise OrinyxApiError(200, "invalid_response", "unexpected exam cases shape")
        return data

    def exam_submit(self, run_id: int | str, answers: list[dict]) -> list[dict]:
        response = self._request(
            "POST", f"{self._exam_path(run_id)}/submissions", json={"submissions": answers}
        )
        data = response.json() if self._media_type(response) == "application/json" else None
        if not isinstance(data, list):
            raise OrinyxApiError(response.status_code, "invalid_response", "unexpected shape")
        return data

    def exam_finish(self, run_id: int | str, allow_partial: bool = False) -> dict[str, Any]:
        body = {"allowPartial": bool(allow_partial)}
        data = self._json_object(
            self._request("POST", f"{self._exam_path(run_id)}/complete", json=body)
        )
        # Checked after the POST on purpose: only a completed run proves the finish happened.
        if not self._is_int(data.get("id")) or data.get("status") != "completed":
            raise OrinyxApiError(200, "invalid_response", "unexpected finished exam shape")
        return data

    def exam_report(self, run_id: int | str) -> dict[str, Any]:
        data = self._json_object(self._request("GET", f"{self._exam_path(run_id)}/report"))
        case_set, cases, reasons = data.get("caseSet"), data.get("cases"), data.get("reasons", [])
        # A non-bool `clinicallyReviewed` would read as evidence; an absent one is a rehearsal.
        # The engine sends `reasons` as a list of strings (empty on a pass), never null.
        if (
            "verdict" not in data
            or not (data["verdict"] is None or isinstance(data["verdict"], str))
            or not isinstance(reasons, list)
            or not all(isinstance(reason, str) for reason in reasons)
            or not isinstance(case_set, dict)
            or not isinstance(case_set.get("clinicallyReviewed", False), bool)
            or not isinstance(data.get("metrics"), dict)
            or not isinstance(cases, list)
            or not all(self._is_case(item) for item in cases)
        ):
            raise OrinyxApiError(200, "invalid_response", "unexpected exam report shape")
        return data

    def exam_trace(self, run_id: int | str, calls: list[dict]) -> dict[str, Any]:
        """One row per exam tool call the product made (behaviour exams, stage 1b). The API
        accepts it only on the recognised hop, so this is the service's call, never a tool."""
        return self._json_object(
            self._request("POST", f"{self._exam_path(run_id)}/trace", json={"calls": calls})
        )

    # Operator actions (quality lead or admin; refused for every other account).

    def create_vendor(self, name: str, product: str, contact_email: str) -> dict[str, Any]:
        body = {"name": name, "product": product, "contactEmail": contact_email}
        return self._json_object(self._request("POST", "/v1/vendors", json=body))

    def vendors(self) -> dict[str, Any]:
        return self._json_object(self._request("GET", "/v1/vendors", params={"limit": 200}))

    def open_exam(
        self, vendor_id: int, case_set_id: str, version: str, *, entry_mode: str = "vendor"
    ) -> dict[str, Any]:
        if isinstance(vendor_id, bool) or not str(vendor_id).isdigit():
            raise ValueError("vendor_id is the vendor's number")
        if entry_mode not in {"vendor", "operator"}:
            raise ValueError("entry_mode must be vendor or operator")
        body = {"caseSetId": case_set_id, "caseSetVersion": version, "entryMode": entry_mode}
        path = f"/v1/vendors/{int(vendor_id)}/benchmark-runs"
        return self._json_object(self._request("POST", path, json=body))

    # --- FDA over-the-counter monographs (reference text) --------------------------------

    def monographs(self, **filters: str | None) -> dict[str, Any]:
        """List monographs. Filters: `ingredient`, `category` (exact names), `q` (title)."""
        allowed = {k: v for k, v in filters.items() if k in ("ingredient", "category", "q") and v}
        data = self._json_object(self._request("GET", "/v1/monographs", params=allowed))
        if not isinstance(data.get("data"), list):
            raise OrinyxApiError(200, "invalid_response", "unexpected monograph list shape")
        return data

    def monograph(self, monograph_id: str) -> dict[str, Any]:
        candidate = str(monograph_id).strip().upper()
        if not _MONOGRAPH_ID_RE.fullmatch(candidate):
            raise ValueError("monograph_id looks like M013 (the letter M and three digits)")
        data = self._json_object(self._request("GET", f"/v1/monographs/{candidate}"))
        if "id" not in data:
            raise OrinyxApiError(200, "invalid_response", "unexpected monograph shape")
        return data

    def regulatory_document(self, document_id: int, section: str | None = None) -> dict[str, Any]:
        if isinstance(document_id, bool) or not str(document_id).isdigit():
            raise ValueError("document_id is the number shown beside a monograph's document")
        params = {"section": section} if section else None
        path = f"/v1/regulatory-documents/{int(document_id)}"
        data = self._json_object(self._request("GET", path, params=params))
        if not isinstance(data.get("sections"), list):
            raise OrinyxApiError(200, "invalid_response", "unexpected document shape")
        return data

    # --- FDA prescribing labels (cached openFDA text; reference, never a verdict) ----------

    def labels(self, drug: str) -> dict[str, Any]:
        """The current cached label(s) for a drug name or RxCUI the engine's resolver places.
        The name is sent as given: the engine does the matching, never this client."""
        name = " ".join(str(drug).split())
        if not name or len(name) > 120:
            raise ValueError("drug is a drug name or RxCUI of at most 120 characters")
        data = self._json_object(self._request("GET", "/v1/labels", params={"drug": name}))
        if not isinstance(data.get("data"), list):
            raise OrinyxApiError(200, "invalid_response", "unexpected label list shape")
        return data

    def contract_document(self, path: str) -> dict[str, Any]:
        """One of the API's documents describing engine-owned data (orinyx_mcp.contract)."""
        return self._json_object(self._request("GET", path))

    def label_sections(self) -> tuple[str, ...]:
        """The label sections the API serves, read once per client; this package's copy
        (LABEL_SECTIONS) when the API does not publish the list or cannot be reached."""
        cached = self._contract_cache.get("label_sections")
        if cached is not None:
            return cached
        from orinyx_mcp import contract

        sections, settled = contract.label_sections(self)
        if settled:
            self._contract_cache["label_sections"] = sections
        return sections

    def label_section(
        self,
        set_id: str,
        section: str,
        version: int | None = None,
        rxcui: str | None = None,
    ) -> dict[str, Any]:
        candidate = str(set_id).strip()
        if not _SET_ID_RE.fullmatch(candidate):
            raise ValueError("set_id is an SPL set ID (letters, digits and hyphens only)")
        if section not in LABEL_SECTIONS:
            # Not in this package's copy: the API's list, once read (contract.check), may name
            # a section added since. Validation itself never sends a request.
            served = self._contract_cache.get("label_sections", LABEL_SECTIONS)
            if section not in served:
                raise ValueError("section must be one of: " + ", ".join(served))
        params: dict[str, Any] = {}
        if version is not None:
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError("version is a positive label version number")
            params["version"] = version
        if rxcui is not None:
            digits = str(rxcui).strip()
            if not re.fullmatch(r"[0-9]{1,20}", digits):
                raise ValueError("rxcui is the drug's RxCUI (ASCII digits)")
            params["rxcui"] = digits
        path = f"/v1/labels/{candidate}/sections/{section}"
        data = self._json_object(self._request("GET", path, params=params or None))
        if "sectionText" not in data:
            raise OrinyxApiError(200, "invalid_response", "unexpected label section shape")
        return data


__all__ = [
    "LABEL_SECTIONS",
    "LABEL_SECTIONS_SHA256",
    "Aggregate",
    "Citation",
    "ExportFile",
    "ExportFormat",
    "OrinyxApiError",
    "OrinyxClient",
    "Verdict",
    "VerificationResult",
]

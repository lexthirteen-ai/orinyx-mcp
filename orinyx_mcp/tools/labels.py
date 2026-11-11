"""Reference-text readers: FDA over-the-counter monographs and cached openFDA prescribing-label
sections. Reference text, never a verdict."""

from orinyx_mcp.client import OrinyxApiError, OrinyxClient

# --- FDA over-the-counter monographs: reference text, never a verdict ----------------------

REFERENCE_NOTE = (
    "FDA reference text as collected by Orinyx. This is not a verdict: only the rules Orinyx "
    "has curated from a monograph affect a verification. The text is machine-extracted from "
    "the FDA PDF and may contain extraction errors. It is not clinical advice; confirm "
    "against the FDA document before relying on it."
)
_MAX_LISTED = 25
_MAX_SECTION_CHARS = 6000


def find_otc_monographs(
    client: OrinyxClient,
    *,
    ingredient: str | None = None,
    category: str | None = None,
    title_contains: str | None = None,
) -> str:
    """Monographs by exact ingredient or category name, or by words in the title."""
    filters = {"ingredient": ingredient, "category": category, "q": title_contains}
    page = client.monographs(**{k: v for k, v in filters.items() if v})
    rows = page["data"]
    if not rows:
        return (
            "No monograph matched. Ingredient and category are exact names (for example "
            "'acetaminophen'); title_contains matches words in the title.\n\n" + REFERENCE_NOTE
        )
    total = (page.get("pagination") or {}).get("total", len(rows))
    lines = [f"FDA OTC monographs: {total} matched, showing {min(len(rows), _MAX_LISTED)}."]
    for row in rows[:_MAX_LISTED]:
        state = " (no longer listed by FDA)" if row.get("delistedAt") else ""
        lines.append(f"- {row['id']}: {row.get('title', '')}{state}")
        lines.append(
            f"  Published {row.get('publishedDate', 'unknown')} - {row.get('registryUrl')}"
        )
    lines += ["", "Use get_otc_monograph with an id for what it covers.", "", REFERENCE_NOTE]
    return "\n".join(lines)


def get_otc_monograph(client: OrinyxClient, *, monograph_id: str) -> str:
    """What one monograph covers, its current documents and its orders."""
    data = client.monograph(monograph_id)
    terms = data.get("terms") or []

    def named(kind: str) -> str:
        return ", ".join(t["term"] for t in terms if t.get("kind") == kind) or "none listed"

    lines = [
        f"FDA OTC monograph {data['id']}: {data.get('title', '')}",
        f"Published {data.get('publishedDate', 'unknown')} - {data.get('registryUrl')}",
        f"Ingredients: {named('ingredient')}",
        f"Categories: {named('therapeutic_category')}",
        "",
        "Documents (current versions):",
    ]
    for doc in data.get("documents") or []:
        lines.append(
            f"- document {doc['id']} ({doc.get('kind')}), version {doc.get('docVersion')}, "
            f"{doc.get('pageCount')} pages: {doc.get('title', '')} - {doc.get('sourceUrl')}"
        )
    orders = data.get("orders") or []
    lines += ["", f"Orders ({len(orders)}):"]
    for order in orders[:_MAX_LISTED]:
        lines.append(
            f"- {order.get('orderId')} ({order.get('orderStatus')}), "
            f"{order.get('publishedDate')}: {order.get('title', '')}"
        )
    lines += [
        "",
        "Use read_otc_monograph_section with a document number to list its sections, then "
        "with a section reference to read one.",
        "",
        REFERENCE_NOTE,
    ]
    return "\n".join(lines)


def _document_source(data: dict) -> str:
    """Everything needed to know WHAT was read: which document, of what, which version,
    whether it is the current one, when it was retrieved and from where."""
    parent = data.get("monographId") or data.get("orderId") or "unknown"
    state = "current version" if data.get("isCurrent", True) else "SUPERSEDED VERSION"
    if data.get("supersededAt"):
        state += f", superseded {data['supersededAt']}"
    return (
        f"{data.get('kind', 'document')} document {data.get('id')} of {parent}: "
        f"{data.get('title', '')} (version {data.get('docVersion')}, {state}, retrieved "
        f"{data.get('retrievedAt')}) - {data.get('sourceUrl')}"
    )


def read_otc_monograph_section(
    client: OrinyxClient, *, document_id: int, section: str | None = None, offset: int = 0
) -> str:
    """A document's section index, or the text of one section with where it came from."""
    data = client.regulatory_document(document_id, section)
    source = _document_source(data)
    warning = "" if data.get("isCurrent", True) else "SUPERSEDED VERSION - not the current text.\n"
    if not section:
        lines = [f"{warning}Sections of {source}:"]
        for item in (data.get("sections") or [])[:200]:
            lines.append(
                f"- {item.get('ref')}: {item.get('heading', '')} (page {item.get('page')})"
            )
        lines += ["", "Call again with one of these references as `section`.", "", REFERENCE_NOTE]
        return "\n".join(lines)
    text = data.get("sectionText")
    if not text:
        raise ValueError(f"this document has no section {section!r}; list its sections first")
    notice, page = _paged(text, offset, data.get("sourceUrl"))
    return f"{warning}Section {section} of {source}\n\n{notice}{page}\n\n{REFERENCE_NOTE}"


def _paged(text: str, offset: int, source_url: str | None) -> tuple[str, str]:
    """One page of a long section and the notice that goes BEFORE it. Pages end at a
    sentence, never mid-sentence: a cut could otherwise drop the second half of a "do not
    exceed ..." statement while keeping the first. Shared by the monograph and label readers."""
    total = len(text)
    start = max(0, min(int(offset or 0), total))
    end = min(start + _MAX_SECTION_CHARS, total)
    if end < total:
        boundary = max(text.rfind(". ", start, end), text.rfind(".\n", start, end))
        if boundary > start:
            end = boundary + 1
    notice = ""
    if start > 0 or end < total:
        rest = (
            f" The rest of this section, which may contain limits, warnings or exceptions, "
            f"is not shown; call again with offset={end}, or read it at {source_url}."
            if end < total
            else " This is the end of the section."
        )
        notice = f"TRUNCATED: characters {start + 1} to {end} of {total}.{rest}\n\n"
    return notice, text[start:end]


# --- FDA prescribing labels: cached openFDA section text, never a verdict -------------------

LABEL_REFERENCE_NOTE = (
    "FDA prescribing-label text as cached by Orinyx from openFDA. This is not a verdict: only "
    "the rules Orinyx derived from this label affect a verification, and a section's presence "
    "here says nothing about any order. It is not clinical advice; the DailyMed link is the "
    "authoritative copy."
)


def _label_source(data: dict) -> str:
    """Everything a citation of this text needs: source, set ID, rxcui, version, effective
    date, currency, retrieval date and the DailyMed address."""
    state = "current" if data.get("isCurrent", True) else "SUPERSEDED VERSION"
    return (
        f"{data.get('source') or 'openFDA'} label, SPL set ID {data.get('setId')} (rxcui "
        f"{data.get('rxcui')}), version {data.get('labelVersion')}, effective "
        f"{data.get('effectiveTime')}, {state}, retrieved {data.get('retrievedAt')} "
        f"- {data.get('sourceUrl')}"
    )


def _label_identity(data: dict) -> list[str]:
    """Which product the label describes, so an agent never quotes another product's label
    as this drug's: the label's own generic name and routes, and the qualifiers the resolver
    stripped from the name given (a formulation or salt the label may not describe)."""
    lines = []
    generic = data.get("labelGenericName")
    routes = ", ".join(data.get("labelRoutes") or [])
    if generic or routes:
        lines.append(
            f"  This label is for {generic or 'an unnamed product'}"
            + (f" (routes: {routes})" if routes else "")
            + "."
        )
    stripped = data.get("qualifiersStripped") or []
    if stripped:
        lines.append(
            f"  The name given carried {', '.join(stripped)}: the formulation or salt stated "
            "may not be the one this label describes."
        )
    return lines


def find_fda_label(client: OrinyxClient, *, drug: str) -> str:
    """The cached FDA label(s) for a drug the knowledge base holds, with the sections that
    carry text. A name the engine cannot place is reported as such, never respelled."""
    try:
        page = client.labels(drug)
    except OrinyxApiError as exc:
        if exc.status == 404:
            return (
                f'No label: "{drug}" is not in the knowledge base. Orinyx matches a name exactly '
                "(plus salts and curated aliases), never by spelling; try the generic name or "
                "the RxCUI. Do not substitute a name yourself."
            )
        raise
    rows = page.get("data") or []
    if not rows:
        return f'The knowledge base names "{drug}" but holds no cached label for it.'
    first = rows[0]
    lines = [
        f'FDA label(s) for "{drug}" (matched as {first.get("matchedVia")} to {first.get("drug")}):'
    ]
    for row in rows[:_MAX_LISTED]:
        lines.append(f"- {_label_source(row)}")
        lines += _label_identity(row)
        sections = row.get("sections") or []
        if sections:
            shown = ", ".join(f"{s.get('section')} ({s.get('chars')} chars)" for s in sections)
            lines.append(f"  Sections with text: {shown}")
        else:
            lines.append("  No cached section carries text.")
    lines += [
        "",
        "Use read_fda_label_section with the set ID and a section name to read one.",
        "",
        LABEL_REFERENCE_NOTE,
    ]
    return "\n".join(lines)


def read_fda_label_section(
    client: OrinyxClient,
    *,
    set_id: str,
    section: str,
    offset: int = 0,
    version: int | None = None,
    rxcui: str | None = None,
) -> str:
    """One cached label section as text with its citation, paged at sentence ends. `rxcui`
    picks the drug when one SPL set backs two knowledge-base drugs (the engine's 409)."""
    data = client.label_section(set_id, section, version=version, rxcui=rxcui)
    text = data.get("sectionText")
    if not text:
        raise ValueError(f"this label carries no {section!r} text")
    warning = (
        "" if data.get("isCurrent", True) else "SUPERSEDED VERSION - not the current label text.\n"
    )
    identity = "\n".join(_label_identity(data))
    notice, page = _paged(text, offset, data.get("sourceUrl"))
    return (
        f"{warning}Section {section} of {data.get('drug')}: {_label_source(data)}\n"
        f"{identity}\n\n{notice}{page}\n\n{LABEL_REFERENCE_NOTE}"
    )

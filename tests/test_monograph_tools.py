"""FDA over-the-counter monograph lookup on the connector: reference text, never a verdict."""

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxClient

LIST = {
    "data": [
        {
            "id": "M013",
            "title": "Internal Analgesic, Antipyretic, and Antirheumatic Drug Products",
            "publishedDate": "2021-09-20",
            "registryUrl": "https://www.accessdata.fda.gov/scripts/cder/omuf/x?id=M013",
            "delistedAt": None,
        }
    ],
    "pagination": {"total": 1, "limit": 50, "offset": 0},
}
DETAIL = LIST["data"][0] | {
    "terms": [
        {"kind": "ingredient", "term": "acetaminophen"},
        {"kind": "ingredient", "term": "aspirin"},
        {"kind": "therapeutic_category", "term": "analgesic"},
    ],
    "documents": [
        {
            "id": 7,
            "kind": "monograph",
            "title": "M013 monograph",
            "docVersion": 2,
            "sourceUrl": "https://www.accessdata.fda.gov/drugsatfda_docs/omuf/M013.pdf",
            "pageCount": 30,
            "retrievedAt": "2026-10-05T20:00:00+00:00",
        }
    ],
    "orders": [
        {
            "orderId": "OTC000008",
            "title": "Final order",
            "orderStatus": "final",
            "publishedDate": "2021-09-20",
            "registryUrl": "https://www.accessdata.fda.gov/scripts/cder/omuf/x?o=8",
        }
    ],
}
DOCUMENT = DETAIL["documents"][0] | {
    "monographId": "M013",
    "sections": [
        {"ref": "M013.50", "heading": "Directions", "page": 12},
        {"ref": "M013.60", "heading": "Professional labeling", "page": 14},
    ],
    "sectionText": None,
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def monographs(self, **filters):
        self.calls.append(("monographs", filters))
        return LIST

    def monograph(self, monograph_id):
        self.calls.append(("monograph", monograph_id))
        return DETAIL

    def regulatory_document(self, document_id, section=None):
        self.calls.append(("document", document_id, section))
        text = None if section is None else "Do not exceed 4,000 mg in 24 hours. " * 400
        return DOCUMENT | {"sectionText": text}


def test_finding_monographs_lists_ids_titles_and_the_fda_address():
    client = FakeClient()
    text = tools.find_otc_monographs(client, ingredient="Acetaminophen")
    assert client.calls == [("monographs", {"ingredient": "Acetaminophen"})]
    assert "M013" in text and "Internal Analgesic" in text
    assert "https://www.accessdata.fda.gov/scripts/cder/omuf/x?id=M013" in text
    assert "not a verdict" in text.lower()


def test_no_match_says_so_plainly():
    class Empty(FakeClient):
        def monographs(self, **filters):
            return {"data": [], "pagination": {"total": 0}}

    assert "No monograph matched" in tools.find_otc_monographs(Empty(), title_contains="zzz")


def test_a_monograph_shows_what_it_covers_and_which_document_to_read():
    text = tools.get_otc_monograph(FakeClient(), monograph_id="M013")
    assert "acetaminophen, aspirin" in text and "analgesic" in text
    assert "document 7" in text and "version 2" in text
    assert "OTC000008" in text and "final" in text
    assert "read_otc_monograph_section" in text  # the next step, by name


def test_reading_a_document_lists_sections_then_returns_capped_cited_text():
    client = FakeClient()
    index = tools.read_otc_monograph_section(client, document_id=7)
    assert "M013.50" in index and "Directions" in index and "page 12" in index
    text = tools.read_otc_monograph_section(client, document_id=7, section="M013.50")
    assert "Do not exceed 4,000 mg" in text
    assert "M013.50" in text and "version 2" in text
    assert "https://www.accessdata.fda.gov/drugsatfda_docs/omuf/M013.pdf" in text
    assert "monograph document 7 of M013" in text and "current version" in text
    assert text.index("TRUNCATED: characters 1 to") < text.index("Do not exceed")  # said FIRST
    assert "may contain limits, warnings or exceptions" in text and "offset=" in text
    body = text.split("\n\n")[2]
    assert len(body) <= 6000 and body.rstrip().endswith(".")  # never cut mid-sentence
    assert "not a verdict" in text.lower() and "machine-extracted" in text
    resume = int(text.split("offset=")[1].split(",")[0])
    rest = tools.read_otc_monograph_section(client, document_id=7, section="M013.50", offset=resume)
    assert f"characters {resume + 1} to" in rest


def test_a_superseded_or_order_document_is_never_cited_as_the_current_monograph():
    class Old(FakeClient):
        def regulatory_document(self, document_id, section=None):
            return DOCUMENT | {
                "kind": "order",
                "monographId": None,
                "orderId": "OTC000008",
                "isCurrent": False,
                "supersededAt": "2026-01-01T00:00:00+00:00",
                "sectionText": "Short text." if section else None,
            }

    text = tools.read_otc_monograph_section(Old(), document_id=7, section="M013.50")
    assert text.startswith("SUPERSEDED VERSION")
    assert "order document 7 of OTC000008" in text and "superseded 2026-01-01" in text
    assert "TRUNCATED" not in text


def test_the_client_only_puts_a_real_monograph_id_or_number_in_a_path():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        url = str(request.url)
        body = (
            DOCUMENT if "regulatory-documents" in url else DETAIL if "/monographs/" in url else LIST
        )
        return httpx.Response(200, json=body)

    with OrinyxClient(
        "http://localhost:9", "ork_live_x", transport=httpx.MockTransport(handler)
    ) as client:
        client.monograph("m013")
        client.monographs(ingredient="aspirin", q=None)
        client.regulatory_document(7, section="M013.50")
        for bad in ("../audit/export", "M13", "M0131", "13"):
            with pytest.raises(ValueError):
                client.monograph(bad)
        with pytest.raises(ValueError):
            client.regulatory_document("7/content")
    assert seen[0].endswith("/v1/monographs/M013")
    assert seen[1].endswith("/v1/monographs?ingredient=aspirin")
    assert seen[2].endswith("/v1/regulatory-documents/7?section=M013.50")
    assert len(seen) == 3


def test_the_monograph_tools_are_offered():
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server, shared

    server = build_server(shared(FakeClient()))
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"find_otc_monographs", "get_otc_monograph", "read_otc_monograph_section"} <= names

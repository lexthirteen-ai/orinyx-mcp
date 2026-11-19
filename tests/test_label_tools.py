"""FDA prescribing-label lookup on the connector: cached label section text with its
citation, paged like the monograph reader; reference text, never a verdict."""

import httpx
import pytest
from orinyx_mcp import tools
from orinyx_mcp.client import OrinyxClient

LABELS = {
    "data": [
        {
            "setId": "0ab7c1d2-1111-4a2b-9c3d-123456789abc",
            "rxcui": "11289",
            "drug": "warfarin",
            "matchedVia": "alias",
            "labelVersion": 3,
            "effectiveTime": "20250612",
            "isCurrent": True,
            "retrievedAt": "2026-10-06T14:00:00+00:00",
            "source": "openFDA",
            "sourceUrl": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=0ab7c1d2-1111-4a2b-9c3d-123456789abc",
            "labelGenericName": "WARFARIN SODIUM",
            "labelRoutes": ["ORAL", "INTRAVENOUS"],
            "qualifiersStripped": ["extended-release"],
            "sections": [
                {"section": "boxed_warning", "chars": 812},
                {"section": "dosage_and_administration", "chars": 14022},
            ],
        }
    ],
    "pagination": {"total": 1, "limit": 1, "offset": 0},
}
SECTION = LABELS["data"][0] | {
    "section": "dosage_and_administration",
    "sectionText": "Individualize the dose. Do not exceed the INR target. " * 300,
    "chars": 54 * 300,
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def labels(self, drug):
        self.calls.append(("labels", drug))
        return LABELS

    def label_section(self, set_id, section, version=None, rxcui=None):
        self.calls.append(("section", set_id, section, version, rxcui))
        return SECTION | {"sectionText": SECTION["sectionText"]}


LABEL_URL = (
    "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=0ab7c1d2-1111-4a2b-9c3d-123456789abc"
)


def test_finding_a_label_names_the_set_id_version_sections_and_the_dailymed_address():
    client = FakeClient()
    text = tools.find_fda_label(client, drug="Coumadin")
    assert client.calls == [("labels", "Coumadin")]
    assert "warfarin" in text and "0ab7c1d2-1111-4a2b-9c3d-123456789abc" in text
    assert "version 3" in text and "effective 20250612" in text and "current" in text
    assert "boxed_warning" in text and "dosage_and_administration" in text and "14022" in text
    assert LABEL_URL in text
    assert "matched as alias" in text.lower()
    assert "This label is for WARFARIN SODIUM" in text and "ORAL, INTRAVENOUS" in text
    assert "extended-release" in text and "may not be the one this label describes" in text
    assert "rxcui 11289" in text
    assert "read_fda_label_section" in text  # the next step, by name
    assert "not a verdict" in text.lower()


def test_a_name_the_engine_cannot_place_is_reported_as_unresolved_not_guessed():
    class Missing(FakeClient):
        def labels(self, drug):
            from orinyx_mcp.client import OrinyxApiError

            raise OrinyxApiError(404, "not_found", "That drug name is not in the knowledge base.")

    text = tools.find_fda_label(Missing(), drug="wafarin")
    assert "not in the knowledge base" in text
    assert '"wafarin"' in text  # quoted exactly as given, never respelled
    assert "generic name" in text.lower() and "Do not substitute" in text


def test_reading_a_section_returns_paged_cited_text_with_the_notice_first():
    client = FakeClient()
    text = tools.read_fda_label_section(
        client, set_id="0ab7c1d2-1111-4a2b-9c3d-123456789abc", section="dosage_and_administration"
    )
    assert client.calls == [
        ("section", "0ab7c1d2-1111-4a2b-9c3d-123456789abc", "dosage_and_administration", None, None)
    ]
    assert "Individualize the dose" in text
    assert "This label is for WARFARIN SODIUM" in text
    assert "openFDA label" in text and "SPL set ID 0ab7c1d2" in text and "version 3" in text
    assert "effective 20250612" in text and "retrieved 2026-10-06" in text
    assert LABEL_URL in text
    assert text.index("TRUNCATED: characters 1 to") < text.index("Individualize")  # said FIRST
    assert "offset=" in text
    body = text.split("\n\n")[2]
    assert len(body) <= 6000 and body.rstrip().endswith(".")  # never cut mid-sentence
    assert "not a verdict" in text.lower()
    resume = int(text.split("offset=")[1].split(",")[0])
    rest = tools.read_fda_label_section(
        client,
        set_id="0ab7c1d2-1111-4a2b-9c3d-123456789abc",
        section="dosage_and_administration",
        offset=resume,
    )
    assert f"characters {resume + 1} to" in rest


def test_a_superseded_label_version_is_marked_and_passed_through():
    class Old(FakeClient):
        def label_section(self, set_id, section, version=None, rxcui=None):
            self.calls.append(("section", set_id, section, version, rxcui))
            return SECTION | {
                "labelVersion": 1,
                "isCurrent": False,
                "effectiveTime": "20190101",
                "sectionText": "Older text.",
            }

    client = Old()
    text = tools.read_fda_label_section(
        client,
        set_id="0ab7c1d2-1111-4a2b-9c3d-123456789abc",
        section="boxed_warning",
        version=1,
        rxcui="11289",
    )
    assert client.calls[0][3] == 1 and client.calls[0][4] == "11289"  # both passed through
    assert text.startswith("SUPERSEDED VERSION")
    assert "version 1" in text and "Older text." in text and "TRUNCATED" not in text


def test_the_client_only_puts_a_set_id_and_a_known_section_in_a_path():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=SECTION if "/sections/" in request.url.path else LABELS)

    with OrinyxClient(
        "http://localhost:9", "ork_live_x", transport=httpx.MockTransport(handler)
    ) as client:
        client.labels("warfarin sodium")
        client.label_section("0ab7c1d2-1111-4a2b-9c3d-123456789abc", "boxed_warning")
        client.label_section(
            "0ab7c1d2-1111-4a2b-9c3d-123456789abc", "warnings", version=2, rxcui="11289"
        )
        for bad_set in ("../audit/export", "set id", "x" * 65, ""):
            with pytest.raises(ValueError):
                client.label_section(bad_set, "warnings")
        for bad_section in ("overdose_notes", "warnings/../x", "WARNINGS", ""):
            with pytest.raises(ValueError):
                client.label_section("0ab7c1d2-1111-4a2b-9c3d-123456789abc", bad_section)
        for bad_version in (0, -1, "2", True):
            with pytest.raises(ValueError):
                client.label_section(
                    "0ab7c1d2-1111-4a2b-9c3d-123456789abc", "warnings", version=bad_version
                )
        for bad_rxcui in ("١١", "1 OR 1", "x", ""):
            with pytest.raises(ValueError):
                client.label_section(
                    "0ab7c1d2-1111-4a2b-9c3d-123456789abc", "warnings", rxcui=bad_rxcui
                )
        for bad_drug in ("", " ", "x" * 121):
            with pytest.raises(ValueError):
                client.labels(bad_drug)
    assert seen[0].endswith("/v1/labels?drug=warfarin+sodium")
    assert seen[1].endswith(
        "/v1/labels/0ab7c1d2-1111-4a2b-9c3d-123456789abc/sections/boxed_warning"
    )
    assert seen[2].endswith(
        "/v1/labels/0ab7c1d2-1111-4a2b-9c3d-123456789abc/sections/warnings?version=2&rxcui=11289"
    )
    assert len(seen) == 3


def test_the_label_tools_are_offered_and_the_front_door_names_them():
    pytest.importorskip("mcp")
    from orinyx_mcp.server import build_server, shared

    server = build_server(shared(FakeClient()))
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {"find_fda_label", "read_fda_label_section"} <= names
    assert "find_fda_label" in tools.__all__ and "read_fda_label_section" in tools.__all__

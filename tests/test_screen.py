"""The client-side identifier screen: a copy of the engine's, run before `orinyx observe`
sends anything. A hit names the pattern, never the text it matched."""

from orinyx_mcp import screen


def test_pattern_names_match_the_engine_list():
    # The Orinyx API's identifier screen is the source of truth; a change there must land
    # here too, and this test is the reminder.
    assert [name for name, _ in screen.SCREEN_PATTERNS] == [
        "phone",
        "ssn",
        "date",
        "long_number",
        "mrn",
    ]


def test_each_pattern_hits():
    for text, name in (
        ("call 555-123-4567", "phone"),
        ("ssn 123-45-6789", "ssn"),
        ("seen 10/12/2026", "date"),
        ("seen 2026-10-12", "date"),
        ("acct 12345678", "long_number"),
        ("MRN pending", "mrn"),
    ):
        assert screen.screen_strings([text]) == name, text


def test_clean_orders_pass():
    assert screen.screen_strings(["warfarin 5 mg by mouth daily", None, ""]) is None

"""The operator's exam script: REST only, the server's case order, never a case-set file."""

import json

from evals import product_exam
from orinyx_mcp.client import OrinyxApiError


class FakeClient:
    def __init__(self):
        self.calls, self.queue = [], ["b", "a"]

    def create_vendor(self, name, product, contact_email):
        if name == "Taken":
            raise OrinyxApiError(409, "conflict", "exists")
        return {"id": 3, "name": name, "product": product}

    def vendors(self):
        return {"data": [{"id": 9, "name": "Taken", "product": "P"}]}

    def open_exam(self, vendor_id, case_set, version):
        return {"id": 12, "vendorId": vendor_id, "caseSetId": case_set, "caseSetVersion": version}

    def exam_cases(self, run_id):
        self.calls_listed = True
        return {"cases": [{"caseId": case_id} for case_id in self.queue]}

    def exam_next_case(self, run_id):
        raise AssertionError("operator-entered answers must not start the server's clock")

    def exam_submit(self, run_id, batch):
        self.calls.append(batch[0])
        return [{"caseId": batch[0]["caseId"], "cached": False}]

    def exam_finish(self, run_id, allow_partial=False):
        self.calls.append("finish")

    def exam_report(self, run_id):
        return {
            "runId": run_id,
            "caseSet": {"id": "s", "version": "1", "clinicallyReviewed": False},
            "verdict": "pass",
            "metrics": {},
            "speed": {},
            "cases": [],
        }


def test_setup_and_open_print_ids():
    client = FakeClient()
    made = product_exam.run(
        ["setup", "--name", "Acme", "--product", "Scribe 2", "--contact-email", "q@a.example"],
        client,
    )
    assert made.startswith("vendor 3 created")
    again = product_exam.run(
        ["setup", "--name", "Taken", "--product", "P", "--contact-email", "q@a.example"], client
    )
    assert again.startswith("vendor 9 already exists")
    opened = product_exam.run(
        ["open", "--vendor-id", "3", "--case-set", "ambient-core", "--version", "1.0.0"], client
    )
    assert "run 12 is open" in opened


def test_answers_are_recorded_in_the_servers_order_and_an_empty_answer_is_allowed(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            [{"caseId": "a", "claims": [{"drug": "warfarin"}]}, {"caseId": "b", "claims": []}]
        )
    )
    client = FakeClient()
    out = product_exam.run(["answer", "--run", "12", "--answers", str(answers), "--finish"], client)
    assert [c["caseId"] for c in client.calls[:2]] == ["b", "a"]
    assert client.calls[0]["assertions"] == [] and client.calls[2] == "finish"
    assert "recorded 2 answers" in out and "REHEARSAL" in out


def test_a_coding_answers_file_sends_the_codes_as_written_and_no_date(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps([{"caseId": "a", "codes": ["E11.9", "r05.9"]}, {"caseId": "b", "codes": []}])
    )
    client = FakeClient()
    out = product_exam.run(["answer", "--run", "12", "--answers", str(answers)], client)
    assert client.calls == [
        {"caseId": "b", "codes": []},
        {"caseId": "a", "codes": ["E11.9", "r05.9"]},
    ]
    assert "recorded 2 answers" in out


def test_a_code_that_is_not_a_string_is_refused_not_converted(tmp_path):
    import pytest

    bad = tmp_path / "answers.json"
    bad.write_text(json.dumps([{"caseId": "a", "codes": [250.0]}, {"caseId": "b", "codes": []}]))
    client = FakeClient()
    with pytest.raises(ValueError, match='"codes"'):
        product_exam.run(["answer", "--run", "12", "--answers", str(bad)], client)
    assert client.calls == []


def test_a_case_with_no_entry_stops_the_run_instead_of_guessing(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps([{"caseId": "a", "claims": []}]))
    client = FakeClient()
    out = product_exam.run(["answer", "--run", "12", "--answers", str(answers)], client)
    assert out.startswith("stopped") and "starting with b" in out and client.calls == []


def test_a_malformed_answers_file_is_a_plain_message(tmp_path):
    import pytest

    bad = tmp_path / "answers.json"
    bad.write_text('[{"claims": []}]')
    with pytest.raises(ValueError, match="JSON list"):
        product_exam.run(["answer", "--run", "12", "--answers", str(bad)], FakeClient())

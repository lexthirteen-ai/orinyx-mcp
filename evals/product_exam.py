"""Operator commands for a scored product exam on a running Orinyx server (REST only).

    export ORINYX_API_URL=https://<host>      ORINYX_API_KEY=<operator key>
    python evals/product_exam.py setup  --name "Acme" --product "Scribe 2.1 (prompt v3)" \\
        --contact-email qa@acme.example
    python evals/product_exam.py open   --vendor-id 3 --case-set ambient-core --version 1.0.0
    python evals/product_exam.py open --vendor-id 3 --case-set ambient-core \\
        --version 1.0.0 --operator-entry
    python evals/product_exam.py answer --run 12 --answers answers.json [--finish]
    python evals/product_exam.py report --run 12

`setup` and `open` need an OPERATOR key (a quality-lead or admin user's key with
`benchmark:read` and `benchmark:write`). A product that can connect an agent sits the exam
itself through the connector (`start_a_test`); `answer` is for a product that cannot: the
operator first opens a SEPARATE sitting with `--operator-entry`, then runs the product on
each case by hand and records what it said in `answers.json`,
a list of `{"caseId": ..., "claims": [...]}`, `{"caseId": ..., "replyText": "..."}` for a
patient-message exam, or `{"caseId": ..., "codes": ["E11.9", ...]}` for an ICD-10-CM coding
exam (no date: the case has its date of service). Answers recorded this way are NOT timed: the
report says speed was not measured. If you timed the product yourself, report that figure
separately as your own measurement. The product's name, version and prompt belong in
`--product`, because a different prompt is a different product.

Nothing here imports the engine or reads a case-set file: the file is the answer key and
stays on the server. Prints ids and the report text; the key is read from the environment.
The engine entry-mode migration and enforcement must deploy before this update. A sitting's
mode cannot be changed, and manual entry cannot complete a hosted-MCP vendor sitting.
"""

import argparse
import json
import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `python evals/product_exam.py`
    sys.path.insert(0, str(REPO))

from orinyx_mcp import tools  # noqa: E402
from orinyx_mcp.client import OrinyxApiError, OrinyxClient  # noqa: E402


def _setup(client: OrinyxClient, args) -> str:
    try:
        vendor = client.create_vendor(args.name, args.product, args.contact_email)
    except OrinyxApiError as exc:
        if exc.status != 409:
            raise
        matches = [v for v in client.vendors().get("data", []) if v.get("name") == args.name]
        if not matches:
            raise
        vendor = matches[0]
        return f"vendor {vendor['id']} already exists: {vendor['name']} / {vendor['product']}"
    return f"vendor {vendor['id']} created: {vendor['name']} / {vendor['product']}"


def _open(client: OrinyxClient, args) -> str:
    mode = "operator" if args.operator_entry else "hosted_mcp"
    run = client.open_exam(args.vendor_id, args.case_set, args.version, entry_mode=mode)
    return (
        f"run {run['id']} is open for vendor {run.get('vendorId')} on {run.get('caseSetId')} "
        f"{run.get('caseSetVersion')}. Entry mode: {mode}."
    )


def _answer(client: OrinyxClient, args) -> str:
    try:
        answers = json.loads(pathlib.Path(args.answers).read_text())
        by_case = {}
        for a in answers:
            if "replyText" in a:
                by_case[a["caseId"]] = {"replyText": str(a["replyText"])}
            elif "codes" in a:
                # Codes go as written (the server reads them against the case's date of
                # service); a code that is not a string is refused, never converted.
                codes = a["codes"]
                if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
                    raise TypeError("codes must be a list of strings")
                by_case[a["caseId"]] = {"codes": codes}
            else:
                by_case[a["caseId"]] = {"assertions": list(a.get("claims", []))}
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError(
            'the answers file must be a JSON list of {"caseId": ..., "claims": [...]}, '
            '{"caseId": ..., "replyText": "..."} or {"caseId": ..., "codes": ["E11.9", ...]}'
        ) from None
    # The whole paper is listed at once, on purpose: answers typed in by an operator were
    # not timed by the server, and the report must say speed was not measured, not report
    # how fast this script is.
    wanted = [case["caseId"] for case in client.exam_cases(args.run).get("cases", [])]
    missing = [case_id for case_id in wanted if case_id not in by_case]
    if missing:
        return (
            f"stopped: the answers file has nothing for {len(missing)} case(s), starting with "
            f"{missing[0]}. Nothing was recorded. Add an entry for each (an empty claims or "
            "codes list is a valid answer) and run again."
        )
    for case_id in wanted:
        client.exam_submit(args.run, [{"caseId": case_id, **by_case[case_id]}])
    lines = [f"recorded {len(wanted)} answers for run {args.run}; no case remains."]
    if args.finish:
        client.exam_finish(args.run)
        lines.append(tools.get_exam_report(client, run_id=args.run))
    return "\n".join(lines)


def _report(client: OrinyxClient, args) -> str:
    return tools.get_exam_report(client, run_id=args.run)


def run(argv: list[str], client: OrinyxClient) -> str:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="register the product under test")
    setup.add_argument("--name", required=True)
    setup.add_argument("--product", required=True, help="product, version and prompt")
    setup.add_argument("--contact-email", required=True)
    opened = sub.add_parser("open", help="open an exam run on a registered test set")
    opened.add_argument("--vendor-id", type=int, required=True)
    opened.add_argument("--case-set", required=True)
    opened.add_argument("--version", required=True)
    opened.add_argument(
        "--operator-entry",
        action="store_true",
        help="open a separate untimed operator-entry sitting",
    )
    answer = sub.add_parser("answer", help="record a product's answers from a file")
    answer.add_argument("--run", type=int, required=True)
    answer.add_argument("--answers", required=True)
    answer.add_argument("--finish", action="store_true", help="finish and print the report")
    report = sub.add_parser("report", help="print the report of a finished run")
    report.add_argument("--run", type=int, required=True)
    args = parser.parse_args(argv)
    handler = {"setup": _setup, "open": _open, "answer": _answer, "report": _report}
    return handler[args.command](client, args)


def main(argv: list[str] | None = None) -> int:
    url, key = os.environ.get("ORINYX_API_URL"), os.environ.get("ORINYX_API_KEY")
    if not url or not key:
        print("Set ORINYX_API_URL and ORINYX_API_KEY in the environment.", file=sys.stderr)
        return 1
    try:
        with OrinyxClient(url, key) as client:
            print(run(sys.argv[1:] if argv is None else argv, client))
    except (OrinyxApiError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

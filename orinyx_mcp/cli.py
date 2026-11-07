"""`orinyx`: a command-line wrapper over the REST API for frameworks that do not speak
MCP (LangChain, CrewAI, AutoGen call it as a subprocess, or import OrinyxClient).
`orinyx observe` reads an agent's saved output instead and checks every order in it, so the
agent under test does not choose what gets checked.

Credentials come from the environment only (ORINYX_API_URL, ORINYX_API_KEY), never from
flags, so an API key never lands in shell history. Exit codes: 0 clean, 2 flagged (a
label flag, or an order that cannot be read as written), 3 not verified (no flag but an
abstain: the label did not settle a claim), 1 error — so a calling framework can branch on
the result without parsing text.
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from orinyx_mcp.client import (
    UNUSABLE_CONFIG,
    InsecureUrlError,
    OrinyxApiError,
    OrinyxClient,
    VerificationResult,
)
from orinyx_mcp.config import ConfigError
from orinyx_mcp.screen import SCREEN_PATTERNS, Patterns, patterns_for, screen_orders
from orinyx_mcp.text import render_accuracy_lines, render_run_text
from orinyx_mcp.verdicts import KNOWN_VERDICTS, aggregate_disagreements, count_verdicts

EXIT_CLEAN, EXIT_ERROR, EXIT_FLAGGED, EXIT_NOT_VERIFIED = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a usage error, which here means "flagged". Usage errors exit 1.

    A usage error never repeats an argument's value: a key passed by mistake (`--api-key
    <key>`) must not be printed back to the terminal, or to a CI log. Unrecognised options
    are named without their values; any other value argparse would quote is left out."""

    def parse_args(self, args=None, namespace=None):  # type: ignore[override]
        args = sys.argv[1:] if args is None else list(args)
        namespace, extras = self.parse_known_args(args, namespace)
        if extras:
            self.error(_unrecognized(extras, args))
        return namespace

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {_without_values(message)}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


# An option name as written: `--tool-version`, `-x`. Lower case only, so a mixed-case key
# typed with leading dashes is never taken for a name.
_OPTION_NAME = re.compile(r"--[a-z0-9][a-z0-9_-]*|-[A-Za-z]")
# A value as argparse quotes it: Python's repr of a string.
_REPR = r"""(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
# argparse's messages that quote a value, and the same message without it.
_QUOTED_VALUE = (
    (re.compile(rf"invalid choice: {_REPR}"), "invalid choice"),
    (re.compile(rf"(invalid \S+ value): {_REPR}"), r"\1"),
    (re.compile(rf"ignored explicit argument {_REPR}"), "ignored explicit argument"),
    (re.compile(rf"unknown parser {_REPR}"), "unknown parser"),
)
_AMBIGUOUS = re.compile(r"ambiguous option: (.*) could match (.*)", re.DOTALL)


def _option_name(word: str) -> str | None:
    """The option a command-line word names, without any `=value`; None for a value, or for
    a word whose name and value cannot be told apart (`-k<value>`)."""
    name = word.split("=", 1)[0] if word.startswith("--") else word
    return name if _OPTION_NAME.fullmatch(name) else None


def _positions(extras: Sequence[str], args: Sequence[str]) -> list[int]:
    """Where each left-over word stood in `args`. argparse keeps them in command-line order, so
    each is placed at the latest spot it can have come from; a word that cannot be placed
    counts as standing at the end."""
    positions, end = [], len(args)
    for word in reversed(extras):
        end = next((i for i in reversed(range(end)) if args[i] == word), -1)
        positions.append(end if end >= 0 else len(args))
    return positions[::-1]


def _unrecognized(extras: Sequence[str], args: Sequence[str]) -> str:
    names = list(map(_option_name, extras))
    if "--" in args:
        # Past the first bare `--` argparse reads every word as a value, so none is named
        # there. The `--` itself is named: it is never a value.
        separator = args.index("--")
        names = [
            "--" if at == separator else name if at < separator else None
            for name, at in zip(names, _positions(extras, args), strict=True)
        ]
    names = [name for name in names if name]
    hidden = len(extras) - len(names)
    if not hidden:
        return f"unrecognized arguments: {' '.join(names)}"
    values = f"{hidden} value{'s' if hidden != 1 else ''} not shown"
    if not names:
        return f"unrecognized arguments: {values}"
    return f"unrecognized arguments: {' '.join(names)} (plus {values})"


def _without_values(message: str) -> str:
    for pattern, replacement in _QUOTED_VALUE:
        message = pattern.sub(replacement, message, count=1)
    ambiguous = _AMBIGUOUS.fullmatch(message)
    if ambiguous:
        name = _option_name(ambiguous.group(1))
        option = f"ambiguous option: {name}" if name else "ambiguous option"
        message = f"{option} could match {ambiguous.group(2)}"
    return message


_FORMATS = {"csv": "csv", "pdf": "pdf", "report": "report.pdf"}

ClientFactory = Callable[[str, str], OrinyxClient]


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="orinyx",
        description=(
            "Verify medication claims with Orinyx. Exit 0 clean, 2 flagged, "
            "3 not verified (no flag, but at least one claim abstained), 1 error."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    verify = sub.add_parser("verify", help="verify claims from a JSON file")
    verify.add_argument(
        "--file",
        required=True,
        type=Path,
        help="JSON: a list of claims, or a full request body with an 'assertions' list",
    )
    verify.add_argument("--tool", help="name of the AI tool whose output is being tested")
    verify.add_argument("--tool-version", help="its version")
    verify.add_argument("--check-interactions", action="store_true")
    verify.add_argument("--json", action="store_true", help="print the API JSON instead of text")

    get = sub.add_parser("get", help="read a saved run")
    get.add_argument("run_id")
    get.add_argument("--json", action="store_true")

    accuracy = sub.add_parser("accuracy", help="the physician-review tally for a run")
    accuracy.add_argument("run_id")
    accuracy.add_argument("--json", action="store_true")

    export = sub.add_parser("export", help="download csv, pdf (full audit) or report (one page)")
    export.add_argument("run_id")
    export.add_argument("--format", choices=sorted(_FORMATS), default="csv")
    export.add_argument("--out", required=True, type=Path)

    observe = sub.add_parser(
        "observe",
        help="check every order in an agent's saved output (one run per record)",
        description=(
            "Read an agent's saved output and verify every order in it, one run per record. "
            ".txt: the file is one record, one order per line. .jsonl / .json: each record's "
            "--field holds a list of orders or one string of them, one per line. A directory "
            "reads its .txt, .jsonl and .json files. Synthetic test data only: a record that "
            "looks like it holds a patient identifier refuses the whole run before anything "
            "is sent."
        ),
    )
    observe.add_argument("paths", nargs="+", type=Path, help="files or directories")
    observe.add_argument(
        "--field",
        default="orders",
        help="dotted path to the orders in each JSON record (default: orders)",
    )
    observe.add_argument("--tool", help="name of the AI tool whose output is being tested")
    observe.add_argument("--tool-version", help="its version")
    observe.add_argument("--check-interactions", action="store_true")
    observe.add_argument("--json", action="store_true", help="print the runs as JSON")
    return parser


def _load_claims(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict) and isinstance(data.get("assertions"), list):
        return data["assertions"], data
    raise ValueError("expected a JSON list of claims or an object with an 'assertions' list")


def _run_exit(result) -> int:
    counts = count_verdicts(result.verdicts)
    disagreements = aggregate_disagreements(counts, result.aggregate)
    if disagreements:
        print(
            "orinyx: NOT VERIFIED: aggregate/verdict rows disagree: " + ", ".join(disagreements),
            file=sys.stderr,
        )
        return EXIT_ERROR
    if counts.flagged:
        return EXIT_FLAGGED
    if counts.not_verified:
        return EXIT_NOT_VERIFIED  # the label did not settle at least one claim: not "clean"
    return EXIT_CLEAN


# --- observe -------------------------------------------------------------------------------

# The API's limits on POST /v1/verifications/orders. A record over them is refused, never
# split: orders checked together (--check-interactions) must stay in one run.
MAX_ORDERS_PER_RUN, MAX_ORDER_CHARS = 50, 500
_OBSERVED_SUFFIXES = (".jsonl", ".json", ".txt")


@dataclass(frozen=True)
class _Record:
    source: str  # "<file name>#<record index>"
    orders: list[str]  # empty: the record has no orders under --field


def _unreadable(number: int, exc: OSError) -> ValueError:
    return ValueError(f"path {number}: cannot be read ({exc.strerror or type(exc).__name__})")


def _observed_files(paths: Sequence[Path]) -> list[tuple[int, Path]]:
    """Each file to read, with the number of the path argument it came from. An error about
    a path argument names that number, not the path: a key given here by mistake must not be
    printed back. A file that is read names itself by its file name in later errors and in
    each record's source."""
    files: list[tuple[int, Path]] = []
    for number, path in enumerate(paths, start=1):
        try:
            if path.is_dir():
                found = sorted(
                    p for p in path.iterdir() if p.is_file() and p.suffix in _OBSERVED_SUFFIXES
                )
                files.extend((number, p) for p in found)
            elif path.suffix in _OBSERVED_SUFFIXES:
                files.append((number, path))
            else:
                raise ValueError(
                    f"path {number}: expected a .txt, .jsonl or .json file, or a directory"
                )
        except OSError as exc:
            raise _unreadable(number, exc) from None
    return files


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _orders_at(record: object, field: str, source: str) -> list[str]:
    value = record
    for key in field.split("."):
        if not isinstance(value, dict) or key not in value:
            return []
        value = value[key]
    if value is None:
        return []
    if isinstance(value, str):
        return _lines(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError(f"{source}: '{field}' is neither a string nor a list of strings")


def _load_observed(paths: Sequence[Path], field: str) -> list[_Record]:
    records: list[_Record] = []
    for number, path in _observed_files(paths):
        try:
            text = path.read_text()
        except OSError as exc:
            raise _unreadable(number, exc) from None
        if path.suffix == ".txt":
            records.append(_Record(f"{path.name}#0", _lines(text)))
            continue
        if path.suffix == ".jsonl":
            data = []
            for index, line in enumerate(_lines(text)):
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path.name}#{index}: not JSON ({exc.msg})") from None
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}: not JSON ({exc.msg})") from None
            data = data if isinstance(data, list) else [data]
        for index, record in enumerate(data):
            source = f"{path.name}#{index}"
            records.append(_Record(source, _orders_at(record, field, source)))
    return records


def _preflight(records: Sequence[_Record], patterns: Patterns = SCREEN_PATTERNS) -> None:
    """Fail closed before any request: one refused record stops the whole invocation."""
    for record in records:
        if len(record.orders) > MAX_ORDERS_PER_RUN:
            raise ValueError(
                f"{record.source}: {len(record.orders)} orders; one run takes at most "
                f"{MAX_ORDERS_PER_RUN}. Nothing was sent."
            )
        for number, order in enumerate(record.orders, start=1):
            if len(order) > MAX_ORDER_CHARS:
                raise ValueError(
                    f"{record.source}: order {number} is {len(order)} characters; the API "
                    f"takes at most {MAX_ORDER_CHARS} characters. Nothing was sent."
                )
        hit = screen_orders(record.orders, patterns)
        if hit:
            # The pattern's name only, never the text it matched.
            raise ValueError(
                f"{record.source}: looks like it holds a patient identifier ({hit}). Nothing "
                "was sent. Observe synthetic test data only."
            )


def _print_observed(runs: list[tuple[str, VerificationResult]], skipped: list[str], args) -> None:
    if args.json:
        body = {
            "runs": [{"source": s, "runId": r.run_id, "raw": r.raw} for s, r in runs],
            "skipped": skipped,
        }
        print(json.dumps(body, indent=2))
        return
    totals = {"claims": 0, "flagged": 0, "supported": 0, "abstain": 0}
    for source, result in runs:
        derived = count_verdicts(result.verdicts)
        counts = {
            "claims": derived.total,
            "flagged": derived.flagged,
            "supported": derived.supported,
            "abstain": derived.not_verified,
        }
        totals = {key: totals[key] + counts[key] for key in totals}
        print(
            f"{source}  run {result.run_id}  {counts['claims']} claims: {counts['flagged']} "
            f"flagged, {counts['supported']} supported, {counts['abstain']} abstained"
        )
        for row in result.verdicts:
            if row.verdict not in KNOWN_VERDICTS:
                print(f"  NOT VERIFIED: unknown verdict {row.verdict!r}")
    if runs:
        print(
            f"Observed {len(runs)} record{'s' if len(runs) != 1 else ''}, {totals['claims']} "
            f"claims: {totals['flagged']} flagged, {totals['supported']} supported, "
            f"{totals['abstain']} abstained. Read one in full: orinyx get <run id>"
        )
    if skipped:
        plural = "s" if len(skipped) != 1 else ""
        print(f"Skipped {len(skipped)} record{plural} without '{args.field}': {', '.join(skipped)}")


def _observe(client: OrinyxClient, args) -> int:
    records = _load_observed(args.paths, args.field)
    _preflight(records)  # this package's copy first: a hit refuses before any request
    patterns = patterns_for(client)  # the API's screen, when this copy is not it
    if patterns is not SCREEN_PATTERNS:
        _preflight(records, patterns)
    to_check = [record for record in records if record.orders]
    skipped = [record.source for record in records if not record.orders]
    if not to_check:
        raise ValueError(f"no orders under '{args.field}' in the given files; nothing was checked")
    runs: list[tuple[str, VerificationResult]] = []
    for record in to_check:
        try:
            result = client.verify_orders(
                record.orders,
                tool_name=args.tool,
                tool_version=args.tool_version,
                check_interactions=args.check_interactions,
            )
        except OrinyxApiError as exc:
            _print_observed(runs, skipped, args)  # what was already recorded stays visible
            print(f"orinyx: {record.source}: {exc.message or exc.code}", file=sys.stderr)
            return EXIT_ERROR
        runs.append((record.source, result))
    _print_observed(runs, skipped, args)
    codes = {_run_exit(result) for _, result in runs}
    for code in (EXIT_ERROR, EXIT_FLAGGED, EXIT_NOT_VERIFIED):
        if code in codes:
            return code
    return EXIT_CLEAN


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None) -> int:
    args = _parser().parse_args(argv)
    url = os.environ.get("ORINYX_API_URL")
    key = os.environ.get("ORINYX_API_KEY")
    if not url or not key:
        print("Set ORINYX_API_URL and ORINYX_API_KEY in the environment.", file=sys.stderr)
        return EXIT_ERROR
    factory = client_factory or OrinyxClient
    try:
        client = factory(url, key)
    except (InsecureUrlError, ConfigError) as exc:
        print(f"orinyx: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, httpx.InvalidURL):
        print(f"orinyx: {UNUSABLE_CONFIG}", file=sys.stderr)
        return EXIT_ERROR
    try:
        if args.command == "verify":
            claims, body = _load_claims(args.file)
            result = client.verify(
                claims,
                tool_name=args.tool or body.get("toolName"),
                tool_version=args.tool_version or body.get("toolVersion"),
                check_interactions=args.check_interactions or bool(body.get("checkInteractions")),
            )
            print(json.dumps(result.raw, indent=2) if args.json else render_run_text(result.raw))
            return _run_exit(result)
        if args.command == "get":
            result = client.get_run(args.run_id)
            accuracy = None
            if not args.json:
                try:
                    accuracy = client.accuracy(args.run_id)
                except OrinyxApiError:
                    accuracy = None
            print(
                json.dumps(result.raw, indent=2)
                if args.json
                else render_run_text(result.raw, accuracy)
            )
            return _run_exit(result)
        if args.command == "accuracy":
            accuracy = client.accuracy(args.run_id)
            if args.json:
                print(json.dumps(accuracy, indent=2))
            else:
                lines = render_accuracy_lines(accuracy) or [
                    f"Run {args.run_id}: no physician review yet, so no accuracy numbers."
                ]
                print("\n".join(lines))
            return EXIT_CLEAN
        if args.command == "export":
            file = client.export(args.run_id, _FORMATS[args.format])  # type: ignore[arg-type]
            args.out.write_bytes(file.content)
            print(f"wrote {args.out} ({file.media_type}, {len(file.content)} bytes)")
            return EXIT_CLEAN
        if args.command == "observe":
            return _observe(client, args)
    except OrinyxApiError as exc:
        print(f"orinyx: {exc.message or exc.code}", file=sys.stderr)
        return EXIT_ERROR
    except (OSError, ValueError) as exc:
        print(f"orinyx: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())

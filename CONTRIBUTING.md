# Contributing to orinyx-mcp

Thank you for helping. This file covers the development setup and the rules every change must
keep. To report a vulnerability, follow [SECURITY.md](SECURITY.md), not a public issue.

## Development setup

Python 3.11 or later.

```bash
git clone https://github.com/lexthirteen-ai/orinyx-mcp.git && cd orinyx-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # no database, no engine: fakes stand in for the API
ruff check . && ruff format --check .
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the same checks with ruff
0.15.20, plus `pip-audit` on `requirements.lock`. Newer ruff releases also format Markdown code
blocks, so run that version if the format check disagrees with CI:
`pip install "ruff==0.15.20"`.

## Rules a change must keep

### This package is a client

It holds no rules, no reference data and no verdict logic: every clinical result comes from
the Orinyx API over REST with the caller's own credential. Nothing in the package may import
the Orinyx engine, even when it is installed beside this package.
`tests/test_client.py::test_nothing_in_the_package_imports_the_engine` enforces this.

### Output contracts do not change without an owner decision

Agents, CI jobs and published examples depend on these exactly. A pull request that changes
any of them needs a decision from the repository owner first:

- **Readable text** printed by the tools and the CLI (`orinyx_mcp/text.py` and the report
  renderers in `orinyx_mcp/tools.py`). No line is added, reordered or reworded.
- **Fixed strings:** `Run id: <uuid>` (parsed by `evals/mcp_local_check.py`) and
  `UNREADABLE - do not act on it`.
- **`--json`** prints the API's response unchanged.
- **Exit codes:**

  | Code | Meaning |
  |---|---|
  | 0 | clean |
  | 1 | error or usage error |
  | 2 | flagged or unreadable |
  | 3 | not verified |

  A usage error is never 2, so a typo cannot read as "flagged".
- **Tool surfaces:** tool names, input schemas, verdict words and severities.

### Synthetic data only

Never put real patient records, names, dates or record numbers anywhere: in tests, fixtures,
examples, issues, pull requests or logs you paste. Use synthetic data throughout.

## Pull requests

- Keep a pull request to one change, and say what it changes and why.
- `pytest` and both ruff checks pass locally before you open it. CI runs on every pull
  request.
- Add or update tests with a change in behaviour.

## License

This project is licensed under the [Apache License 2.0](LICENSE). Unless you explicitly state
otherwise, any contribution you intentionally submit for inclusion in the project is licensed
under the same terms (Apache-2.0, section 5), without any additional terms or conditions.

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
  renderer in `orinyx_mcp/tools/reports.py`, the tools under `orinyx_mcp/tools/` and the prose in
  `orinyx_mcp/copy.py`). No line is added, reordered or reworded.
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

## Publishing to PyPI (owner checklist)

The repository is already public and has GitHub release tags; those do not upload a
package to PyPI. Before the November 9 announcement:

1. Merge the publishing workflow and deploy the engine's self-serve key endpoints
   before advertising that credential path.
2. In [GitHub's `pypi` environment](https://github.com/lexthirteen-ai/orinyx-mcp/settings/environments),
   retain the required owner review and add a **tag** deployment rule such as `v*`.
   A rule allowing only the `main` branch blocks the tag-triggered publishing job.
3. At https://pypi.org/manage/account/publishing/, add a pending trusted publisher
   (or add one to an existing project) with these exact values:
   - PyPI project: `orinyx-mcp`
   - GitHub owner: `lexthirteen-ai`
   - Repository: `orinyx-mcp`
   - Workflow filename: `publish.yml` (not a path or `release.yml`)
   - Environment: `pypi`
   No PyPI API token or GitHub repository secret is needed.
4. This work targets **0.1.5**, alongside the other changes accumulating on `main`.
   Merge the engine API first, then the dashboard/MCP consumers; do not copy engine
   authorization into either client. The package version is set to `0.1.5`; review
   the combined release notes before tagging. Existing tags must not be moved. From
   the reviewed release commit, create and push the matching `v0.1.5` tag. The workflow refuses a
   tag/version mismatch, tests the package, then builds a wheel and sdist with
   `python -I -m build` and validates their metadata with Twine. Only stable
   `v<major>.<minor>.<patch>` tags select PyPI; prerelease tags are refused.
   `scripts/lint_release_workflow.py` governs the workflow, and
   `scripts/check_dist.py` validates both archives against the version's exact
   manifest in `release/manifests/`, the source tree and the Registry marker.
   Update that manifest whenever packaged files change. Checksums and an exact
   file-list check are repeated in the publishing job before upload.
5. Approve the `pypi` environment deployment. Only the publishing job has
   `id-token: write`; it downloads the build artifact and uses
   `pypa/gh-action-pypi-publish` with OIDC, with no source checkout or build there.
6. Verify https://pypi.org/project/orinyx-mcp/ and install the new version in a clean
   environment (`pip install orinyx-mcp`); check `orinyx --help`,
   `orinyx-mcp --version` and `uvx orinyx-mcp stdio` with your own API environment.

Do not announce PyPI availability until the upload and clean install succeed.
The workflow does not change repository visibility, environment policies or PyPI
account settings, and never creates a release tag itself.

## License

This project is licensed under the [Apache License 2.0](LICENSE). Unless you explicitly state
otherwise, any contribution you intentionally submit for inclusion in the project is licensed
under the same terms (Apache-2.0, section 5), without any additional terms or conditions.

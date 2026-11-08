# Changelog

All notable changes to this project are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Planned release: **0.1.5**.

### Added

- Tag-driven PyPI publishing through GitHub OIDC and the protected `pypi` environment.
  The workflow tests and builds the package, requires a matching version tag, and publishes
  only the resulting wheel and source distribution without a long-lived PyPI token.
- Local installation with `pip install orinyx-mcp` and `uvx orinyx-mcp stdio`, CLI examples,
  and the engine's session-only self-serve key flow. The engine must be deployed first;
  developer keys carry only `verify:read` and `verify:write` and expire within 90 days.

### Changed

- Packaging for PyPI: the package metadata is complete (authors, keywords, classifiers and
  project URLs), dependency ranges stop before the next major version, the build backend has
  a bounded range, the source distribution holds a reviewed list of files, and the README's
  links and logo are absolute so they work on the PyPI page. The lowest allowed versions rise
  to `httpx` 0.28, `pydantic` 2.12, `starlette` 1.3.1 and `uvicorn` 0.31.1.
- Before it sends orders, `orinyx observe` asks the Orinyx API for the current identifier
  screen. If the API serves a different list, `observe` screens with that list. If the API
  says its screen differs but does not send it, `observe` refuses rather than screen with a
  stale list. If the API does not serve the list or cannot answer, the local copy is used; a
  failed request is logged.
- On the first tool call, the MCP server checks its copies of the label sections and the
  identifier screen against the API's, in the background, when the API serves those lists. A
  difference is logged. The API does not serve them yet, so for now the local copies are used.

## [0.1.4] - 2026-11-05

### Changed

- Developer accounts can use the five FDA reference lookups: `find_fda_label`,
  `read_fda_label_section`, `find_otc_monographs`, `get_otc_monograph` and
  `read_otc_monograph_section`. `start_a_test` lists them under LOOK SOMETHING UP for a
  developer account. They return reference text, not a verdict, and are not charged against
  the monthly checks of the free plan. On a label lookup the reply says how the name was
  matched, and a formulation or salt Orinyx stripped from the name is shown as a caution.
- Still staff-only: a label's version history and diff, a monograph's version history and its
  separate orders listing, and a regulatory document's content. Product (vendor) accounts are still refused
  every lookup. The change is in the Orinyx API; tool names and input schemas are unchanged.

## [0.1.3] - 2026-11-05

### Added

- Every result row names the Orinyx check that produced it (beta). When Orinyx sends a run's
  `checks` list, the tool text of `verify_order_text`, `verify_medications` and
  `get_verification`, and the `orinyx verify` text output, carry a block headed
  "Checks (beta release candidates; Orinyx names the check behind each row):". It names each
  check by the label Orinyx sends, with the rows it produced and its own counts (flagged,
  unreadable, supported, not verified); unreadable rows are never counted as flagged. The
  block follows the existing output, so the earlier lines are unchanged and `Run id:` is
  still the last line of tool text. A run without `checks` renders as in 0.1.2.
- Install docs: a new `docs/TROUBLESHOOTING.md`, a "Supported environments" section in the
  README and an "Official package" section in SECURITY.md. The README and SECURITY.md name
  the only official package, `orinyx-mcp`, published only from
  `github.com/lexthirteen-ai/orinyx-mcp`.
- `orinyx-mcp stdio` starts the stdio MCP server, the same server as `python -m orinyx_mcp`,
  and `orinyx-mcp --version` prints the installed version.

### Changed

- The server instructions say every result row names the Orinyx check that produced it
  (Medication Claims, Semantic Mapping or Source Evidence), and that these checks are beta
  release candidates, not production-ready, each deciding with deterministic rules only. The
  descriptions of `verify_medications`, `verify_order_text` and `get_verification` say each
  row names the check that produced it (beta). Tool names and input schemas are unchanged.
- Install docs: the README's Installation section puts the hosted connector first as the
  self-serve path, with Claude Code, Claude Desktop and Cursor steps, and says the stdio
  server, the CLI and CI need a key issued by Orinyx. Every example that holds a key warns
  never to commit a client config file that holds one.
- `orinyx-mcp` with any argument other than `stdio` or `--version` (for example
  `orinyx-mcp serve`) now exits 1 with a usage line instead of starting the network server.
  `orinyx-mcp` with no argument is still the network server, unchanged.

## [0.1.2] - 2026-11-03

### Changed

- Docs (2026-11-03): repository links now use `lexthirteen-ai/orinyx-mcp`; restored two
  disclosures a tidy edit had dropped (the IV acetaminophen fix does not cover CDS Hooks,
  telehealth or transcript extraction; the smoke test's IV step covers `IV` only); the
  Acknowledgements say the optional models are not enabled on the hosted service.

## [0.1.1] - 2026-11-02

### Added

- The not-for-clinical-use statement opens the server instructions and every tool description,
  the README's first screen and the release notes; tests pin the exact text (gate B15).

### Changed

- `verify_medications`'s description asks for one patient's medications per call, and says
  that when the call states one route for a drug, that route is carried onto the drug's
  frequency claims that state none. Nothing is carried for a drug whose claims state two
  routes or one Orinyx cannot read, or whose drug name names a different route. The tool name
  and input schema are unchanged.
- The IV acetaminophen known limit: oral-label frequency is fixed on the orders path and on
  `verify_medications` structured runs; not CDS Hooks, telehealth or transcript extraction;
  IVP is not read as a route. Its disclosed limits are
  listed with it. See
  [Known limits](docs/RELEASE_NOTES_2026-11-02.md#known-limits).
- The release notes are dated with the publication date (`docs/RELEASE_NOTES_2026-11-02.md`)
  and name orinyx-mcp 0.1.1. A new known limit says that a NOT VERIFIED row shows no
  citation, even when Orinyx's result names a specific label.

## [0.1.0] - 2026-10-29

Limited testing release of the hosted connector `https://orinyx-mcp.fly.dev/mcp`, with
orinyx-mcp 0.1.0 and Orinyx engine 0.3.1. Synthetic data only. The current release notes,
which cover 0.1.0 and 0.1.1 and list every known limit, are in
[docs/RELEASE_NOTES_2026-11-02.md](docs/RELEASE_NOTES_2026-11-02.md).

### Added

- **Orders as written** (`verify_order_text`): each order is split into a dose, a route and a
  frequency claim, with no language model, and each is checked against FDA label text or an
  FDA OTC monograph. One drug per order; up to 50 orders of 500 characters per request.
- **Structured claims** (`verify_medications`) of nine claim types, one claim type per claim.
- **Interactions within a request** (`check_interactions: true` on either tool), checked
  against the labels' own Drug Interactions text.
- **Run read-backs:** `get_verification`, `get_accuracy` and `export_verification` (CSV, PDF
  or a report). Every run is stored in an audit record under your account, and audit records
  cannot be deleted.
- **Four results per claim:** FLAGGED (with a severity), SUPPORTED, NOT VERIFIED (abstain) and
  UNREADABLE. Each supported or flagged row cites the label section or monograph paragraph it
  was judged against. A supported row is not a safety clearance, and an abstain is unchecked,
  never passing. Orinyx flags; the clinician decides.
- **Free plan:** 200 checks per calendar month (UTC), one account per sign-up. One call to
  `verify_order_text` or `verify_medications` is one check; lookups and read-backs do not
  count.
- **A refused key says so:** when the API refuses the key or sign-in itself (401),
  `start_a_test` answers with a short message saying it was refused and what to check, instead
  of the menu of tests.

### Not in this release

- Exams are not self-serve: they are for product accounts that Orinyx registers.
- Label and monograph lookups are for staff accounts and are refused for a developer account.
- The dashboard is for staff accounts.

### Known limits

Known gaps in the knowledge base and the checks, among them nitrofurantoin (route only), no IV
acetaminophen daily ceiling, weight- and age-conditional maxima not compared, one label per
drug, and combination products. Most show up as a NOT VERIFIED row, a refused order or a daily
total that was not checked, so a missing flag is never evidence that an order is safe. See
[Known limits](docs/RELEASE_NOTES_2026-11-02.md#known-limits).

[Unreleased]: https://github.com/lexthirteen-ai/orinyx-mcp/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/lexthirteen-ai/orinyx-mcp/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/lexthirteen-ai/orinyx-mcp/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/lexthirteen-ai/orinyx-mcp/compare/v0.1.1...v0.1.2
[0.1.1]: docs/RELEASE_NOTES_2026-11-02.md

# Changelog

All notable changes to this project are recorded here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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

[Unreleased]: https://github.com/lexthirteen-ai/orinyx-mcp/compare/main...HEAD
[0.1.1]: docs/RELEASE_NOTES_2026-11-02.md

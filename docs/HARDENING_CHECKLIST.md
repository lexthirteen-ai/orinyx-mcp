# Hardening checklist — orinyx-mcp

base=da696ef5598bdc9b274cf0e327c285735bdbda7e | checklist-version=1 | sweep=2026-11-13

This file lists closed rows only: a check that passed at the sweep, or a finding that was fixed
with a test that fails if it comes back. Row numbers are stable across sweeps and are never
reused, so a gap in the numbering is a row that is not closed. A `pass` is re-run at every sweep
and is never carried forward. Where a row was fixed by a test alone, the code was already right
and nothing held it there.

Row grammar: `H-orinyx-mcp-NNN | dimension | file:line or command | status | test path or —`.
File and line references are as of the sweep date in the status.

## secrets — Exposed secrets

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-003 | secrets | orinyx_mcp/config.py:85-86 (a username or password in `MCP_PUBLIC_URL` is refused at start-up, so it is never published in the protected-resource document or the 401 challenge) | fixed 2026-11-13 | tests/test_public_url_userinfo.py |
| H-orinyx-mcp-048 | secrets | secret-shape scan of the tree with `grep -rnoE`, 15 common credential shapes and the four `ork_` prefixes, the match never printed (prefix and length only): no full-length match | pass 2026-11-13 | — |
| H-orinyx-mcp-049 | secrets | e-mail shape, count and last domain label only: every address is on `.example` or `.test` | pass 2026-11-13 | — |
| H-orinyx-mcp-050 | secrets | the repo's own identifier screen (`orinyx_mcp.screen.SCREEN_PATTERNS`) over the tracked files | pass 2026-11-13 | — |
| H-orinyx-mcp-051 | secrets | `git ls-files \| grep -nE '(^\|/)\.env\|\.pem$\|\.key$\|\.p12$\|\.pfx$\|id_rsa\|\.netrc\|credentials\|secrets?\.'` (one hit, the source module `orinyx_mcp/credentials.py`) | pass 2026-11-13 | — |
| H-orinyx-mcp-052 | secrets | `git log --format=%H da696ef5598bdc9b274cf0e327c285735bdbda7e..HEAD` (the tree under review is the base commit plus this sweep's own commits) | pass 2026-11-13 | — |

## §5 access control — Broken access control (IDOR)

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-001 | access | tests/conftest.py; orinyx_mcp/cli.py:456-463; orinyx_mcp/__main__.py:27-34 (a test that runs a command without `ORINYX_API_KEY` can no longer reach a sign-in saved on the machine: the OS keychain is blocked in the test process and in every child process it starts, and a connection that leaves the machine is refused) | fixed 2026-11-13 | tests/test_suite_isolation.py |
| H-orinyx-mcp-012 | access | orinyx_mcp/credentials.py (the imports, the one home-directory path and the file calls of the credential store, which the package-wide guard in tests/test_config_safety.py leaves out) | fixed 2026-11-13 | tests/test_credential_store_structure.py |
| H-orinyx-mcp-013 | access | orinyx_mcp/cli.py:449-466; orinyx_mcp/__main__.py:22-37; orinyx_mcp/http.py:240-245 (`ORINYX_API_KEY` wins over a saved sign-in, a saved sign-in is used only for its own API origin, and the network server never reads the sign-in store) | fixed 2026-11-13 | tests/test_credential_precedence.py |
| H-orinyx-mcp-014 | access | orinyx_mcp/login.py:38-63 (what the sign-in callback takes and what it answers 400) | fixed 2026-11-13 | tests/test_login_callback_rules.py |
| H-orinyx-mcp-015 | access | orinyx_mcp/login.py:185-224 (what the sign-in accepts from the token endpoint, at sign-in and at refresh) | fixed 2026-11-13 | tests/test_login_token_answers.py |
| H-orinyx-mcp-017 | access | orinyx_mcp/credentials.py:53-61,113-147 (the sign-in lock: its folder, its file, and the platforms with no lock or no native keychain) | fixed 2026-11-13 | tests/test_login_lock.py |
| H-orinyx-mcp-018 | access | orinyx_mcp/credentials.py:68-95 (what the sign-in accepts back from the keychain) | fixed 2026-11-13 | tests/test_stored_login_record.py |
| H-orinyx-mcp-053 | access | orinyx_mcp/login.py:49 (a wrong `state` never completes a sign-in, and the listener goes on waiting) | pass 2026-11-13 | tests/test_login.py::test_wrong_callback_state_does_not_complete_signin; tests/test_login_callback_rules.py |
| H-orinyx-mcp-054 | access | orinyx_mcp/http.py:396-399; orinyx_mcp/config.py:95-98 (the hosted server does not start without the hop secret: 32 characters, ASCII) | pass 2026-11-13 | tests/test_http.py::test_hosted_mcp_refuses_to_start_without_hop_authentication; tests/test_config.py::test_the_hop_secret_must_be_long_and_the_port_a_number; tests/test_config.py::test_hop_secret_must_be_ascii |

## injection — Injection & sanitization

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-016 | injection | orinyx_mcp/login.py:93,102-183 (how the sign-in reads the server's metadata and its registration answer: no redirect followed, at most 64 KB of JSON, every endpoint on the API's own origin, a public client) | fixed 2026-11-13 | tests/test_login_metadata_answers.py |
| H-orinyx-mcp-055 | injection | orinyx_mcp/client.py:127-142 (a malformed disclosure is `invalid_response`, not a crash) | pass 2026-11-13 | tests/test_client.py::test_malformed_context_is_refused_before_rendering; tests/test_cli.py::test_malformed_context_exits_1_in_every_mode; tests/test_tools.py::test_malformed_context_reaches_the_agent_as_a_sanitized_tool_error |

## boundary — Client-vs-server boundaries

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-056 | boundary | Dockerfile:20-21; .dockerignore:1-2 (the image runs as a non-root user; the build context is an allowlist) | pass 2026-11-13 | — |

## rot — AI code rot

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-020 | rot | orinyx_mcp/http.py:51-58; orinyx_mcp/credentials.py:15 (two scope lists with one name: the six the network server advertises and the four a CLI sign-in asks for, different by the two exam scopes on purpose) | fixed 2026-11-13 | tests/test_scope_lists.py |
| H-orinyx-mcp-057 | rot | `ruff check .` | pass 2026-11-13 | — |
| H-orinyx-mcp-058 | rot | `ruff format --check .` | pass 2026-11-13 | — |

## §6 deployment readiness — Environment & deployment rules

| Row | Dimension | File:line or command | Status | Test |
|---|---|---|---|---|
| H-orinyx-mcp-004 | deploy | orinyx_mcp/config.py:26-27,99-103 (a hop secret that no HTTP header can carry is refused at start-up, where it used to start and then refuse every caller) | fixed 2026-11-13 | tests/test_hop_secret_header_value.py |
| H-orinyx-mcp-019 | deploy | release/manifests/0.1.5.json (the manifest is compared with the tracked files on every push, not only when a release is built) | fixed 2026-11-13 | tests/test_manifest_matches_tracked_files.py |
| H-orinyx-mcp-065 | deploy | requirements.lock:29 (`opentelemetry-api` is pinned at 1.45.2, the release that fixes GHSA-mf5v-w3w3-f6cg / CVE-2026-126360, slow parsing of a crafted `traceparent`; every lock file that pins the package must pin 1.45.2 or later) | fixed 2026-11-13 | tests/test_dependency_floors.py |
| H-orinyx-mcp-059 | deploy | `pip-audit -r requirements.lock --no-deps --disable-pip` (41 pins on macOS) and the same over a copy without platform markers (all 43 pins): no known advisory | pass 2026-11-13 | — |
| H-orinyx-mcp-060 | deploy | `pip-audit -r requirements-release.lock --no-deps --require-hashes --disable-pip` (29 pins on macOS) and the same over a copy without platform markers (all 36 pins): no known advisory | pass 2026-11-13 | — |
| H-orinyx-mcp-061 | deploy | both lock files hold exact `==` pins only: requirements.lock 43, requirements-release.lock 36 | pass 2026-11-13 | — |
| H-orinyx-mcp-062 | deploy | `python -I scripts/check_dist.py --manifest release/manifests/0.1.5.json --print-shape` | pass 2026-11-13 | — |
| H-orinyx-mcp-063 | deploy | `python -I scripts/lint_release_workflow.py .github/workflows/release.yml` | pass 2026-11-13 | — |
| H-orinyx-mcp-064 | deploy | `python -I scripts/check_build_inputs.py .` | pass 2026-11-13 | — |

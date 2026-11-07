"""The install docs. A self-serve developer has only the hosted connector, so the README's
Installation section opens with it; every stdio, CLI and CI path says it needs a key issued by
Orinyx; no doc gives a PyPI install command, a CLI login, a singular developer-page link or a
real-looking key; every section that shows a config or command holding `ORINYX_API_KEY` warns
never to commit a config file that holds a key; the official-package line (pre-release form) is
in the README and SECURITY.md; and the troubleshooting page and the Supported environments
section are linked from Installation, the latter with no support-window or support-policy
statement. Each check reads the docs as committed, so a later edit that drops or reverses one of
these fails here."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# The five files this change touched, and every doc under docs/.
CHANGED = (
    "README.md",
    "docs/QUICKSTART.md",
    "docs/TROUBLESHOOTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
)
DEVELOPERS_URL = "https://orinyx.io/developers"
PACKAGE_LINE = (
    "The only official package is `orinyx-mcp`, published only from "
    "`github.com/lexthirteen-ai/orinyx-mcp`. Anything else named orinyx isn't Orinyx's."
)
README_ACCESS_LINE = (
    "Sign up at [orinyx.io/developers](https://orinyx.io/developers) to use the hosted connector "
    "with your Orinyx account; a key for the stdio server, the CLI or CI is issued by Orinyx."
)
HOSTED_URL = "https://orinyx-mcp.fly.dev/mcp"
CLAUDE_CODE_HOSTED = f"claude mcp add --transport http orinyx {HOSTED_URL}"
CURSOR_JSON = '{"mcpServers": {"orinyx": {"url": "https://orinyx-mcp.fly.dev/mcp"}}}'
WARNING = "never commit a client config file that holds a key"
WARNING_NAMES = ("claude_desktop_config.json", ".cursor/mcp.json")

# A PyPI install of any Orinyx name: pip/pip3/pipx/uv pip/uv tool install, uv add, or a
# uvx/pipx run/uv tool run, with any flags, quoted or pinned. A from-source install
# (`pip install -e .`, `pip install "git+https://...orinyx-mcp.git@<commit>"`) never matches,
# because the name does not follow the command and its flags.
PYPI_INSTALL = re.compile(
    r"\b(?:(?:pip3?|pipx|uv\s+pip|uv\s+tool)\s+install|uv\s+add|uvx|pipx\s+run|uv\s+tool\s+run)"
    r"(?:\s+-{1,2}[\w-]+(?:[= ][^\s'\"]+)?)*\s+[\"']?orinyx",
    re.I,
)
SINGULAR_DEVELOPER = re.compile(r"orinyx\.io/developer(?!s)", re.I)
# An 8-character key pattern: shorter than the 16 the tree-wide scan in
# test_config_safety.py uses.
KEY_SHAPED = re.compile(r"ork_(?:live|test|oat|ort)_[A-Za-z0-9]{8,}")
CLI_LOGIN = re.compile(r"\borinyx\s+login\b", re.I)
SUPPORT_POLICY = re.compile(
    r"support window|supported version|only the latest|latest 0\.|\bminor\b|end[ -]of[ -]life|"
    r"\beol\b|deprecat|\bpolicy\b|\blts\b|\buntil\b",
    re.I,
)
HEADING = re.compile(r"(#{1,6}) ")
INLINE_CODE = re.compile(r"`([^`]+)`")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _collapse(text: str) -> str:
    # Collapse the Markdown line wrapping and bold markers so a phrase matches across a break.
    return " ".join(text.replace("**", "").split())


def _doc_files() -> list[str]:
    docs = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").rglob("*.md"))
    return sorted({"README.md", "SECURITY.md", "CHANGELOG.md", *docs})


def _sections(text: str) -> list[tuple[str, str]]:
    """Each heading (any level) with the text up to the next heading of any level. A `#` line
    inside a code fence (a shell comment) is not a heading."""
    sections: list[tuple[str, str]] = []
    heading, lines, in_fence = "", [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and HEADING.match(line):
            sections.append((heading, "\n".join(lines)))
            heading, lines = line, []
        else:
            lines.append(line)
    sections.append((heading, "\n".join(lines)))
    return sections


def _section(text: str, heading: str) -> str:
    """The text under one heading up to the next heading of the same or a higher level."""
    level = len(HEADING.match(heading).group(1))
    out, inside, in_fence = [], False, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match and inside and len(match.group(1)) <= level:
            break
        if inside:
            out.append(line)
        if line == heading:
            inside = True
    assert inside, f"no heading {heading!r}"
    return "\n".join(out)


def _shows_the_key(body: str) -> bool:
    """True if a section shows a config or command holding ORINYX_API_KEY: the name inside a
    code fence, or inside an inline code span that is more than the bare name (for example
    `--header "Authorization: Bearer $ORINYX_API_KEY"`). A table or a sentence naming the
    variable (`ORINYX_API_KEY`) is not a config or a command."""
    in_fence, prose = False, []
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence and "ORINYX_API_KEY" in line:
            return True
        if not in_fence:
            prose.append(line)
    # Inline spans are read outside the fences, so a fence's backticks never pair with them.
    for span in INLINE_CODE.findall(" ".join(" ".join(prose).split())):
        if "ORINYX_API_KEY" in span and span.strip() != "ORINYX_API_KEY":
            return True
    return False


def _warns(body: str) -> bool:
    text = _collapse(body).lower()
    return WARNING in text and all(name in text for name in WARNING_NAMES)


def _unwarned_key_sections(text: str) -> tuple[set[str], list[str]]:
    shown: set[str] = set()
    missing: list[str] = []
    for heading, body in _sections(text):
        if _shows_the_key(body):
            shown.add(heading)
            if not _warns(body):
                missing.append(heading)
    return shown, missing


# --- detectors -----------------------------------------------------------------------------


def test_the_detectors_tell_a_violation_from_an_allowed_form():
    for bad in (
        "pip install orinyx-mcp",
        "pip install orinyx",
        "pip3 install -U orinyx-mcp",
        'pip install "orinyx-mcp==0.1.3"',
        "pip install --upgrade orinyx-mcp==0.1.3",
        "pipx install orinyx-mcp",
        "uv pip install orinyx-mcp",
        "uv tool install orinyx-mcp",
        "uv add orinyx-mcp",
        "uvx orinyx-mcp",
        "uvx orinyx",
        "uvx --from orinyx-mcp orinyx verify",
        "uvx orinyx-mcp@0.1.3",
    ):
        assert PYPI_INSTALL.search(bad), bad
    for good in (
        "pip install -e .",
        'pip install -e ".[dev]"',
        'pip install "git+https://github.com/lexthirteen-ai/orinyx-mcp.git@<commit>"',
        "Claude Desktop: `spawn <command> ENOENT` (for example `spawn uvx ENOENT`)",
        "The package is not published to PyPI; install it from a checkout.",
    ):
        assert not PYPI_INSTALL.search(good), good
    assert SINGULAR_DEVELOPER.search("https://orinyx.io/developer")
    assert SINGULAR_DEVELOPER.search("[x](https://orinyx.io/developer/)")
    assert not SINGULAR_DEVELOPER.search(DEVELOPERS_URL)
    assert KEY_SHAPED.search("ork_live_" + "Ab3dEf7h")  # 8 characters is enough
    assert not KEY_SHAPED.search("ork_live_" + "Ab3dEf7")  # 7 is not
    assert not KEY_SHAPED.search("<your ork_live_ key>")
    assert not KEY_SHAPED.search("a key (`ork_live_...`)")
    assert CLI_LOGIN.search("run `orinyx login`")
    assert SUPPORT_POLICY.search("During the beta, only the latest 0.x minor is supported.")


def test_the_warning_check_finds_a_key_section_without_the_warning():
    text = (
        "## Fenced\n\n```bash\nexport ORINYX_API_KEY=<key>\n```\n\n"
        '## Inline\n\nAdd `--header "Authorization: Bearer $ORINYX_API_KEY"`.\n\n'
        '## Warned\n\n```json\n{"ORINYX_API_KEY": "<key>"}\n```\n\n'
        "**Never commit a client config file that holds a key**, such as\n"
        "`claude_desktop_config.json` or `.cursor/mcp.json`.\n\n"
        "## Named only\n\nCredentials come from `ORINYX_API_KEY` only.\n\n"
        "## Fence comment\n\n```bash\n# not a heading\nexport ORINYX_API_KEY=<key>\n```\n"
    )
    shown, missing = _unwarned_key_sections(text)
    assert shown == {"## Fenced", "## Inline", "## Warned", "## Fence comment"}
    assert missing == ["## Fenced", "## Inline", "## Fence comment"]


# --- the docs ------------------------------------------------------------------------------


def test_the_installation_section_opens_with_the_hosted_self_serve_path():
    readme = _read("README.md")
    installation = _section(readme, "## Installation")
    subsections = [line for line in installation.splitlines() if line.startswith("### ")]
    assert subsections[0] == "### Hosted connector (the self-serve path)"
    rows = [line for line in installation.splitlines() if line.startswith("| [")]
    assert rows[0].startswith(
        "| [Hosted connector](#hosted-connector-the-self-serve-path) | the self-serve path |"
    )
    hosted = _section(readme, "### Hosted connector (the self-serve path)")
    assert HOSTED_URL in hosted and "OAuth" in hosted
    claude_code = _section(readme, "#### Claude Code")
    assert f"```bash\n{CLAUDE_CODE_HOSTED}\n```" in claude_code
    assert "run `/mcp` inside Claude Code and authenticate" in _collapse(claude_code)
    desktop = _collapse(_section(readme, "#### Claude Desktop"))
    assert f"Add `{HOSTED_URL}` as a custom connector and sign in" in desktop
    cursor = _section(readme, "#### Cursor")
    assert "`~/.cursor/mcp.json`" in cursor and f"```json\n{CURSOR_JSON}\n```" in cursor
    assert "sign in" in cursor


def test_the_old_access_line_is_replaced():
    first_part = _read("README.md").split("\n## ", 1)[0]
    assert "Access to the API is arranged with Orinyx." not in _collapse(_read("README.md"))
    assert README_ACCESS_LINE in _collapse(first_part)


@pytest.mark.parametrize(
    ("rel", "heading"),
    [
        ("README.md", "### Local stdio (from source)"),
        ("README.md", "#### Claude Code (stdio)"),
        ("README.md", "#### Claude Desktop (stdio)"),
        ("README.md", "## CLI in CI"),
        ("docs/QUICKSTART.md", "## Install"),
        ("docs/QUICKSTART.md", "### Claude Code"),
        ("docs/QUICKSTART.md", "### Claude Desktop"),
        ("docs/QUICKSTART.md", "### Check the connection"),
        ("docs/QUICKSTART.md", "## Check from the shell"),
        ("docs/QUICKSTART.md", "## CI recipe"),
        ("docs/QUICKSTART.md", "## Observe a test run"),
    ],
)
def test_every_stdio_cli_and_ci_path_says_its_key_is_issued_by_orinyx(rel, heading):
    body = _collapse(_section(_read(rel), heading))
    assert re.search(r"issued (?:to you )?by Orinyx", body), (rel, heading)


@pytest.mark.parametrize("rel", ["README.md", "docs/QUICKSTART.md"])
def test_every_section_showing_the_key_warns_never_to_commit_a_config(rel):
    shown, missing = _unwarned_key_sections(_read(rel))
    expected = {
        "README.md": {
            "#### Claude Code",
            "### Local stdio (from source)",
            "#### Claude Code (stdio)",
            "#### Claude Desktop (stdio)",
            "## CLI in CI",
        },
        "docs/QUICKSTART.md": {"### Claude Code", "### Claude Desktop", "## CI recipe"},
    }[rel]
    assert expected <= shown  # the check found the sections it must guard
    assert not missing


@pytest.mark.parametrize("rel", ["README.md", "SECURITY.md"])
def test_the_official_package_line_is_stated_once(rel):
    text = _collapse(_read(rel))
    assert text.count(PACKAGE_LINE) == 1
    where = _section(_read(rel), "## Installation" if rel == "README.md" else "## Official package")
    assert PACKAGE_LINE in _collapse(where)


@pytest.mark.parametrize("rel", CHANGED)
def test_no_changed_file_gives_a_pypi_install_command(rel):
    hits = [line for line in _read(rel).splitlines() if PYPI_INSTALL.search(line)]
    assert not hits


def test_the_from_source_install_stays():
    assert "pip install -e ." in _section(_read("README.md"), "### Local stdio (from source)")
    assert "pip install -e ." in _section(_read("docs/QUICKSTART.md"), "## Install")


@pytest.mark.parametrize("rel", _doc_files())
def test_every_developer_page_link_is_the_plural_form(rel):
    text = _read(rel)
    assert not SINGULAR_DEVELOPER.search(text)
    for target in re.findall(r"\]\(([^)\s]*orinyx\.io/developer[^)\s]*)\)", text):
        assert target == DEVELOPERS_URL, target


def test_the_readme_links_the_developer_page():
    assert f"[orinyx.io/developers]({DEVELOPERS_URL})" in _read("README.md")


@pytest.mark.parametrize("rel", CHANGED)
def test_no_changed_file_shows_a_key_shaped_value(rel):
    assert not KEY_SHAPED.search(_read(rel))


@pytest.mark.parametrize("rel", _doc_files())
def test_no_doc_names_a_cli_login(rel):
    assert not CLI_LOGIN.search(_read(rel))


def test_troubleshooting_exists_and_is_linked_from_installation():
    installation = _section(_read("README.md"), "## Installation")
    assert "blob/main/docs/TROUBLESHOOTING.md)" in installation
    lines = _read("docs/TROUBLESHOOTING.md").splitlines()
    assert "| Symptom | Cause | Fix |" in lines
    body = [line for line in lines if line.startswith("| ") and line != "| Symptom | Cause | Fix |"]
    # Every symptom row of the troubleshooting table, in order.
    for row, symptom in zip(
        body,
        (
            "`Set ORINYX_API_URL and ORINYX_API_KEY in the environment.`",
            "`Set MCP_PUBLIC_URL and ORINYX_API_URL`",
            "`ORINYX_API_URL must use https (plain http only for localhost).`",
            "401 `Invalid or revoked API key.`",
            "403 `... does not cover this surface`",
            "429 `quota_exceeded`",
            "The hosted sign-in loops or is refused",
            "ENOENT",
            "A run is refused before sending",
            "Exit code 3 in CI",
        ),
        strict=True,
    ):
        assert symptom in row.split(" | ")[0], (symptom, row)
    unauthorized = body[3]
    assert "mint" not in unauthorized.lower()
    assert "Ask whoever issued the key (Orinyx)" in unauthorized
    assert "A self-serve account has no key" in unauthorized
    assert "`python -m orinyx_mcp`" in body[1]


def test_troubleshooting_never_repairs_a_uvx_or_pipx_launch():
    # No official path launches through uvx or pipx, so a row that helps a reader fix one would
    # help them run a package that is not ours. The ENOENT fix names only the from-source
    # virtualenv's interpreter, never a PATH lookup for whatever command failed.
    text = _read("docs/TROUBLESHOOTING.md")
    assert not re.search(r"\b(?:uvx|pipx)\b", text, re.I)
    enoent = [line for line in text.splitlines() if line.startswith("| ") and "ENOENT" in line]
    assert len(enoent) == 1
    assert "which " not in enoent[0]
    assert '/.venv/bin/orinyx-mcp` with `"args": ["stdio"]`' in enoent[0].split(" | ")[2]


def test_supported_environments_is_linked_and_states_facts_only():
    readme = _read("README.md")
    assert "(#supported-environments)" in _section(readme, "## Installation")
    section = _section(readme, "### Supported environments")
    for row in (
        "| Python 3.11, 3.12 and 3.13 | tested in CI on Linux |",
        "| Python 3.14 | used in development; not tested in CI |",
        "| macOS | used in development; not tested in CI |",
        "| Windows | untested |",
        "| Transports | stdio (local) and Streamable HTTP (hosted) |",
    ):
        assert row in section, row
    assert "`https://orinyx-mcp.fly.dev/health`" in section
    assert not SUPPORT_POLICY.search(section), SUPPORT_POLICY.search(section)


def test_the_ci_python_versions_match_the_supported_environments_row():
    workflow = _read(".github/workflows/ci.yml")
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow

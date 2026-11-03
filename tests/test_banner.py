"""The banner above `orinyx -h` on an interactive terminal.

1. The asset `orinyx_mcp/assets/banner.json` is pinned: its canonical sha256, a constant here,
   and the art as a literal block. The render reproduces both golden hashes, and colour falls
   only on the shadow strokes.
2. The banner shows only on top-level help (`-h`, `--help`, `-h` glued to a value) and plain
   `orinyx`, and only when stdout is a terminal. It never reaches stderr, a pipe, a
   subcommand's output or help, `--json` output, or the MCP servers, and `CI`,
   `ORINYX_NO_BANNER` and `--no-banner` (before or after `-h`) turn it off.
3. Every byte and exit code pinned in `tests/fixtures/cli_output_before.json` is unchanged:
   after the banner, the help is exactly the pinned help.
4. Width, encoding, colour switches and a broken asset fall back quietly, never with an error.

A terminal here is a StringIO that says it is one. Help bytes are compared with colour off and
80 columns, as in tests/test_usage_errors.py, since Python 3.14's argparse colours its help on
a terminal.
"""

import argparse
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

import pytest
from orinyx_mcp import banner, cli

from tests.test_cli_output_unchanged import BEFORE, ENV, _environment, _factory, _workspace, cases
from tests.test_engine_contract import _canonical_sha256
from tests.test_usage_errors import COLOUR_SWITCHES, PLAIN_TERMINAL, _run_module

PACKAGE = Path(cli.__file__).resolve().parent
ASSET_FILE = PACKAGE / "assets" / "banner.json"
ASSET = json.loads(ASSET_FILE.read_text(encoding="utf-8"))
ASSET_SHA256 = "675bfeff1b688690bbc4f93e2eb1db33d9554ac986ad90f99c265f4f5aa4cf00"

# The art, exactly as approved: trailing spaces stripped, one leading space on the first line.
ART = """\
 ██████╗ ██████╗ ██╗███╗   ██╗██╗   ██╗██╗  ██╗
██╔═══██╗██╔══██╗██║████╗  ██║╚██╗ ██╔╝╚██╗██╔╝
██║   ██║██████╔╝██║██╔██╗ ██║ ╚████╔╝  ╚███╔╝
██║   ██║██╔══██╗██║██║╚██╗██║  ╚██╔╝   ██╔██╗
╚██████╔╝██║  ██║██║██║ ╚████║   ██║   ██╔╝ ██╗
 ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝
""".splitlines()
SUBTITLE = " " * 10 + "INDEPENDENT AI VERIFICATION"
COMPACT = "ORINYX - INDEPENDENT AI VERIFICATION"
SHADOW = "═║╔╗╚╝"
PLASMA = "\x1b[38;2;79;195;232m"
RESET = "\x1b[0m"
MONO = "\n".join([*ART, "", SUBTITLE]) + "\n"

HELP = BEFORE["--help"]["out"]
TOP_HELP = ("--help", "-h", "-h glued to a value")
BANNER_CASES = (*TOP_HELP, "no command")
BANNER_SWITCHES = ("CI", "ORINYX_NO_BANNER", "WT_SESSION")


class FakeTTY(io.StringIO):
    def __init__(self, encoding: str | None = "utf-8"):
        super().__init__()
        self._encoding = encoding

    @property
    def encoding(self):  # type: ignore[override]
        return self._encoding

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _plain_terminal(monkeypatch):
    """Colour off, 80 columns, and no banner switch, whatever the caller's environment."""
    for name in (*COLOUR_SWITCHES, *BANNER_SWITCHES):
        monkeypatch.delenv(name, raising=False)
    for name, value in PLAIN_TERMINAL.items():
        monkeypatch.setenv(name, value)


def run(argv: list[str], env: dict[str, str] | None = None, stdout=None) -> dict:
    """`orinyx <argv>` in process, with a terminal for stdout unless another stream is given."""
    out = FakeTTY() if stdout is None else stdout
    err = io.StringIO()
    with (
        _environment(ENV if env is None else env),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        try:
            code = cli.main(argv, client_factory=_factory)
        except SystemExit as exc:
            code = exc.code
    return {"exit": code, "out": out.getvalue(), "err": err.getvalue()}


def run_case(name: str, work: Path, stdout=None) -> dict:
    """One case of the pinned fixture, with `<work>` for its path, as the fixture holds it."""
    _workspace(work)
    argv, env = cases(work)[name]
    result = run(argv, env, stdout)
    return {
        key: value if key == "exit" else value.replace(str(work), "<work>")
        for key, value in result.items()
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _drawn_in(text: str) -> list[tuple[str, str | None]]:
    """Each printed character with the SGR colour it is drawn in (None: the terminal's own)."""
    drawn, colour = [], None
    for token in re.split(r"(\x1b\[[0-9;]*m)", text):
        if token.startswith("\x1b"):
            colour = None if token == RESET else token
        else:
            drawn.extend((char, colour) for char in token)
    return drawn


# --- the asset ------------------------------------------------------------------------------


def test_the_asset_is_pinned_by_its_canonical_hash_and_its_art():
    assert ASSET["sha256"] == _canonical_sha256(ASSET) == ASSET_SHA256
    assert ASSET["art"] == ART
    assert sorted(ASSET) == sorted(
        [
            "_note", "format", "text", "font", "generator", "art", "subtitle", "compact",
            "width", "colors", "accent_chars", "subtitle_color", "golden_sha256", "sha256",
        ]
    )  # fmt: skip
    assert ASSET["format"] == 1
    assert (ASSET["text"], ASSET["font"]) == ("ORINYX", "ansi_shadow")
    assert ASSET["generator"].endswith(" 1.0.4") and ASSET["generator"] in ASSET["_note"]
    assert ASSET["colors"] == {"base": None, "accent": "#4FC3E8"}
    assert (ASSET["accent_chars"], ASSET["subtitle_color"]) == (SHADOW, "base")
    assert ASSET["subtitle"] == SUBTITLE
    assert ASSET["compact"] == COMPACT and COMPACT.isascii() and len(COMPACT) == 36
    assert ASSET["width"] == max(len(line) for line in ASSET["art"]) == 47
    assert all(line == line.rstrip() for line in ART)
    assert set("".join(ART)) == {" ", "█", *SHADOW}


def test_the_package_reads_the_same_asset():
    assert banner._read_asset() == ASSET


def test_the_render_reproduces_both_golden_hashes(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    mono = banner.render(FakeTTY(), {"NO_COLOR": "1"}, 80)
    colour = banner.render(FakeTTY(), {}, 80)
    assert mono == MONO
    assert _sha(mono) == ASSET["golden_sha256"]["mono"]
    assert _sha(colour) == ASSET["golden_sha256"]["color"]
    assert re.sub(r"\x1b\[[0-9;]*m", "", colour) == MONO


def test_only_the_shadow_strokes_are_coloured(monkeypatch):
    """Plasma on `═ ║ ╔ ╗ ╚ ╝` only; the letters, the subtitle, every space and every newline
    in the terminal's own colour, so each line ends reset."""
    monkeypatch.setattr(sys, "platform", "linux")
    colour = banner.render(FakeTTY(), {}, 80)
    assert set(re.findall(r"\x1b\[[0-9;]*m", colour)) == {PLASMA, RESET}
    drawn = _drawn_in(colour)
    for char, drawn_colour in drawn:
        assert drawn_colour == (PLASMA if char in SHADOW else None), (char, drawn_colour)
    assert sum(1 for char, _ in drawn if char == "█") == MONO.count("█")


# --- where it shows ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", TOP_HELP)
def test_top_level_help_on_a_terminal_opens_with_the_banner(name, tmp_path):
    result = run_case(name, tmp_path)
    assert result == {**BEFORE[name], "out": MONO + BEFORE[name]["out"]}
    assert (result["exit"], result["err"]) == (0, "")


@pytest.mark.parametrize("name", BANNER_CASES)
def test_off_a_terminal_the_output_is_the_pinned_output(name, tmp_path):
    assert run_case(name, tmp_path, stdout=io.StringIO()) == BEFORE[name]


def test_plain_orinyx_on_a_terminal_prints_the_banner_and_the_help_and_returns_1():
    out, err = FakeTTY(), io.StringIO()
    with _environment(ENV), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([], client_factory=_factory)  # returns; no SystemExit
    assert (code, out.getvalue(), err.getvalue()) == (1, MONO + HELP, "")
    assert BEFORE["no command"]["exit"] == 1


def test_plain_orinyx_on_a_terminal_goes_through_the_interactive_home(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_interactive_home", lambda parser: seen.append(parser) or 42)
    assert run([])["exit"] == 42
    assert len(seen) == 1 and isinstance(seen[0], cli._TopParser)
    assert run([], stdout=io.StringIO()) == BEFORE["no command"]
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({"ORINYX_NO_BANNER": "1"}, []),
        ({"CI": "true"}, []),
        ({}, ["--no-banner"]),
        ({}, ["--no"]),
    ],
)
def test_a_switch_hides_only_the_banner_from_plain_orinyx(env, argv):
    assert run(argv, {**ENV, **env}) == {"exit": 1, "out": HELP, "err": ""}


@pytest.mark.parametrize(
    ("env", "argv"),
    [
        ({"ORINYX_NO_BANNER": "1"}, ["-h"]),
        ({"CI": "true"}, ["-h"]),
        ({"CI": "false"}, ["-h"]),  # any non-empty CI
        ({}, ["--no-banner", "-h"]),
        ({}, ["-h", "--no-banner"]),  # after -h, which argparse acts on first
        ({}, ["--no", "-h"]),
        ({}, ["--help", "--n"]),
    ],
)
def test_the_switches_turn_the_banner_off(env, argv):
    assert run(argv, {**ENV, **env}) == BEFORE["-h"]


@pytest.mark.parametrize("argv", [["verify", "--no-banner"], ["get", "x", "--no-banner"]])
def test_the_switch_after_a_subcommand_is_an_ordinary_usage_error(argv):
    result = run(argv)
    assert (result["exit"], result["out"]) == (1, "")
    assert " error: " in result["err"] and ART[0] not in result["err"]
    if argv[0] == "get":
        assert result["err"].endswith("orinyx: error: unrecognized arguments: --no-banner\n")


@pytest.mark.parametrize(
    ("words", "shown"),
    [
        ([], True),
        (["-h"], True),
        (["--help"], True),
        (["-hX"], True),
        (["--no-banner"], False),
        (["--no-b"], False),
        (["--n"], False),
        (["-h", "--no-banner"], False),
        (["--", "--no-banner"], True),  # past `--`, a value
        (["verify", "--no-banner"], True),  # past the command, not a top-level word
        (["-h", "verify", "--no"], True),
        (["-n"], True),
        (["--"], True),
    ],
)
def test_wanted_reads_only_the_top_level_words(words, shown):
    assert banner.wanted(words, FakeTTY(), {}) is shown


def test_wanted_needs_a_terminal_and_no_switch_in_the_environment():
    assert banner.wanted(["-h"], io.StringIO(), {}) is False
    assert banner.wanted(["-h"], None, {}) is False  # type: ignore[arg-type]
    assert banner.wanted(["-h"], FakeTTY(), {"CI": "1"}) is False
    assert banner.wanted(["-h"], FakeTTY(), {"ORINYX_NO_BANNER": "yes"}) is False
    assert banner.wanted(["-h"], FakeTTY(), {"CI": "", "ORINYX_NO_BANNER": ""}) is True


def test_the_switch_is_a_hidden_top_level_flag():
    parser = cli._parser()
    (action,) = [a for a in parser._actions if a.option_strings == ["--no-banner"]]
    assert isinstance(action, argparse._StoreTrueAction)
    assert action.help == argparse.SUPPRESS
    assert "--no-banner" not in parser.format_usage() + parser.format_help()


@pytest.mark.parametrize("argv", [["verify", "-h"], ["verify", "--help"]])
def test_subcommand_help_never_carries_the_banner(argv):
    assert run(argv) == BEFORE["verify --help"]


def test_help_written_to_another_file_never_carries_the_banner():
    parser = cli._parser()
    parser.banner = True
    out, elsewhere = FakeTTY(), io.StringIO()
    with contextlib.redirect_stdout(out):
        parser.print_help(elsewhere)
    assert (out.getvalue(), elsewhere.getvalue()) == ("", HELP)


def test_only_the_top_level_parser_carries_the_banner():
    parser = cli._parser()
    assert type(parser) is cli._TopParser
    (sub,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert sorted(sub.choices) == ["accuracy", "export", "get", "observe", "verify"]
    assert all(type(child) is cli._Parser for child in sub.choices.values())


@pytest.mark.parametrize("name", sorted(cases(Path("unused"))))
def test_no_other_output_changes_on_a_terminal(name, tmp_path):
    result = run_case(name, tmp_path)
    if name not in BANNER_CASES:
        assert result == BEFORE[name]
        assert ART[0] not in result["out"] and COMPACT not in result["out"]
    assert ART[0] not in result["err"] and COMPACT not in result["err"]
    assert "\x1b" not in result["err"]


def test_a_pipe_from_a_real_process_gets_no_banner():
    done = _run_module("orinyx_mcp.cli", ["-h"], {})
    assert (done.returncode, done.stderr) == (0, b"")
    assert done.stdout.decode("utf-8") == BEFORE["-h"]["out"]


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = "orinyx_mcp" + (f".{module}" if module else "")
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_only_the_cli_imports_the_banner_and_nothing_imports_the_cli():
    modules = {path.name: _imports(path) for path in sorted(PACKAGE.glob("*.py"))}
    assert {"__main__.py", "http.py", "server.py", "tools.py", "arena.py"} <= set(modules)

    def importers(target: str) -> set[str]:
        return {
            name
            for name, imported in modules.items()
            if any(n == target or n.startswith(target + ".") for n in imported)
        }

    assert importers("orinyx_mcp.banner") == {"cli.py"}
    assert importers("orinyx_mcp.cli") == set()


# --- fallbacks --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("columns", "shows"), [("47", "compact"), ("48", "art"), ("20", "compact"), ("100", "art")]
)
def test_the_art_needs_a_terminal_wider_than_it(columns, shows):
    env = {**ENV, "COLUMNS": columns}
    tty, pipe = run(["-h"], env), run(["-h"], env, stdout=io.StringIO())
    assert (tty["exit"], tty["err"]) == (pipe["exit"], pipe["err"]) == (0, "")
    head = COMPACT + "\n" if shows == "compact" else MONO
    assert tty["out"] == head + pipe["out"]


def test_the_compact_line_never_carries_colour(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    for columns in (47, 36, 1):
        assert banner.render(FakeTTY(), {}, columns) == COMPACT + "\n"


def test_the_width_comes_from_the_terminal_size(monkeypatch):
    asked = []

    def size(fallback):
        asked.append(fallback)
        return os.terminal_size((47, 24))

    monkeypatch.setattr(banner.shutil, "get_terminal_size", size)
    out = FakeTTY()
    banner.show(out, {"NO_COLOR": "1"})
    assert (out.getvalue(), asked) == (COMPACT + "\n", [(80, 24)])


@pytest.mark.parametrize("encoding", ["ascii", None, "no-such-codec"])
def test_a_terminal_that_cannot_encode_the_art_gets_the_compact_line(encoding):
    assert banner.render(FakeTTY(encoding), {}, 80) == COMPACT + "\n"
    result = run(["-h"], stdout=FakeTTY(encoding))
    assert result == {**BEFORE["-h"], "out": COMPACT + "\n" + BEFORE["-h"]["out"]}


@pytest.mark.parametrize(
    ("platform", "env", "coloured"),
    [
        ("linux", {"NO_COLOR": "1"}, False),
        ("linux", {"TERM": "dumb"}, False),
        ("win32", {}, False),
        ("win32", {"WT_SESSION": "0f1e2d3c"}, True),
        ("linux", {"NO_COLOR": ""}, True),
        ("linux", {"TERM": "xterm-256color"}, True),
        ("darwin", {}, True),
    ],
)
def test_the_colour_gates(platform, env, coloured, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    out = banner.render(FakeTTY(), env, 80)
    golden = ASSET["golden_sha256"]["color" if coloured else "mono"]
    assert _sha(out) == golden
    assert ("\x1b" in out) is coloured
    if not coloured:
        assert out == MONO


def test_the_cli_draws_the_colour_banner_above_plain_help(monkeypatch):
    """Colour allowed for the banner; PYTHON_COLORS=0 keeps argparse's own help plain."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("PYTHON_COLORS", "0")
    monkeypatch.delenv("NO_COLOR")
    out, err = FakeTTY(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as exited:
            cli.main(["-h"], client_factory=_factory)
    text = out.getvalue()
    assert (exited.value.code, err.getvalue()) == (0, "")
    assert _sha(text[: -len(BEFORE["-h"]["out"])]) == ASSET["golden_sha256"]["color"]
    assert text.endswith(BEFORE["-h"]["out"])


def _broken_asset(how: str, monkeypatch, tmp_path: Path) -> None:
    if how == "the loader raises":

        def fail():
            raise OSError("unreadable")

        monkeypatch.setattr(banner, "_read_asset", fail)
    elif how == "a wrong sha256":
        monkeypatch.setattr(banner, "_read_asset", lambda: {**ASSET, "sha256": "0" * 64})
    elif how == "art changed, sha256 not":
        monkeypatch.setattr(banner, "_read_asset", lambda: {**ASSET, "art": ["X" * 47] * 6})
    elif how == "no sha256":
        body = {key: value for key, value in ASSET.items() if key != "sha256"}
        monkeypatch.setattr(banner, "_read_asset", lambda: body)
    elif how == "a missing asset":
        monkeypatch.setattr(banner, "_asset_file", lambda: tmp_path / "missing.json")
    elif how == "invalid JSON":
        bad = tmp_path / "banner.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(banner, "_asset_file", lambda: bad)


@pytest.mark.parametrize(
    "how",
    [
        "the loader raises",
        "a wrong sha256",
        "art changed, sha256 not",
        "no sha256",
        "a missing asset",
        "invalid JSON",
    ],
)
def test_a_broken_asset_means_no_banner_and_no_error(how, monkeypatch, tmp_path):
    _broken_asset(how, monkeypatch, tmp_path)
    assert banner.render(FakeTTY(), {}, 80) == ""
    assert run(["-h"]) == BEFORE["-h"]
    assert run([]) == {"exit": 1, "out": HELP, "err": ""}

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
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest
from orinyx_mcp import banner, cli

from tests.test_cli_output_unchanged import BEFORE, ENV, _environment, _factory, _workspace, cases
from tests.test_engine_contract import _canonical_sha256
from tests.test_usage_errors import COLOUR_SWITCHES, PLAIN_TERMINAL, ROOT, _run_module

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


# C0 controls, DEL and C1 controls. A terminal can act on any of them, ESC (0x1B) and the C1
# CSI (0x9B) above all. The banner writes the asset's text as it stands, and its own hash only
# proves the file is whole, so the asset itself must hold none.
CONTROL_CHARACTERS = frozenset(map(chr, [*range(0x20), 0x7F, *range(0x80, 0xA0)]))


def _asset_strings(value, path="asset"):
    """Every string in the asset, keys included, each with where it sits."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _asset_strings(key, f"{path} key {key!r}")
            yield from _asset_strings(item, f"{path}[{key!r}]")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _asset_strings(item, f"{path}[{index}]")


def _control_characters_in(asset) -> list[str]:
    return [
        f"{where}: U+{ord(char):04X}"
        for where, text in _asset_strings(asset)
        for char in text
        if char in CONTROL_CHARACTERS
    ]


def test_the_asset_holds_no_control_character():
    assert _control_characters_in(ASSET) == []
    raw = ASSET_FILE.read_text(encoding="utf-8")
    # Outside its strings the file is plain JSON layout: newlines and spaces only.
    assert {char for char in raw if char in CONTROL_CHARACTERS} <= {chr(0x0A)}


@pytest.mark.parametrize(
    ("field", "planted"),
    [
        ("art", chr(0x1B) + "]0;title" + chr(0x07)),
        ("subtitle", chr(0x1B) + "[2J"),
        ("compact", chr(0x9B) + "2J"),
        ("_note", chr(0x00)),
        ("text", chr(0x7F)),
    ],
)
def test_the_control_character_check_finds_a_planted_one(field, planted):
    asset = json.loads(json.dumps(ASSET))
    if field == "art":
        asset["art"][0] += planted
    else:
        asset[field] += planted
    assert _control_characters_in(asset), field


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
    "argv",
    [
        ["--help", "--json"],
        ["--json", "--help"],
        ["-h", "verify"],
        ["-h", "verify", "--json"],
    ],
)
def test_top_level_help_with_other_arguments_prints_only_help(argv):
    assert run(argv) == BEFORE["-h"]


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


@pytest.mark.parametrize(
    "argv",
    [
        ["login", "-h"],
        ["logout", "-h"],
        ["status", "-h"],
        ["login", "--help"],
        ["status", "--json"],
        ["status"],
    ],
)
def test_the_sign_in_commands_never_carry_the_banner(argv):
    """`login`, `logout` and `status` came after the banner. On a terminal their bytes and exit
    codes equal the same run into a file, and none carries a banner mark. `status` runs with the
    environment key, so it reads no saved login."""
    on_a_terminal = run(argv)
    assert on_a_terminal == run(argv, stdout=io.StringIO())
    assert _banner_marks(on_a_terminal["out"] + on_a_terminal["err"]) == []


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
    assert sorted(sub.choices) == [
        "accuracy",
        "export",
        "get",
        "login",
        "logout",
        "observe",
        "status",
        "verify",
    ]
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


def _module_files() -> dict[str, Path]:
    """Every module of the package, subpackages included, by its path under orinyx_mcp/."""
    return {
        path.relative_to(PACKAGE).as_posix(): path
        for path in sorted(PACKAGE.rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    package = ["orinyx_mcp", *path.relative_to(PACKAGE).parent.parts]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                base = ".".join(package[: len(package) - (node.level - 1)])
                module = base + (f".{module}" if module else "")
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_only_the_cli_imports_the_banner_and_nothing_imports_the_cli():
    modules = {name: _imports(path) for name, path in _module_files().items()}
    expected = {"__main__.py", "http.py", "server.py", "gateway.py", "arena.py", "login.py"}
    assert "tools/verify.py" in modules
    assert expected <= set(modules)

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


def _rehashed(**fields) -> dict:
    """The asset with some fields changed and its sha256 recomputed, so it passes the check."""
    body = {key: value for key, value in {**ASSET, **fields}.items() if key != "sha256"}
    return {**body, "sha256": _canonical_sha256(body)}


@pytest.mark.parametrize(
    ("fields", "mono_breaks"),
    [
        ({"art": None}, True),
        ({"width": "47"}, True),
        ({"colors": {"base": None, "accent": 12}}, False),
    ],
    ids=["art not a list", "width not a number", "accent not a colour"],
)
def test_an_asset_that_passes_its_hash_but_cannot_be_drawn_means_no_banner(
    fields, mono_breaks, monkeypatch
):
    """Any failure, not only the ones the loader raises: a self-consistent asset that cannot be
    drawn gives "" from render, and `orinyx -h` stays the pinned help with no traceback."""
    monkeypatch.setattr(sys, "platform", "linux")
    broken = _rehashed(**fields)
    monkeypatch.setattr(banner, "_read_asset", lambda: broken)
    assert banner.render(FakeTTY(), {}, 80) == ""
    if mono_breaks:
        assert banner.render(FakeTTY(), {"NO_COLOR": "1"}, 80) == ""
        assert run(["-h"]) == BEFORE["-h"]


# --- with colour allowed ----------------------------------------------------------------------


def test_with_colour_allowed_only_top_level_help_on_a_terminal_changes(monkeypatch, tmp_path):
    """The replays above run with NO_COLOR=1, but a pipe from a CI job or a subprocess usually
    has no NO_COLOR. With colour allowed, every fixture case off a terminal is still the pinned
    output, and on a terminal (stdout and stderr both) only the four banner cases gain the
    colour banner. PYTHON_COLORS=0 keeps argparse's own help plain."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("PYTHON_COLORS", "0")
    monkeypatch.delenv("NO_COLOR")
    colour = banner.render(FakeTTY(), {}, 80)
    assert _sha(colour) == ASSET["golden_sha256"]["color"]
    wrong = []
    for at, name in enumerate(sorted(cases(Path("unused")))):
        for terminal in (False, True):
            work = tmp_path / f"{at}-{terminal}"
            work.mkdir()
            _workspace(work)
            argv, env = cases(work)[name]
            out, err = (FakeTTY(), FakeTTY()) if terminal else (io.StringIO(), io.StringIO())
            with mock.patch.dict(os.environ, {"COLUMNS": "80", "LINES": "24"}):
                for variable in ("ORINYX_API_URL", "ORINYX_API_KEY"):
                    os.environ.pop(variable, None)
                os.environ.update(env)
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        code = cli.main(argv, client_factory=_factory)
                    except SystemExit as exc:
                        code = exc.code
            got = {
                "exit": code,
                "out": out.getvalue().replace(str(work), "<work>"),
                "err": err.getvalue().replace(str(work), "<work>"),
            }
            expected = BEFORE[name]
            if terminal and name in TOP_HELP:
                expected = {**expected, "out": colour + expected["out"]}
            elif terminal and name == "no command":
                expected = {"exit": 1, "out": colour + HELP, "err": ""}
            if got != expected:
                wrong.append((name, "terminal" if terminal else "pipe"))
    assert wrong == []


# --- the MCP servers, and the rest of the package -----------------------------------------------


def _banner_marks(text: str) -> list[str]:
    return [mark for mark in (ART[0], SUBTITLE.strip(), COMPACT, PLASMA) if mark in text]


def test_the_stdio_server_on_a_terminal_writes_nothing_to_stdout(monkeypatch):
    """stdout is the MCP protocol stream. With stdout and stderr both terminals, colour allowed
    and no switch set (every condition under which the CLI shows its banner), the stdio server
    writes no byte to stdout: refusing to start, as `serve`, and up to `server.run()`."""
    pytest.importorskip("mcp")
    from orinyx_mcp import __main__ as stdio
    from orinyx_mcp import server

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.delenv("NO_COLOR")
    for name in list(os.environ):
        if name.startswith(("ORINYX_", "MCP_", "DOWNSTREAM_MCP_")):
            monkeypatch.delenv(name)
    ran = []

    class Started:
        def run(self):
            ran.append(True)

    monkeypatch.setattr(server, "build_server", lambda *args, **kwargs: Started())

    def stdio_main(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        out, err = FakeTTY(), FakeTTY()
        with mock.patch.dict(os.environ, env):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = stdio.main(argv)
        return code, out.getvalue(), err.getvalue()

    for argv, env, code in (
        ([], {}, 1),
        (["serve"], {}, 1),
        (["--no-such-word"], {}, 1),
        ([], ENV, 0),
    ):
        got, out, err = stdio_main(argv, env)
        assert (got, out) == (code, ""), (argv, got, out)
        assert _banner_marks(err) == [], (argv, err)
    assert ran == [True]


def test_loading_the_rest_of_the_package_never_loads_the_banner_or_the_cli():
    """The AST scan above cannot see a module imported by name at run time. A fresh interpreter
    that imports every other module, then runs the stdio entry point and `serve` without a
    configuration, has loaded neither `orinyx_mcp.banner` nor `orinyx_mcp.cli`."""
    others = sorted(
        name.removesuffix(".py").removesuffix("/__init__").replace("/", ".")
        for name in _module_files()
        if name not in {"banner.py", "cli.py"}
    )
    assert {"__main__", "http", "server", "gateway", "arena", "login", "tools.verify"} <= set(
        others
    )
    script = "\n".join(
        [
            "import importlib, sys",
            f"for name in {others!r}:",
            "    module = 'orinyx_mcp' if name == '__init__' else 'orinyx_mcp.' + name",
            "    importlib.import_module(module)",
            "from orinyx_mcp import __main__ as stdio",
            "codes = (stdio.main([]), stdio.main(['serve']))",
            "watched = ('orinyx_mcp.banner', 'orinyx_mcp.cli')",
            "loaded = sorted(name for name in watched if name in sys.modules)",
            "print(codes, loaded)",
        ]
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ORINYX_", "DOWNSTREAM_MCP_", "MCP_", "PYTHON"))
    }
    done = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        # tests/no_keychain first, as conftest.py gives every child: no keychain is opened.
        env={
            **environment,
            "PYTHONPATH": os.pathsep.join([str(ROOT / "tests" / "no_keychain"), str(ROOT)]),
        },
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    assert (done.returncode, done.stdout) == (0, b"(1, 1) []\n"), done.stderr


# --- no dependency, and the docs ----------------------------------------------------------------

# C15 allows the generator's name only in banner.json, so this file spells it in parts.
GENERATOR = "py" + "figlet"


def test_the_banner_module_is_standard_library_only_and_holds_no_banner_data():
    path = PACKAGE / "banner.py"
    source = path.read_text(encoding="utf-8")
    roots = {name.split(".")[0] for name in _imports(path)}
    assert roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names)
    assert roots.isdisjoint({"ctypes", "colorama", GENERATOR})
    assert re.findall(r"#[0-9A-Fa-f]{6}\b|\b\d+;\d+;\d+m", source) == []
    for text in (*ART, SUBTITLE.strip(), COMPACT, "INDEPENDENT", "█", *SHADOW):
        assert text not in source, text


def test_no_new_dependency_and_the_wheel_lists_the_asset():
    project_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8").lower()
    for name in (GENERATOR, "colorama"):
        assert name not in project_text.lower() and name not in lock, name
    project = tomllib.loads(project_text)
    wheel = project["tool"]["hatch"]["build"]["targets"]["wheel"]
    # Hatchling ships every file under the listed package, so the asset needs no artifact entry.
    assert wheel["packages"] == ["orinyx_mcp"]


def test_the_generator_is_named_only_in_the_asset_note_and_generator_fields():
    word = GENERATOR.encode()
    hits = []
    for top, dirs, files in os.walk(ROOT):
        dirs[:] = [
            name
            for name in dirs
            if (not name.startswith(".") or name == ".github")
            and name not in {"__pycache__", "node_modules", "dist", "build"}
            and not name.endswith(".egg-info")
        ]
        for name in files:
            path = Path(top, name)
            if word in path.read_bytes().lower():
                hits.append(path.relative_to(ROOT).as_posix())
    assert hits == ["orinyx_mcp/assets/banner.json"]
    fields = sorted(
        key
        for key, value in ASSET.items()
        if GENERATOR in json.dumps(value, ensure_ascii=False).lower()
    )
    assert fields == ["_note", "generator"]


def test_the_readme_documents_both_switches_in_cli_in_ci_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    before, _, rest = readme.partition("\n## CLI in CI\n")
    section, _, after = rest.partition("\n## ")
    assert section, "README has no 'CLI in CI' section"
    assert "ORINYX_NO_BANNER" in section and "--no-banner" in section
    assert "ORINYX_NO_BANNER" not in before + after and "--no-banner" not in before + after

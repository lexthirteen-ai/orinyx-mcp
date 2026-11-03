"""The banner above `orinyx -h` on an interactive terminal. Imported by `orinyx_mcp/cli.py`
only: the stdio and network servers never import it, so no banner byte can reach the MCP
protocol stream.

Everything shown comes from `orinyx_mcp/assets/banner.json`, which carries the art, the
subtitle, the compact line, the colours and its own hashes; the render rule is written in its
`_note`. The banner is decoration, so a missing or damaged asset means no banner, never an
error: nothing on stderr and no change to the help text or the exit code.
"""

import hashlib
import json
import shutil
import sys
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import TextIO

RESET = "\x1b[0m"
SWITCH = "--no-banner"


def turns_off(word: str) -> bool:
    """A top-level word that turns the banner off: `--no-banner` or any abbreviation of it
    that argparse accepts at the top level (`--n`, `--no`, ...)."""
    return len(word) > 2 and SWITCH.startswith(word)


def is_terminal(stream: TextIO | None) -> bool:
    """Whether the stream is an interactive terminal; False for anything that cannot say."""
    try:
        return bool(stream.isatty())  # type: ignore[union-attr]
    except (AttributeError, OSError, ValueError):
        return False


def wanted(words: Sequence[str], stream: TextIO, environ: Mapping[str, str]) -> bool:
    """Whether to show the banner, decided from the raw command-line words before argparse
    reads them: argparse prints the help the moment it reaches `-h`, before a later
    `--no-banner` has been read. Only the top-level words count, the ones before the first
    word that does not start with `-` and before `--`."""
    if not is_terminal(stream):
        return False
    if environ.get("ORINYX_NO_BANNER") or environ.get("CI"):
        return False
    for word in words:
        if word == "--" or not word.startswith("-"):
            break
        if turns_off(word):
            return False
    return True


def _asset_file():
    return resources.files("orinyx_mcp").joinpath("assets", "banner.json")


def _read_asset() -> dict:
    return json.loads(_asset_file().read_text(encoding="utf-8"))


def _checked_asset() -> dict:
    """The asset, if it carries its own canonical sha256 (every other field, key-sorted)."""
    asset = _read_asset()
    body = {key: value for key, value in asset.items() if key != "sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != asset["sha256"]:
        raise ValueError("the banner asset does not match its sha256")
    return asset


def _encodable(text: str, stream: TextIO) -> bool:
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return False
    try:
        text.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _coloured(environ: Mapping[str, str]) -> bool:
    """no-color.org: any non-empty NO_COLOR turns colour off. A Windows console other than
    Windows Terminal (which sets WT_SESSION) gets no colour, rather than enabling VT codes."""
    if environ.get("NO_COLOR") or environ.get("TERM") == "dumb":
        return False
    return sys.platform != "win32" or "WT_SESSION" in environ


def _sgr(colour: str) -> str:
    red, green, blue = (int(colour[at : at + 2], 16) for at in (1, 3, 5))
    return f"\x1b[38;2;{red};{green};{blue}m"


def _paint(line: str, classes: Mapping[str, str | None]) -> str:
    """One line, with an SGR code wherever the colour class changes. A space, and a class
    whose colour is null, is the terminal's own text colour."""
    painted, current = [], None
    for char in line:
        colour = None if char == " " else classes[char]
        if colour != current:
            painted.append(RESET if colour is None else _sgr(colour))
            current = colour
        painted.append(char)
    if current is not None:
        painted.append(RESET)
    return "".join(painted)


def _colour_lines(asset: dict) -> list[str]:
    colours = asset["colors"]
    accent_chars = asset["accent_chars"]
    art_classes = {
        char: colours["accent"] if char in accent_chars else colours["base"]
        for char in set("".join(asset["art"]))
    }
    subtitle_colour = colours[asset["subtitle_color"]]
    subtitle_classes = {char: subtitle_colour for char in set(asset["subtitle"])}
    return [_paint(line, art_classes) for line in asset["art"]] + [
        "",
        _paint(asset["subtitle"], subtitle_classes),
    ]


def render(stream: TextIO, environ: Mapping[str, str], columns: int) -> str:
    """The banner text for this stream: the art (in colour when allowed), or the compact line
    when the terminal is not wider than the art or cannot encode it. "" on any failure."""
    try:
        asset = _checked_asset()
        art = "\n".join([*asset["art"], "", asset["subtitle"]])
        if columns <= asset["width"] or not _encodable(art, stream):
            return asset["compact"] + "\n"
        if not _coloured(environ):
            return art + "\n"
        return "\n".join(_colour_lines(asset)) + "\n"
    except Exception:
        return ""


def show(stream: TextIO, environ: Mapping[str, str]) -> None:
    """Write the banner once, at the width of the terminal (COLUMNS when set)."""
    text = render(stream, environ, shutil.get_terminal_size((80, 24)).columns)
    if text:
        try:
            stream.write(text)
        except (OSError, ValueError):
            pass


__all__ = ["is_terminal", "render", "show", "turns_off", "wanted"]

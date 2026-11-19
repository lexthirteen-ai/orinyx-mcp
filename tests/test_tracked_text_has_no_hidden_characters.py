"""No tracked text file holds a character a reader cannot see.

A bidirectional control can make a line read differently from the bytes it holds, and a
zero-width character hides inside a word; neither shows in a review of the diff. A text that
means to name one writes its escape out in plain characters (a backslash, `u`, and the four
hex digits), never the character itself. This test reads every file git tracks (a new file
counts from the moment it is staged), skips any file that is not UTF-8 text (an image, for
example), and names each hidden character it finds by file, line and column.

Outside a git checkout (an unpacked source distribution, for example) there is no list of
tracked files, and the check is skipped.
"""

import subprocess
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Built from code points so that this file holds none of the characters it looks for.
BIDIRECTIONAL_CONTROLS = (
    *range(0x202A, 0x202E + 1),  # embeddings, overrides and the pop that ends them
    *range(0x2066, 0x2069 + 1),  # isolates and the pop that ends them
    0x200E,  # left-to-right mark
    0x200F,  # right-to-left mark
    0x061C,  # Arabic letter mark
)
ZERO_WIDTH = (
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space, also the byte order mark
)
HIDDEN = frozenset(chr(code) for code in BIDIRECTIONAL_CONTROLS + ZERO_WIDTH)


def hidden_characters(text: str) -> list[str]:
    """Each hidden character in `text`, as `line:column U+XXXX NAME`, in order."""
    found = []
    # Split on line feeds only: str.splitlines also breaks at characters this check reports.
    for line_number, line in enumerate(text.split("\n"), start=1):
        for column, character in enumerate(line, start=1):
            if character in HIDDEN:
                name = unicodedata.name(character, "")
                found.append(f"{line_number}:{column} U+{ord(character):04X} {name}".rstrip())
    return found


def read_text(path: Path) -> str | None:
    """The file's text, or None when it is not UTF-8 text or cannot be read as a file."""
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def tracked_files() -> list[str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout.decode()
    except (OSError, subprocess.SubprocessError):
        listed = ""
    names = sorted(name for name in listed.split("\0") if name)
    if not names:
        pytest.skip("not a git checkout: there is no list of tracked files to read")
    return names


def test_no_tracked_text_file_holds_a_bidirectional_control_or_a_zero_width_character():
    found = []
    for name in tracked_files():
        text = read_text(ROOT / name)
        if text is None:
            continue
        found.extend(f"{name}:{place}" for place in hidden_characters(text))
    assert found == []


# --- the check itself, on made-up text -------------------------------------------------------


@pytest.mark.parametrize("code", BIDIRECTIONAL_CONTROLS + ZERO_WIDTH, ids=lambda c: f"U+{c:04X}")
def test_each_hidden_character_is_named_with_its_line_and_column(code):
    text = "first line\nsecond " + chr(code) + "line\n"
    (place,) = hidden_characters(text)
    assert place.startswith(f"2:8 U+{code:04X}")


def test_plain_text_and_written_out_escapes_have_nothing_to_report():
    escape = chr(92) + "u202e"
    text = f"shown as an escape such as `{escape}`.\nemoji and accents are text: caf{chr(0xE9)}\n"
    assert hidden_characters(text) == []


def test_every_hidden_character_on_a_line_is_named():
    text = "a" + chr(0x202E) + "b" + chr(0x200B) + "c"
    assert hidden_characters(text) == [
        "1:2 U+202E RIGHT-TO-LEFT OVERRIDE",
        "1:4 U+200B ZERO WIDTH SPACE",
    ]


def test_a_file_that_is_not_utf8_text_is_skipped(tmp_path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert read_text(image) is None
    text = tmp_path / "notes.md"
    text.write_bytes(("x" + chr(0xFEFF)).encode("utf-8"))
    assert read_text(text) == "x" + chr(0xFEFF)

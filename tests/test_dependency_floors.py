"""The lowest version a lock file may pin for a package with a known advisory.

`opentelemetry-api` up to 1.45.1 parses a crafted `traceparent` header in quadratic time
(GHSA-mf5v-w3w3-f6cg, CVE-2026-126360). 1.45.2 fixes it. The MCP server extracts trace
context from every inbound message, so every lock file that pins the package must pin
1.45.2 or later. The test reads lock text only: it installs, imports and fetches nothing.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# package name -> (lowest allowed version, the lock files that must pin it)
FLOORS = {
    "opentelemetry-api": ("1.45.2", {"requirements.lock"}),
}
PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;\\]+)")


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def version_of(text: str) -> tuple[int, ...]:
    assert re.fullmatch(r"[0-9]+(\.[0-9]+)*", text), f"not a dotted-integer version: {text!r}"
    return tuple(int(part) for part in text.split("."))


def at_or_above(version: str, floor: str) -> bool:
    return version_of(version) >= version_of(floor)


def pins_in(path: Path) -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = PIN.match(line)
        if match:
            pins.setdefault(normalized(match.group(1)), []).append(match.group(2))
    return pins


def lock_files() -> list[Path]:
    return sorted(ROOT.glob("requirements*.lock"))


def test_there_are_lock_files_to_read():
    assert lock_files(), "no requirements*.lock at the repository root"


@pytest.mark.parametrize("package", sorted(FLOORS))
def test_exactly_the_expected_lock_files_pin_the_package(package):
    _, expected = FLOORS[package]
    found = {path.name for path in lock_files() if normalized(package) in pins_in(path)}
    assert found == expected, (package, sorted(found), sorted(expected))


@pytest.mark.parametrize("package", sorted(FLOORS))
def test_every_pin_is_at_or_above_the_floor(package):
    floor, expected = FLOORS[package]
    for name in sorted(expected):
        versions = pins_in(ROOT / name).get(normalized(package), [])
        assert versions, f"{name} does not pin {package}"
        for version in versions:
            assert at_or_above(version, floor), f"{name} pins {package}=={version}, below {floor}"


@pytest.mark.parametrize(
    "version, allowed",
    [("1.45.1", False), ("1.44.9", False), ("1.45.2", True), ("1.45.10", True), ("2.0.0", True)],
)
def test_the_floor_comparison_can_fail(version, allowed):
    assert at_or_above(version, "1.45.2") is allowed


def test_a_version_that_is_not_dotted_integers_fails():
    with pytest.raises(AssertionError):
        version_of("1.45.2rc1")

"""Check a directory of built distributions before anything is published.

    python -I scripts/check_dist.py DIST_DIR --manifest release/manifests/<version>.json \\
        [--source SOURCE_DIR] [--require-marker] [--wheel-only]

    python -I scripts/check_dist.py --manifest release/manifests/<version>.json --print-shape

Exit 0 when every check holds, 1 otherwise. Every failure is printed on its own `FAIL:` line.

The manifest says which shape the release has, and DIST_DIR must match it. A release with an
`sdist` list holds exactly one sdist (`.tar.gz`) and one wheel (`.whl`), plus at most a
`SHA256SUMS` file. A release with `"wheel_only": true` holds one wheel, no sdist, and at most
`SHA256SUMS`: the way to publish a release without its sdist.

The manifest is a JSON file, committed once per release, that lists the exact member paths
the release is allowed to hold (no globs):

    {
      "version": "0.1.3",
      "sdist": ["PKG-INFO", "README.md", ...],     # relative to the sdist's top directory
      "wheel_only": true,                          # in place of "sdist", never with it
      "wheel": ["orinyx_mcp/__init__.py", ...],
      "deny_exemptions": [{"path": "fly.toml", "reason": "..."}]    # optional
    }

The sdist's top directory must be `orinyx_mcp-<version>/`. A manifest has exactly one of an
`sdist` list and `wheel_only: true`: neither is refused, both are refused, and a missing `sdist`
list is never taken to mean wheel-only. `--wheel-only` is optional; when given it asserts that
the manifest says `wheel_only: true`. `--print-shape` reads only the manifest and prints
`wheel_only=true` or `wheel_only=false` (the release workflow uses it), exit 1 when the
manifest is not valid (the `FAIL:` lines then go to stderr, because stdout may be redirected
to a CI output file). `deny_exemptions` is off unless a manifest lists
an entry: each entry excuses one exact member path from the file-name deny rules below, with
a recorded reason, and is printed as a `NOTE:` whenever it is used. It never excuses the
banner files or a credential-shaped string.

Checks, in addition to the exact member sets:

* the archives are named `orinyx_mcp-<version>.tar.gz` and
  `orinyx_mcp-<version>-py3-none-any.whl`, with the manifest's version;
* no member path matches a deny rule: SMOKE_TEST, docs/qa/, .worktrees/, .env, fly.toml,
  CLAUDE.md (case-insensitive substrings) or a `.pem` suffix;
* no member contains a credential-shaped string (`ork_live_`, `ork_test_`, `ork_oat_` or
  `ork_ort_` followed by 8 or more letters, digits, `-` or `_`); the string is never printed;
* neither archive holds the terminal banner (`orinyx_mcp/banner.py`,
  `orinyx_mcp/assets/banner.json`), whose font licence is not cleared;
* with `--source`, every sdist member and every wheel member under `orinyx_mcp/` is
  byte-for-byte the file at the same path in that tree (generated metadata is exempt), and
  the wheel's version equals `__version__` in that tree;
* the wheel's METADATA has `Metadata-Version` 2.4 or later and `License-Expression:
  Apache-2.0`; with `--require-marker`, its description also holds the Registry `mcp-name`
  marker line.

The script reads the archives as data and never extracts them. It takes no credential.
"""

import argparse
import email
import email.message
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

PATH_DENY = (
    "SMOKE_TEST",
    "docs/qa/",
    ".worktrees/",
    ".env",
    "fly.toml",
    "CLAUDE.md",
)
PATH_DENY_SUFFIX = (".pem",)
# The terminal banner stays out of every distribution until its font licence is cleared.
BANNER_PATHS = ("orinyx_mcp/banner.py", "orinyx_mcp/assets/banner.json")
CREDENTIAL = re.compile(rb"ork_(?:live|test|oat|ort)_[A-Za-z0-9_-]{8,}")
MARKER = "mcp-name: io.github.lexthirteen-ai/orinyx-mcp"
LICENSE_EXPRESSION = "Apache-2.0"
MIN_METADATA_VERSION = (2, 4)
PACKAGE = "orinyx_mcp"
WHEEL_TAG = "py3-none-any"
# Hatchling writes this one file into the sdist; the build generates it, the tree has none.
# It also always copies .gitignore in. That is a tree file, so it is not listed here: a manifest
# names it, and --source compares its bytes like any other member.
GENERATED_SDIST_FILES = ("PKG-INFO",)


class Archive:
    """The regular files of one sdist or wheel, by member path, read as bytes."""

    def __init__(self, kind: str, path: Path):
        self.kind = kind
        self.path = path
        self.files: dict[str, bytes] = {}
        self.problems: list[str] = []

    def add(self, name: str, data: bytes) -> None:
        if name in self.files:
            self.problems.append(f"{self.kind} lists {name!r} twice")
        self.files[name] = data


def _safe_name(kind: str, name: str, problems: list[str]) -> bool:
    parts = PurePosixPath(name).parts
    if not name or name.startswith("/") or "\\" in name or "\0" in name or ".." in parts:
        problems.append(f"{kind} member has an unsafe path: {name!r}")
        return False
    return True


def read_sdist(path: Path) -> Archive:
    archive = Archive("sdist", path)
    try:
        with tarfile.open(path, "r:gz") as tar:
            for member in tar:
                if not _safe_name("sdist", member.name, archive.problems):
                    continue
                if member.isdir():
                    continue
                if not member.isfile():
                    archive.problems.append(f"sdist member is not a regular file: {member.name!r}")
                    continue
                handle = tar.extractfile(member)
                archive.add(member.name, handle.read() if handle else b"")
    except (tarfile.TarError, OSError, EOFError) as exc:
        archive.problems.append(f"sdist cannot be read: {type(exc).__name__}")
    return archive


def read_wheel(path: Path) -> Archive:
    archive = Archive("wheel", path)
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if not _safe_name("wheel", info.filename, archive.problems):
                    continue
                if info.is_dir():
                    continue
                archive.add(info.filename, zf.read(info))
    except (zipfile.BadZipFile, OSError) as exc:
        archive.problems.append(f"wheel cannot be read: {type(exc).__name__}")
    return archive


def strip_top(archive: Archive, top: str) -> dict[str, bytes]:
    """The sdist's files keyed by path under its top directory; a stray path is a problem."""
    out: dict[str, bytes] = {}
    prefix = top + "/"
    for name, data in archive.files.items():
        if not name.startswith(prefix):
            archive.problems.append(f"sdist member is outside {prefix}: {name!r}")
            continue
        out[name[len(prefix) :]] = data
    return out


def manifest_shape(manifest: dict) -> tuple[bool, list[str]]:
    """(wheel_only, problems): the manifest must carry exactly one of `sdist` and `wheel_only`."""
    has_sdist = "sdist" in manifest
    has_flag = "wheel_only" in manifest
    problems = []
    if has_flag and manifest["wheel_only"] is not True:
        problems.append("manifest wheel_only must be true when present")
    if has_sdist and has_flag:
        problems.append("manifest has both an 'sdist' list and 'wheel_only'; it needs exactly one")
    if not has_sdist and not has_flag:
        problems.append("manifest has neither an 'sdist' list nor 'wheel_only': true")
    return manifest.get("wheel_only") is True, problems


def load_manifest(path: Path) -> tuple[dict, list[str]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, [f"manifest cannot be read: {type(exc).__name__}"]
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return {}, ["manifest is not a JSON object"]
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        problems.append("manifest has no version")
    wheel_only, shape_problems = manifest_shape(manifest)
    problems += shape_problems
    for key in ["wheel"] if wheel_only or "sdist" not in manifest else ["sdist", "wheel"]:
        listed = manifest.get(key)
        if not isinstance(listed, list) or not all(isinstance(p, str) for p in listed):
            problems.append(f"manifest has no {key!r} list of paths")
        elif len(set(listed)) != len(listed):
            problems.append(f"manifest {key!r} list holds a path twice")
    exemptions = manifest.get("deny_exemptions", [])
    if not isinstance(exemptions, list) or not all(
        isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("reason"), str)
        and e["reason"].strip()
        for e in exemptions
    ):
        problems.append("manifest deny_exemptions must be a list of {path, reason} entries")
    return manifest, problems


def compare_sets(label: str, found: set[str], expected: set[str]) -> list[str]:
    out = [
        f"{label} has a file that is not in the manifest: {p!r}" for p in sorted(found - expected)
    ]
    out += [f"{label} is missing a manifest path: {p!r}" for p in sorted(expected - found)]
    return out


def path_denied(path: str) -> bool:
    lowered = path.lower()
    return any(rule.lower() in lowered for rule in PATH_DENY) or lowered.endswith(PATH_DENY_SUFFIX)


def banner_present(path: str) -> bool:
    return any(path == banned or path.endswith("/" + banned) for banned in BANNER_PATHS)


def check_content_rules(
    label: str, files: dict[str, bytes], exemptions: dict[str, str]
) -> tuple[list[str], list[str]]:
    failures, notes = [], []
    for path, data in sorted(files.items()):
        if banner_present(path):
            failures.append(f"{label} holds the terminal banner: {path!r}")
        if path_denied(path):
            if path in exemptions:
                notes.append(
                    f"{label} {path!r} is exempt from the file-name rules: {exemptions[path]}"
                )
            else:
                failures.append(f"{label} holds a path the deny rules refuse: {path!r}")
        if CREDENTIAL.search(data):
            failures.append(f"{label} member {path!r} holds a credential-shaped string")
    return failures, notes


def source_version(source: Path) -> tuple[str | None, list[str]]:
    init = source / PACKAGE / "__init__.py"
    try:
        text = init.read_text(encoding="utf-8")
    except OSError:
        return None, [f"--source has no {PACKAGE}/__init__.py"]
    found = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if not found:
        return None, [f"{PACKAGE}/__init__.py in --source has no __version__"]
    return found.group(1), []


def compare_with_source(label: str, files: dict[str, bytes], source: Path) -> list[str]:
    failures = []
    for path, data in sorted(files.items()):
        candidate = source / path
        if not candidate.is_file():
            failures.append(f"{label} member has no file in --source: {path!r}")
        elif candidate.read_bytes() != data:
            failures.append(f"{label} member differs from --source: {path!r}")
    return failures


def parse_metadata(data: bytes) -> tuple[email.message.Message, str]:
    message = email.message_from_bytes(data)
    body = message.get_payload()
    description = (message.get("Description") or "") + (body if isinstance(body, str) else "")
    return message, description


def check_metadata(wheel: Archive, expected_version: str, require_marker: bool) -> list[str]:
    metadata_files = [
        name
        for name in wheel.files
        if name.endswith(".dist-info/METADATA") and name.count("/") == 1
    ]
    if len(metadata_files) != 1:
        return [f"wheel holds {len(metadata_files)} METADATA files, expected 1"]
    message, description = parse_metadata(wheel.files[metadata_files[0]])
    failures = []
    if message.get("Version") != expected_version:
        failures.append(
            f"wheel METADATA Version is {message.get('Version')!r}, expected {expected_version!r}"
        )
    try:
        meta_version = tuple(int(n) for n in (message.get("Metadata-Version") or "").split("."))
    except ValueError:
        meta_version = ()
    if not meta_version or meta_version < MIN_METADATA_VERSION:
        failures.append(
            f"wheel Metadata-Version is {message.get('Metadata-Version')!r}, "
            f"expected {'.'.join(map(str, MIN_METADATA_VERSION))} or later"
        )
    if message.get("License-Expression") != LICENSE_EXPRESSION:
        failures.append(f"wheel METADATA lacks 'License-Expression: {LICENSE_EXPRESSION}'")
    if require_marker and MARKER not in description:
        failures.append(f"wheel description lacks the marker {MARKER!r}")
    return failures


def check_sdist_version(sdist_files: dict[str, bytes], expected_version: str) -> list[str]:
    data = sdist_files.get("PKG-INFO")
    if data is None:
        return []  # a missing PKG-INFO is already a manifest mismatch
    version = email.message_from_bytes(data).get("Version")
    if version != expected_version:
        return [f"sdist PKG-INFO Version is {version!r}, expected {expected_version!r}"]
    return []


def check_directory(dist_dir: Path, wheel_only: bool) -> tuple[Path | None, Path | None, list[str]]:
    failures = []
    if not dist_dir.is_dir():
        return None, None, [f"{dist_dir} is not a directory"]
    entries = sorted(dist_dir.iterdir())
    sdists = [p for p in entries if p.is_file() and p.name.endswith(".tar.gz")]
    wheels = [p for p in entries if p.is_file() and p.name.endswith(".whl")]
    others = [
        p
        for p in entries
        if p not in sdists and p not in wheels and not (p.is_file() and p.name == "SHA256SUMS")
    ]
    failures += [f"unexpected entry in the distribution directory: {p.name!r}" for p in others]
    if len(wheels) != 1:
        failures.append(f"expected exactly one wheel, found {len(wheels)}")
    if wheel_only:
        if sdists:
            failures.append(
                f"the manifest is wheel_only, but the directory holds {len(sdists)} sdist(s)"
            )
    elif len(sdists) != 1:
        failures.append(f"expected exactly one sdist, found {len(sdists)}")
    return (
        sdists[0] if len(sdists) == 1 else None,
        wheels[0] if len(wheels) == 1 else None,
        failures,
    )


def check_file_names(sdist_path: Path | None, wheel_path: Path | None, version: str) -> list[str]:
    """The index reads a release's project and version from these names, not from the bytes."""
    failures = []
    for label, path, expected in (
        ("sdist", sdist_path, f"{PACKAGE}-{version}.tar.gz"),
        ("wheel", wheel_path, f"{PACKAGE}-{version}-{WHEEL_TAG}.whl"),
    ):
        if path is not None and path.name != expected:
            failures.append(f"{label} file is named {path.name!r}, expected {expected!r}")
    return failures


def run(
    dist_dir: Path,
    manifest_path: Path,
    source: Path | None = None,
    require_marker: bool = False,
    wheel_only_flag: bool = False,
) -> tuple[list[str], list[str]]:
    """Every check. Returns (failures, notes); the distributions pass when failures is empty."""
    manifest, failures = load_manifest(manifest_path)
    wheel_only = manifest.get("wheel_only") is True
    if wheel_only_flag and not wheel_only:
        failures.append("--wheel-only was given, but the manifest does not say wheel_only: true")
    sdist_path, wheel_path, directory_failures = check_directory(dist_dir, wheel_only)
    failures += directory_failures
    notes: list[str] = []
    if "version" not in manifest or not isinstance(manifest.get("version"), str):
        return failures, notes
    failures += check_file_names(sdist_path, wheel_path, manifest["version"])
    listed = manifest.get("deny_exemptions", [])  # anything but a list is already a failure
    exemptions = {
        e["path"]: e["reason"]
        for e in (listed if isinstance(listed, list) else [])
        if isinstance(e, dict)
        and isinstance(e.get("path"), str)
        and isinstance(e.get("reason"), str)
    }

    expected_version = manifest["version"]
    if source is not None:
        from_source, problems = source_version(source)
        failures += problems
        if from_source is not None:
            if from_source != expected_version:
                failures.append(
                    f"manifest version {expected_version!r} differs from __version__ "
                    f"{from_source!r} in --source"
                )
            expected_version = from_source

    sdist_files: dict[str, bytes] = {}
    if sdist_path is not None:
        sdist = read_sdist(sdist_path)
        sdist_files = strip_top(sdist, f"{PACKAGE}-{manifest['version']}")
        failures += sdist.problems
        if isinstance(manifest.get("sdist"), list):
            failures += compare_sets("sdist", set(sdist_files), set(manifest["sdist"]))
        got_failures, got_notes = check_content_rules("sdist", sdist_files, exemptions)
        failures += got_failures
        notes += got_notes
        failures += check_sdist_version(sdist_files, expected_version)
        if source is not None:
            comparable = {p: d for p, d in sdist_files.items() if p not in GENERATED_SDIST_FILES}
            failures += compare_with_source("sdist", comparable, source)

    if wheel_path is not None:
        wheel = read_wheel(wheel_path)
        failures += wheel.problems
        if isinstance(manifest.get("wheel"), list):
            failures += compare_sets("wheel", set(wheel.files), set(manifest["wheel"]))
        got_failures, got_notes = check_content_rules("wheel", wheel.files, exemptions)
        failures += got_failures
        notes += got_notes
        for name in sorted(wheel.files):
            if not name.startswith(PACKAGE + "/") and not (
                name.split("/")[0].endswith(".dist-info") and name.count("/") >= 1
            ):
                failures.append(
                    f"wheel holds a file outside {PACKAGE}/ and its dist-info: {name!r}"
                )
        failures += check_metadata(wheel, expected_version, require_marker)
        if source is not None:
            comparable = {p: d for p, d in wheel.files.items() if p.startswith(PACKAGE + "/")}
            failures += compare_with_source("wheel", comparable, source)
    return failures, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check built distributions before publishing.")
    parser.add_argument("dist_dir", type=Path, nargs="?")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="the source tree the files were built from")
    parser.add_argument("--require-marker", action="store_true", help="require the mcp-name marker")
    parser.add_argument(
        "--wheel-only",
        action="store_true",
        help="assert that the manifest says wheel_only: true (the manifest decides, not this flag)",
    )
    parser.add_argument(
        "--print-shape",
        action="store_true",
        help="read only the manifest and print wheel_only=true or wheel_only=false",
    )
    args = parser.parse_args(argv)
    if args.print_shape:
        manifest, problems = load_manifest(args.manifest)
        for problem in problems:
            print("FAIL:", problem, file=sys.stderr)  # stdout may be a CI output file
        if problems:
            return 1
        print(f"wheel_only={'true' if manifest.get('wheel_only') is True else 'false'}")
        return 0
    if args.dist_dir is None:
        parser.error("dist_dir is required unless --print-shape is given")
    failures, notes = run(
        args.dist_dir, args.manifest, args.source, args.require_marker, args.wheel_only
    )
    for note in notes:
        print("NOTE:", note)
    for failure in failures:
        print("FAIL:", failure)
    print("check_dist:", "FAIL" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

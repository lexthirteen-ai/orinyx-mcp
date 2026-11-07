"""Refuse a source tree whose build would run code the tree supplies, before it is built.

    python -I scripts/check_build_inputs.py TREE_DIR

Run it from the trusted copy of the repository against the tree about to be built. Exit 0 when
the tree is safe to build, 1 otherwise; every problem is printed on its own `FAIL:` line.

`python -m build --no-isolation` and hatchling both load code named by the tree being built.
The tree is safe to build only when none of that machinery is present:

* `pyproject.toml` exists, parses, and names `build-backend = "hatchling.build"`;
* `[build-system]` has no `backend-path` (it makes the build import a module from the tree);
* no `hooks` table appears anywhere under `[tool.hatch]` (build hooks, metadata hooks, and the
  per-target hook tables all live there), and `[tool.hatch.version]` does not name a `source`
  other than `regex` (the `code` source runs a file from the tree);
* no top-level file or directory named `hatch_build*` (hatchling's default custom hook file);
* no top-level entry named `hatch*.toml` or `.hatch*.toml`, in any letter case: hatchling merges
  `hatch.toml` over `[tool.hatch]`, so it can name a hook, a version source or a hook file the
  checks above never see, and the other spellings are refused as well since they are never
  needed;
* no symbolic link anywhere in the checked-out tree (`.git` itself excepted), and, when the
  tree is a git checkout, no index entry with mode 120000.

Standard library only (`tomllib` needs Python 3.11 or later).
"""

import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

BACKEND = "hatchling.build"


def hook_tables(node, path):
    """Dotted paths of every key named `hooks` under a table."""
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}"
            if key == "hooks":
                found.append(here)
            found.extend(hook_tables(value, here))
    return found


def check_pyproject(tree: Path) -> list[str]:
    path = tree / "pyproject.toml"
    if not path.is_file():
        return ["no pyproject.toml in the tree"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        return [f"pyproject.toml does not parse: {error}"]
    failures = []
    system = data.get("build-system")
    if not isinstance(system, dict):
        failures.append("pyproject.toml has no [build-system] table")
        system = {}
    if system.get("build-backend") != BACKEND:
        failures.append(f"build-backend is {system.get('build-backend')!r}, expected {BACKEND!r}")
    if "backend-path" in system:
        failures.append("[build-system] sets backend-path")
    tool = data.get("tool")
    hatch = tool.get("hatch") if isinstance(tool, dict) else None
    if isinstance(hatch, dict):
        for name in hook_tables(hatch, "tool.hatch"):
            failures.append(f"[{name}] is present")
        version = hatch.get("version")
        if isinstance(version, dict) and version.get("source", "regex") != "regex":
            failures.append(f"[tool.hatch.version] source is {version['source']!r}, not 'regex'")
    return failures


def check_hook_files(tree: Path) -> list[str]:
    failures = []
    for entry in sorted(tree.iterdir()):
        lowered = entry.name.lower()
        if entry.name.startswith("hatch_build"):
            failures.append(f"{entry.name} is present at the top of the tree")
        elif lowered.removeprefix(".").startswith("hatch") and lowered.endswith(".toml"):
            failures.append(f"{entry.name} is present at the top of the tree (hatch configuration)")
    return failures


def check_symlinks(tree: Path) -> list[str]:
    failures = []
    for here, dirs, files in os.walk(tree, followlinks=False):
        if here == str(tree) and ".git" in dirs:
            dirs.remove(".git")
        for name in dirs + files:
            full = Path(here) / name
            if full.is_symlink():
                failures.append(f"{full.relative_to(tree)} is a symbolic link")
    if (tree / ".git").exists():
        listing = subprocess.run(
            ["git", "-C", str(tree), "ls-files", "-s", "-z"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if listing.returncode != 0:
            failures.append(f"git ls-files failed: {listing.stderr.strip()}")
        for entry in listing.stdout.split("\0"):
            info, _, name = entry.partition("\t")
            if info.split(" ")[0] == "120000":
                failures.append(f"{name} is a symbolic link in the git index")
    return failures


def check_tree(tree: Path) -> list[str]:
    if not tree.is_dir():
        return [f"{tree} is not a directory"]
    return check_pyproject(tree) + check_hook_files(tree) + check_symlinks(tree)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tree", type=Path, help="the source tree about to be built")
    args = parser.parse_args(argv)
    failures = check_tree(args.tree)
    for failure in failures:
        print("FAIL:", failure)
    print("check_build_inputs:", "FAIL" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

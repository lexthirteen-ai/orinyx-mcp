"""Text checks for a release workflow file, for a reviewer to run before applying it.

    python -I scripts/lint_release_workflow.py path/to/release.yml

Prints one `FAIL:` line per problem and exits 1 when there is any. It reads the text only (no
YAML library), so it is deliberately strict about layout: two-space indents, one key per line.
It checks:

* every `uses:` names its action by a full 40-hex commit sha followed by a `# <tag>` comment
  (a placeholder, a tag or a branch fails);
* the only trigger is exactly `push: tags: ["v*"]`, and nothing reads `inputs.`;
* `permissions: {}` is set at the top level, and `concurrency` sets `cancel-in-progress: false`;
* no `run:` block contains a `${{ ... }}` expression (values reach scripts through `env:`);
* `id-token: write` appears only in the jobs allowed to publish or attest, and
  `contents: write` only in the draft-release job;
* every `python` / `python3` command in a `run:` block is followed by `-I` (isolated mode, so
  a file in the directory it runs from, such as the tag's tree, cannot shadow a module);
* when a `run:` block calls `check_dist.py`, the workflow also reads the release's shape with
  `check_dist.py ... --print-shape` (the manifest's explicit `sdist` / `wheel_only` keys), and
  no `run:` block tests for an `"sdist"` key itself;
* the build job runs `check_build_inputs.py` on the tag's tree before the line that builds;
* the `testpypi` and `pypi` jobs hold the `LISTING_CHECK` text below, before they delete
  `dist/SHA256SUMS` (the files in `dist/` are exactly the files the checksum list names);
* the concurrency group names the tag (`github.ref_name`; the tag fixes the target);
* the `testpypi` and `pypi` jobs each run only on the target preflight derived from the tag;
* every `gh attestation verify` line also has `--signer-workflow`;
* no token or password setting, no `secrets.` reference other than none, and no actions cache.
"""

import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
TAG_COMMENT = re.compile(r"^\s+#\s*\S+")
ID_TOKEN_JOBS = {"testpypi", "pypi", "draft-release"}
CONTENTS_WRITE_JOBS = {"draft-release"}
TRIGGER = ["  push:", '    tags: ["v*"]']
PUBLISH_JOBS = ("testpypi", "pypi")
# The publish jobs hold no checkout of the repository, so this check is inline text. The
# workflow must hold these lines verbatim; the tests run this very text on scratch directories.
LISTING_CHECK = r"""diff <(cd dist && find . -mindepth 1 -maxdepth 1 ! -name SHA256SUMS \
    | sed 's|^\./||' | LC_ALL=C sort) \
  <(sed -E 's/^[0-9a-f]{64} [ *]//' dist/SHA256SUMS | LC_ALL=C sort) \
  || { echo "::error::the files in dist/ are not exactly the files SHA256SUMS lists"; exit 1; }"""
FORBIDDEN_TEXT = (
    (re.compile(r"\bsecrets\."), "a secrets.* reference"),
    (
        re.compile(r"^\s*(?:password|user|api[-_]?token|token):", re.I | re.M),
        "a credential setting",
    ),
    (re.compile(r"PYPI[_A-Z]*TOKEN|pypi-AgE", re.I), "a PyPI token"),
    (re.compile(r"actions/cache\b"), "an actions cache"),
    (re.compile(r"^\s+cache(?:-dependency-path)?:", re.M), "a cache setting"),
)


def python_without_isolation(content: str) -> bool:
    """True when a line of a run block starts a python command that is not followed by -I."""
    if content.lstrip().startswith("#"):
        return False
    tokens = content.split()
    for here, token in enumerate(tokens):
        name = token.strip("\"'()").rsplit("/", 1)[-1]
        if name in ("python", "python3") and (here + 1 >= len(tokens) or tokens[here + 1] != "-I"):
            return True
    return False


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def run_blocks(lines: list[str]):
    """Yield (line number, text) for every line of every `run:` value."""
    i = 0
    while i < len(lines):
        match = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", lines[i])
        if not match:
            i += 1
            continue
        base = indent_of(lines[i]) + (2 if lines[i].lstrip().startswith("- ") else 0)
        rest = match.group(2)
        if rest[:1] in ("|", ">"):
            i += 1
            while i < len(lines) and (not lines[i].strip() or indent_of(lines[i]) > base):
                yield i + 1, lines[i]
                i += 1
        else:
            yield i + 1, rest
            i += 1


def jobs(lines: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    in_jobs, current = False, None
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs and line and not line.startswith(" ") and not line.startswith("#"):
            in_jobs = False
        if in_jobs:
            job = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if job:
                current = job.group(1)
                out[current] = []
            elif current is not None:
                out[current].append(line)
    return out


def triggers(lines: list[str]) -> list[str]:
    """The lines of the top-level `on:` block."""
    found: list[str] = []
    on = False
    for line in lines:
        if re.match(r"^(?:on|\"on\"):\s*$", line):
            on = True
            continue
        if on and line and not line.startswith(" ") and not line.startswith("#"):
            break
        if on and line.strip():
            found.append(line.rstrip())
    return found


def listing_check_before_rm(body: list[str]) -> bool:
    """True when the body holds LISTING_CHECK, in full, before its `rm -f dist/SHA256SUMS`."""
    lines = [line.strip() for line in body]
    wanted = [line.strip() for line in LISTING_CHECK.splitlines()]
    removals = [n for n, line in enumerate(lines) if "rm -f dist/SHA256SUMS" in line]
    for start in range(len(lines) - len(wanted) + 1):
        if lines[start : start + len(wanted)] == wanted:
            return bool(removals) and start + len(wanted) <= removals[0]
    return False


def lint(text: str) -> list[str]:
    lines = text.splitlines()
    failures = []
    for number, line in enumerate(lines, 1):
        found = USES.match(line)
        if found and not found.group(1).startswith("./"):
            if not PINNED.match(found.group(1)) or not TAG_COMMENT.match(found.group(2)):
                failures.append(f"line {number}: uses: is not a full sha with a tag comment")
    if triggers(lines) != TRIGGER:
        failures.append(f"triggers are {triggers(lines)}, expected {TRIGGER}")
    if re.search(r"\binputs\.", text):
        failures.append("the file reads inputs., and the trigger has no inputs")
    if not any(line.rstrip() == "permissions: {}" for line in lines):
        failures.append("no top-level `permissions: {}`")
    if not any(line.strip() == "cancel-in-progress: false" for line in lines):
        failures.append("no `cancel-in-progress: false`")
    calls_check_dist = False
    for number, content in run_blocks(lines):
        if "${{" in content:
            failures.append(f"line {number}: a run block holds a ${{{{ }}}} expression")
        if python_without_isolation(content):
            failures.append(f"line {number}: a python command in a run block lacks -I")
        if "check_dist.py" in content:
            calls_check_dist = True
        if re.search(r"[\"']sdist[\"']", content):
            failures.append(f"line {number}: a run block tests for an sdist key itself")
    if calls_check_dist and "check_dist.py" in text and "--print-shape" not in text:
        failures.append("check_dist.py is called, but the shape is never read with --print-shape")
    groups = [line for line in lines if line.strip().startswith("group:")]
    if not any("github.ref_name" in line for line in groups):
        failures.append("the concurrency group does not name github.ref_name")
    for number, line in enumerate(lines, 1):
        if "gh attestation verify" in line and "--signer-workflow" not in line:
            failures.append(f"line {number}: gh attestation verify without --signer-workflow")
    for pattern, label in FORBIDDEN_TEXT:
        if pattern.search(text):
            failures.append(f"the file holds {label}")
    all_jobs = jobs(lines)
    build = [line.strip() for line in all_jobs.get("build", [])]
    checks = [
        n for n, line in enumerate(build) if "check_build_inputs.py" in line and line[:1] != "#"
    ]
    builds = [n for n, line in enumerate(build) if "-m build" in line and line[:1] != "#"]
    if "build" not in all_jobs:
        failures.append("no build job")
    elif not checks or not builds or checks[0] > builds[0]:
        failures.append("the build job does not run check_build_inputs.py before the build")
    for name in PUBLISH_JOBS:
        if name in all_jobs and not listing_check_before_rm(all_jobs[name]):
            failures.append(
                f"job {name!r} lacks the dist listing check before rm -f dist/SHA256SUMS"
            )
        gate = f"    if: ${{{{ needs.preflight.outputs.target == '{name}' }}}}"
        if name in all_jobs and gate not in all_jobs[name]:
            failures.append(f"job {name!r} does not run only on target {name}")
    for name, body in all_jobs.items():
        block = "\n".join(body)
        if re.search(r"^\s+id-token:\s*write\b", block, re.M) and name not in ID_TOKEN_JOBS:
            failures.append(f"job {name!r} holds id-token: write")
        if re.search(r"^\s+contents:\s*write\b", block, re.M) and name not in CONTENTS_WRITE_JOBS:
            failures.append(f"job {name!r} holds contents: write")
        if not re.search(r"^\s+permissions:", block, re.M):
            failures.append(f"job {name!r} sets no permissions of its own")
    return failures


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: lint_release_workflow.py FILE", file=sys.stderr)
        return 1
    failures = lint(Path(args[0]).read_text(encoding="utf-8"))
    for failure in failures:
        print("FAIL:", failure)
    print("lint_release_workflow:", "FAIL" if failures else "ok")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

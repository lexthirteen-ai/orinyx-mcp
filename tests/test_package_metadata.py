"""What `pyproject.toml` and the README promise a developer who finds the package on PyPI."""

import html.parser
import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
REPO = "lexthirteen-ai/orinyx-mcp"
PAGE = f"https://github.com/{REPO}/blob/main/"
IMAGE = f"https://raw.githubusercontent.com/{REPO}/main/"
# Paths like these never reach the public repository, so a link to one would be dead there.
NOT_EXPORTED = ("SMOKE_TEST", "docs/qa/")
# No README target stays relative.
HELD_RELATIVE = []
DEPENDENCIES = [
    "mcp>=2.3,<3",
    "httpx>=0.28,<1",
    "httpx2>=2.13,<3",
    "pydantic>=2.12,<3",
    "starlette>=1.3.1,<2",
    "uvicorn>=0.31.1,<1",
]
SDIST_EXCLUDE = ["/*/", "!/orinyx_mcp/", "!/tests/"]
SDIST_INCLUDE = [
    "orinyx_mcp/",
    "tests/",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "pyproject.toml",
]
# The only members outside SDIST_INCLUDE. The build writes PKG-INFO. Hatchling always copies
# .gitignore into an sdist, and `exclude` cannot remove it; it is the tree's own file, so
# check_dist.py compares its bytes like any other member.
SDIST_ADDED_BY_THE_BUILD = ["PKG-INFO", ".gitignore"]


def version_of(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def in_range(version: str, requirement: str) -> bool:
    floor, ceiling = re.fullmatch(r"[a-z0-9]+>=([0-9.]+),<([0-9.]+)", requirement).groups()
    return version_of(floor) <= version_of(version) < version_of(ceiling)


def test_the_build_backend_is_bounded_and_at_least_the_first_to_default_to_metadata_2_4():
    assert PROJECT["build-system"]["requires"] == ["hatchling>=1.27,<2"]
    assert PROJECT["build-system"]["build-backend"] == "hatchling.build"


def test_the_dependencies_are_exactly_the_bounded_ranges():
    assert PROJECT["project"]["dependencies"] == DEPENDENCIES


def test_every_locked_version_is_inside_its_range():
    locked = dict(
        line.split("==")
        for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
        if "==" in line and not line.startswith("#")
    )
    for requirement in DEPENDENCIES:
        name = re.match(r"[a-z0-9]+", requirement).group()
        assert in_range(locked[name], requirement), (name, locked[name])


@pytest.mark.parametrize(
    "version, inside",
    [("1.3.0", False), ("1.3.1", True), ("1.10.0", True), ("2.0.0", False)],
)
def test_the_range_check_can_fail(version, inside):
    assert in_range(version, "starlette>=1.3.1,<2") is inside


def test_the_project_table():
    project = PROJECT["project"]
    assert project["authors"] == [{"name": "Lex Hamilton"}]
    assert project["keywords"] == [
        "mcp",
        "model-context-protocol",
        "healthcare-ai",
        "evaluation",
        "fda-labels",
    ]
    assert project["classifiers"] == [
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Operating System :: POSIX",
        "Operating System :: MacOS",
        "Topic :: Software Development :: Testing",
    ]
    assert project["dynamic"] == ["version"]
    assert project["license"] == "Apache-2.0"


def test_the_six_project_urls_are_absolute():
    assert PROJECT["project"]["urls"] == {
        "Homepage": "https://orinyx.io/developers",
        "Documentation": PAGE + "docs/QUICKSTART.md",
        "Source": f"https://github.com/{REPO}",
        "Issues": f"https://github.com/{REPO}/issues",
        "Changelog": PAGE + "CHANGELOG.md",
        "Security": PAGE + "SECURITY.md",
    }


def test_the_sdist_holds_only_the_reviewed_list():
    sdist = PROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert sdist["include"] == SDIST_INCLUDE
    assert sdist["exclude"] == SDIST_EXCLUDE


def test_the_wheel_is_unchanged_and_ships_no_json_artifact():
    wheel = PROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["packages"] == ["orinyx_mcp"]
    assert wheel["artifacts"] == ["orinyx_mcp/assets/*.svg", "orinyx_mcp/assets/*.png"]


def test_the_committed_manifests_list_only_the_reviewed_sdist_paths():
    exact = {"README.md", "LICENSE", "CHANGELOG.md", "pyproject.toml", *SDIST_ADDED_BY_THE_BUILD}
    manifests = sorted((ROOT / "release" / "manifests").glob("*.json"))
    assert manifests
    for path in manifests:
        members = json.loads(path.read_text(encoding="utf-8"))["sdist"]
        assert set(SDIST_ADDED_BY_THE_BUILD) <= set(members), path
        for member in members:
            assert member in exact or member.startswith(("orinyx_mcp/", "tests/")), member


def test_no_test_file_holds_a_key_shaped_string():
    shape = re.compile(rb"ork_" + rb"(?:live|test|oat|ort)_[A-Za-z0-9_-]{8,}")
    hits = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and shape.search(path.read_bytes())
    }
    assert hits == set()


class _Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag, attrs):
        wanted = {"img": "src", "a": "href", "source": "srcset"}.get(tag)
        self.targets += [value for name, value in attrs if name == wanted and value]


def link_targets(markdown: str) -> list[str]:
    """Every Markdown link and image target, reference definition, `<img src>` and `<a href>`."""
    tags = _Tags()
    tags.feed(markdown)
    inline = re.findall(r"\]\(\s*<?([^)\s>]+)", markdown)
    definitions = re.findall(r"^\s*\[[^\]]+\]:\s*<?([^\s>]+)", markdown, re.MULTILINE)
    return inline + definitions + tags.targets


def relative(targets: list[str]) -> list[str]:
    return [t for t in targets if not t.startswith(("https://", "mailto:", "#"))]


def test_the_readme_has_no_relative_link_or_image():
    targets = link_targets(README)
    assert len(targets) > 30
    assert relative(targets) == HELD_RELATIVE


@pytest.mark.parametrize(
    "markdown",
    [
        "[a](docs/A.md)",
        "![a](assets/a.png)",
        "[![a](https://x.test/a.svg)](LICENSE)",
        "[a][r]\n\n[r]: docs/A.md\n",
        '<img src="assets/a.png" alt="a">',
        '<a href="docs/A.md">a</a>',
        '<picture><source srcset="assets/a.png"></picture>',
        "[a](http://x.test/)",
    ],
)
def test_the_link_check_finds_each_form_of_relative_target(markdown):
    assert relative(link_targets(markdown))


def test_the_link_check_allows_https_mail_and_anchors():
    assert relative(link_targets("[a](https://x.test) [b](mailto:a@x.test) [c](#d)")) == []


def test_every_repository_link_in_the_readme_points_at_a_public_file_in_this_tree():
    paths = [
        target.removeprefix(prefix).split("#")[0].rstrip("/")
        for target in link_targets(README)
        for prefix in (PAGE, IMAGE)
        if target.startswith(prefix)
    ]
    assert len(paths) == 21 - len(HELD_RELATIVE)
    for path in paths:
        assert (ROOT / path).exists(), path
        assert not any(rule in path for rule in NOT_EXPORTED), path

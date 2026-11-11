"""`scripts/check_dist.py` refuses any distribution that is not exactly what was reviewed.

Every archive here is built by hand in `tmp_path` (a tar.gz and a zip written with the
standard library); no build backend runs. Credential-shaped strings are assembled at run
time, so this file holds none.
"""

import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_dist", ROOT / "scripts" / "check_dist.py")
check_dist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_dist)

VERSION = "9.9.9"
TOP = f"orinyx_mcp-{VERSION}"
DIST_INFO = f"orinyx_mcp-{VERSION}.dist-info"
MARKER = "mcp-name: io.github.lexthirteen-ai/orinyx-mcp"
KEY_SHAPED = "ork_" + "live_" + "A1b2C3d4E5f6"
KEY_WITH_PUNCTUATION = "ork_" + "live_" + "ab-cd_efghij"

SOURCE_FILES = {
    "orinyx_mcp/__init__.py": f'__version__ = "{VERSION}"\n'.encode(),
    "orinyx_mcp/cli.py": b"def main():\n    return 0\n",
    "README.md": b"# orinyx-mcp\n",
}


def metadata(
    version: str = VERSION,
    metadata_version: str = "2.5",
    license_expression: str | None = "Apache-2.0",
    description: str = "A client.\n",
) -> bytes:
    lines = [f"Metadata-Version: {metadata_version}", "Name: orinyx-mcp", f"Version: {version}"]
    if license_expression is not None:
        lines.append(f"License-Expression: {license_expression}")
    return ("\n".join(lines) + "\n\n" + description).encode()


def clean_sdist_files() -> dict[str, bytes]:
    files = dict(SOURCE_FILES)
    files["PKG-INFO"] = metadata()
    return files


def clean_wheel_files() -> dict[str, bytes]:
    files = {p: d for p, d in SOURCE_FILES.items() if p.startswith("orinyx_mcp/")}
    files[f"{DIST_INFO}/METADATA"] = metadata()
    files[f"{DIST_INFO}/WHEEL"] = b"Wheel-Version: 1.0\n"
    files[f"{DIST_INFO}/RECORD"] = b""
    return files


def write_sdist(path: Path, files: dict[str, bytes], top: str = TOP) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def write_wheel(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


class Release:
    """A clean release in `tmp_path`: dist dir, source tree and manifest, each editable."""

    def __init__(self, tmp_path: Path):
        self.dist = tmp_path / "dist"
        self.dist.mkdir()
        self.source = tmp_path / "source"
        for name, data in SOURCE_FILES.items():
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.manifest_path = tmp_path / "manifest.json"
        self.sdist_files = clean_sdist_files()
        self.wheel_files = clean_wheel_files()
        self.manifest = {
            "version": VERSION,
            "sdist": sorted(self.sdist_files),
            "wheel": sorted(self.wheel_files),
            "deny_exemptions": [],
        }

    def make_wheel_only(self) -> "Release":
        """The manifest of a wheel-only release: `wheel_only: true` in place of `sdist`."""
        del self.manifest["sdist"]
        self.manifest["wheel_only"] = True
        return self

    def write(self, sdist: bool = True) -> "Release":
        if sdist:
            write_sdist(self.dist / f"{TOP}.tar.gz", self.sdist_files)
        write_wheel(self.dist / f"orinyx_mcp-{VERSION}-py3-none-any.whl", self.wheel_files)
        self.manifest_path.write_text(json.dumps(self.manifest))
        return self

    def run(self, *extra: str, source: bool = True) -> int:
        argv = [str(self.dist), "--manifest", str(self.manifest_path)]
        if source:
            argv += ["--source", str(self.source)]
        return check_dist.main(argv + list(extra))


def failing(release: Release, capsys, *extra: str, source: bool = True) -> str:
    """Run the check, expect exit 1, and return what it printed."""
    assert release.run(*extra, source=source) == 1
    return capsys.readouterr().out


def test_a_clean_release_passes(tmp_path, capsys):
    release = Release(tmp_path).write()
    assert release.run() == 0
    assert capsys.readouterr().out == "check_dist: ok\n"


def test_a_clean_release_passes_without_a_source_tree(tmp_path):
    assert Release(tmp_path).write().run(source=False) == 0


def test_a_planted_file_in_the_wheel_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/scratch.json"] = b"{}"
    out = failing(release.write(), capsys)
    assert "not in the manifest: 'orinyx_mcp/scratch.json'" in out


def test_a_planted_dotenv_image_in_the_sdist_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["orinyx_mcp/assets/.env.png"] = b"\x89PNG"
    out = failing(release.write(), capsys)
    assert "not in the manifest: 'orinyx_mcp/assets/.env.png'" in out
    assert "deny rules refuse: 'orinyx_mcp/assets/.env.png'" in out


def test_a_planted_file_in_the_sdist_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["extra.txt"] = b"x"
    out = failing(release.write(), capsys)
    assert "sdist has a file that is not in the manifest: 'extra.txt'" in out


def test_a_manifest_path_missing_from_the_archive_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.manifest["wheel"] = [*release.manifest["wheel"], "orinyx_mcp/gone.py"]
    out = failing(release.write(), capsys)
    assert "wheel is missing a manifest path: 'orinyx_mcp/gone.py'" in out


def test_the_manifest_lists_exact_paths_not_patterns(tmp_path, capsys):
    release = Release(tmp_path)
    release.manifest["wheel"] = [
        p for p in release.manifest["wheel"] if not p.startswith("orinyx_mcp/")
    ] + ["orinyx_mcp/*.py"]
    out = failing(release.write(), capsys)
    assert "missing a manifest path: 'orinyx_mcp/*.py'" in out
    assert "not in the manifest: 'orinyx_mcp/cli.py'" in out


def test_a_sdist_member_that_differs_from_the_source_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["README.md"] = b"# orinyx-mcp, edited after the review\n"
    out = failing(release.write(), capsys)
    assert "sdist member differs from --source: 'README.md'" in out


def test_a_wheel_member_that_differs_from_the_source_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/cli.py"] = b"def main():\n    return 1\n"
    out = failing(release.write(), capsys)
    assert "wheel member differs from --source: 'orinyx_mcp/cli.py'" in out


def test_a_member_with_no_source_file_fails(tmp_path, capsys):
    release = Release(tmp_path)
    (release.source / "orinyx_mcp" / "cli.py").unlink()
    out = failing(release.write(), capsys)
    assert "sdist member has no file in --source: 'orinyx_mcp/cli.py'" in out
    assert "wheel member has no file in --source: 'orinyx_mcp/cli.py'" in out


def test_generated_metadata_is_not_compared_with_the_source(tmp_path):
    release = Release(tmp_path).write()
    assert not (release.source / "PKG-INFO").exists()
    assert release.run() == 0


@pytest.mark.parametrize("path", ["orinyx_mcp/banner.py", "orinyx_mcp/assets/banner.json"])
@pytest.mark.parametrize("archive", ["wheel", "sdist"])
def test_the_banner_is_refused_even_when_the_manifest_lists_it(tmp_path, capsys, path, archive):
    release = Release(tmp_path)
    (release.source / path).parent.mkdir(parents=True, exist_ok=True)
    (release.source / path).write_bytes(b"art")
    getattr(release, f"{archive}_files")[path] = b"art"
    release.manifest[archive] = sorted(getattr(release, f"{archive}_files"))
    out = failing(release.write(), capsys)
    assert f"{archive} holds the terminal banner: {path!r}" in out


def test_a_banner_cannot_be_excused_by_an_exemption(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/banner.py"] = b"art"
    release.manifest["wheel"] = sorted(release.wheel_files)
    release.manifest["deny_exemptions"] = [{"path": "orinyx_mcp/banner.py", "reason": "x"}]
    assert "terminal banner" in failing(release.write(), capsys, source=False)


@pytest.mark.parametrize("archive", ["wheel", "sdist"])
def test_a_credential_shaped_string_is_refused_and_never_printed(tmp_path, capsys, archive):
    release = Release(tmp_path)
    getattr(release, f"{archive}_files")["orinyx_mcp/cli.py"] = f"KEY = '{KEY_SHAPED}'\n".encode()
    out = failing(release.write(), capsys, source=False)
    assert f"{archive} member 'orinyx_mcp/cli.py' holds a credential-shaped string" in out
    assert KEY_SHAPED not in out
    assert "A1b2C3d4" not in out


@pytest.mark.parametrize("archive", ["wheel", "sdist"])
def test_a_key_with_hyphen_and_underscore_is_refused_even_when_listed_and_equal_to_source(
    tmp_path, capsys, archive
):
    release = Release(tmp_path)
    data = f"KEY = '{KEY_WITH_PUNCTUATION}'\n".encode()
    release.wheel_files["orinyx_mcp/cli.py"] = data
    release.sdist_files["orinyx_mcp/cli.py"] = data
    (release.source / "orinyx_mcp" / "cli.py").write_bytes(data)  # byte-equal to the source
    release.manifest["sdist"] = sorted(release.sdist_files)  # and listed in the manifest
    release.manifest["wheel"] = sorted(release.wheel_files)
    out = failing(release.write(), capsys)
    assert f"{archive} member 'orinyx_mcp/cli.py' holds a credential-shaped string" in out
    assert KEY_WITH_PUNCTUATION not in out
    assert "ab-cd_" not in out


@pytest.mark.parametrize("tail", ["ab-cdefgh", "ab_cdefgh", "-_-_-_-_", "A1-b2_C3"])
def test_the_key_body_may_hold_hyphens_and_underscores(tmp_path, capsys, tail):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/cli.py"] = f"x = 'ork_live_{tail}'\n".encode()
    assert "credential-shaped" in failing(release.write(), capsys, source=False)


@pytest.mark.parametrize("prefix", ["live", "test", "oat", "ort"])
def test_every_key_prefix_is_refused(tmp_path, capsys, prefix):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/cli.py"] = f"x = 'ork_{prefix}_abcdefgh'\n".encode()
    assert "credential-shaped" in failing(release.write(), capsys, source=False)


def test_a_short_or_prefix_only_string_is_not_a_credential(tmp_path):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/cli.py"] = (
        b"a = 'ork_live_abc'\nb = 'ork_live_'\nc = 'ork_live_a-b_c'\n"
    )
    release.sdist_files["orinyx_mcp/cli.py"] = release.wheel_files["orinyx_mcp/cli.py"]
    (release.source / "orinyx_mcp" / "cli.py").write_bytes(release.wheel_files["orinyx_mcp/cli.py"])
    assert release.write().run() == 0


@pytest.mark.parametrize(
    "path",
    [
        "docs/SMOKE_TEST.md",
        "docs/qa/sheet.md",
        ".worktrees/build-x/a.py",
        "orinyx_mcp/.env",
        "config/prod.env.local",
        "fly.toml",
        "CLAUDE.md",
        "certs/server.pem",
    ],
)
def test_denied_paths_are_refused_even_when_listed_in_the_manifest(tmp_path, capsys, path):
    release = Release(tmp_path)
    release.sdist_files[path] = b"x"
    release.manifest["sdist"] = sorted(release.sdist_files)
    out = failing(release.write(), capsys, source=False)
    assert f"deny rules refuse: {path!r}" in out


def test_a_recorded_exemption_excuses_one_exact_path_and_says_so(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["fly.toml"] = b"app = 'x'\n"
    release.manifest["sdist"] = sorted(release.sdist_files)
    release.manifest["deny_exemptions"] = [
        {"path": "fly.toml", "reason": "recorded for this release"}
    ]
    assert release.write().run(source=False) == 0
    assert (
        "NOTE: sdist 'fly.toml' is exempt from the file-name rules: recorded for this release"
        in (capsys.readouterr().out)
    )


def test_an_exemption_does_not_cover_another_path(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["fly.toml"] = b"a"
    release.sdist_files["deploy/fly.toml"] = b"b"
    release.manifest["sdist"] = sorted(release.sdist_files)
    release.manifest["deny_exemptions"] = [{"path": "fly.toml", "reason": "recorded"}]
    out = failing(release.write(), capsys, source=False)
    assert "deny rules refuse: 'deploy/fly.toml'" in out
    assert "deny rules refuse: 'fly.toml'" not in out


def test_an_exemption_does_not_excuse_a_credential_shaped_string(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["fly.toml"] = f"k = '{KEY_SHAPED}'\n".encode()
    release.manifest["sdist"] = sorted(release.sdist_files)
    release.manifest["deny_exemptions"] = [{"path": "fly.toml", "reason": "recorded"}]
    assert "credential-shaped" in failing(release.write(), capsys, source=False)


def test_an_exemption_needs_a_reason(tmp_path, capsys):
    release = Release(tmp_path)
    release.manifest["deny_exemptions"] = [{"path": "fly.toml", "reason": "  "}]
    assert "deny_exemptions must be a list" in failing(release.write(), capsys)


@pytest.mark.parametrize("value", [None, 5, True, "fly.toml", {"path": "x", "reason": "y"}])
def test_deny_exemptions_that_are_not_a_list_fail_without_a_traceback(tmp_path, capsys, value):
    release = Release(tmp_path)
    release.manifest["deny_exemptions"] = value
    out = failing(release.write(), capsys)
    assert "FAIL: manifest deny_exemptions must be a list" in out
    assert "check_dist: FAIL" in out


@pytest.mark.parametrize("value", [None, 5])
def test_deny_exemptions_that_are_not_a_list_excuse_nothing(tmp_path, capsys, value):
    release = Release(tmp_path)
    release.wheel_files["orinyx_mcp/fly.toml"] = b"x"
    release.manifest["wheel"] = sorted(release.wheel_files)
    release.manifest["deny_exemptions"] = value
    assert "holds a path the deny rules refuse" in failing(release.write(), capsys, source=False)


def test_a_version_mismatch_in_the_wheel_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(version="9.9.8")
    out = failing(release.write(), capsys)
    assert "wheel METADATA Version is '9.9.8', expected '9.9.9'" in out


def test_a_source_version_that_differs_from_the_manifest_fails(tmp_path, capsys):
    release = Release(tmp_path)
    (release.source / "orinyx_mcp" / "__init__.py").write_text('__version__ = "9.9.8"\n')
    out = failing(release.write(), capsys)
    assert "manifest version '9.9.9' differs from __version__ '9.9.8' in --source" in out


def test_a_sdist_version_mismatch_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.sdist_files["PKG-INFO"] = metadata(version="9.9.8")
    assert "sdist PKG-INFO Version is '9.9.8'" in failing(release.write(), capsys)


def test_a_missing_license_expression_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(license_expression=None)
    assert "lacks 'License-Expression: Apache-2.0'" in failing(release.write(), capsys)


def test_a_different_license_expression_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(license_expression="MIT")
    assert "lacks 'License-Expression: Apache-2.0'" in failing(release.write(), capsys)


@pytest.mark.parametrize("old", ["2.1", "2.3", "1.2", "x"])
def test_an_old_metadata_version_fails(tmp_path, capsys, old):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(metadata_version=old)
    assert "Metadata-Version" in failing(release.write(), capsys)


@pytest.mark.parametrize("ok", ["2.4", "2.5", "2.10"])
def test_a_new_enough_metadata_version_passes(tmp_path, ok):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(metadata_version=ok)
    assert release.write().run() == 0


def test_the_marker_is_not_required_unless_the_switch_is_on(tmp_path):
    assert Release(tmp_path).write().run() == 0


def test_a_missing_marker_fails_with_the_switch_on(tmp_path, capsys):
    out = failing(Release(tmp_path).write(), capsys, "--require-marker")
    assert f"wheel description lacks the marker {MARKER!r}" in out


def test_the_marker_passes_with_the_switch_on(tmp_path):
    release = Release(tmp_path)
    release.wheel_files[f"{DIST_INFO}/METADATA"] = metadata(
        description=f"Intro\n\n<!-- {MARKER} -->\n"
    )
    assert release.write().run("--require-marker") == 0


def test_two_sdists_fail(tmp_path, capsys):
    release = Release(tmp_path).write()
    write_sdist(release.dist / "orinyx_mcp-9.9.8.tar.gz", release.sdist_files)
    assert "expected exactly one sdist, found 2" in failing(release, capsys)


def test_no_wheel_fails(tmp_path, capsys):
    release = Release(tmp_path).write()
    next(release.dist.glob("*.whl")).unlink()
    assert "expected exactly one wheel, found 0" in failing(release, capsys)


def test_a_stray_file_in_the_directory_fails(tmp_path, capsys):
    release = Release(tmp_path).write()
    (release.dist / "notes.txt").write_text("x")
    assert "unexpected entry in the distribution directory: 'notes.txt'" in failing(release, capsys)


def test_a_checksum_file_is_allowed(tmp_path):
    release = Release(tmp_path).write()
    (release.dist / "SHA256SUMS").write_text("0  file\n")
    assert release.run() == 0


def rename_archive(release: Release, suffix: str, name: str) -> None:
    """Give the one archive with this suffix a new file name. Its bytes do not change."""
    [archive] = release.dist.glob(f"*{suffix}")
    before = archive.read_bytes()
    assert archive.rename(release.dist / name).read_bytes() == before


def test_the_correct_file_names_pass(tmp_path, capsys):
    release = Release(tmp_path).write()
    assert sorted(p.name for p in release.dist.iterdir()) == [
        "orinyx_mcp-9.9.9-py3-none-any.whl",
        "orinyx_mcp-9.9.9.tar.gz",
    ]
    assert release.run() == 0
    assert "check_dist: ok" in capsys.readouterr().out


def test_the_correct_wheel_name_passes_in_a_wheel_only_release(tmp_path):
    release = Release(tmp_path).make_wheel_only().write(sdist=False)
    assert [p.name for p in release.dist.iterdir()] == ["orinyx_mcp-9.9.9-py3-none-any.whl"]
    assert release.run() == 0


@pytest.mark.parametrize("source", [True, False])
@pytest.mark.parametrize(
    "name",
    [
        "orinyx_mcp-9.9.8.tar.gz",  # wrong version
        "orinyx_mcp-9.9.9rc1.tar.gz",
        "other_project-9.9.9.tar.gz",  # wrong project
        "orinyx-mcp-9.9.9.tar.gz",
        "Orinyx_mcp-9.9.9.tar.gz",
    ],
)
def test_a_valid_sdist_under_a_wrong_name_fails(tmp_path, capsys, name, source):
    release = Release(tmp_path).write()
    rename_archive(release, ".tar.gz", name)
    out = failing(release, capsys, source=source)
    assert f"sdist file is named {name!r}, expected 'orinyx_mcp-9.9.9.tar.gz'" in out
    assert "check_dist: FAIL" in out
    assert "Traceback" not in out


WRONG_WHEEL_NAMES = [
    "orinyx_mcp-9.9.8-py3-none-any.whl",  # wrong version
    "orinyx_mcp-9.9.9rc1-py3-none-any.whl",
    "other_project-9.9.9-py3-none-any.whl",  # wrong project
    "orinyx-mcp-9.9.9-py3-none-any.whl",
    "Orinyx_mcp-9.9.9-py3-none-any.whl",
    "orinyx_mcp-9.9.9-py2.py3-none-any.whl",  # wrong tag
    "orinyx_mcp-9.9.9-cp312-cp312-macosx_11_0_arm64.whl",
    "orinyx_mcp-9.9.9-py3-none-linux_x86_64.whl",
    "orinyx_mcp-9.9.9-1-py3-none-any.whl",  # a build number
    "orinyx_mcp-9.9.9.whl",
]


@pytest.mark.parametrize("source", [True, False])
@pytest.mark.parametrize("name", WRONG_WHEEL_NAMES)
def test_a_valid_wheel_under_a_wrong_name_fails(tmp_path, capsys, name, source):
    release = Release(tmp_path).write()
    rename_archive(release, ".whl", name)
    out = failing(release, capsys, source=source)
    assert f"wheel file is named {name!r}, expected 'orinyx_mcp-9.9.9-py3-none-any.whl'" in out
    assert "check_dist: FAIL" in out
    assert "Traceback" not in out


@pytest.mark.parametrize("name", WRONG_WHEEL_NAMES)
def test_a_wheel_only_release_refuses_a_wrong_wheel_name(tmp_path, capsys, name):
    release = Release(tmp_path).make_wheel_only().write(sdist=False)
    rename_archive(release, ".whl", name)
    assert f"wheel file is named {name!r}" in failing(release, capsys)


def test_both_wrong_names_are_reported(tmp_path, capsys):
    release = Release(tmp_path).write()
    rename_archive(release, ".tar.gz", "orinyx_mcp-9.9.8.tar.gz")
    rename_archive(release, ".whl", "orinyx_mcp-9.9.8-py3-none-any.whl")
    out = failing(release, capsys)
    assert "sdist file is named" in out
    assert "wheel file is named" in out


def test_the_names_follow_the_manifest_version_not_the_source_version(tmp_path, capsys):
    """A manifest that is ahead of the tree already fails; the names are held to the manifest."""
    release = Release(tmp_path)
    release.manifest["version"] = "9.9.8"
    out = failing(release.write(), capsys)
    assert "differs from __version__" in out
    assert "expected 'orinyx_mcp-9.9.8.tar.gz'" in out
    assert "expected 'orinyx_mcp-9.9.8-py3-none-any.whl'" in out


def test_a_wheel_only_manifest_needs_no_sdist(tmp_path, capsys):
    release = Release(tmp_path).make_wheel_only()
    assert release.write(sdist=False).run() == 0
    assert capsys.readouterr().out == "check_dist: ok\n"


def test_the_wheel_only_flag_agrees_with_a_wheel_only_manifest(tmp_path):
    release = Release(tmp_path).make_wheel_only()
    assert release.write(sdist=False).run("--wheel-only") == 0


def test_a_manifest_with_neither_an_sdist_list_nor_wheel_only_fails(tmp_path, capsys):
    release = Release(tmp_path)
    del release.manifest["sdist"]
    out = failing(release.write(sdist=False), capsys)
    assert "manifest has neither an 'sdist' list nor 'wheel_only': true" in out


def test_a_missing_sdist_list_is_not_read_as_wheel_only_even_with_the_flag(tmp_path, capsys):
    release = Release(tmp_path)
    del release.manifest["sdist"]
    out = failing(release.write(sdist=False), capsys, "--wheel-only")
    assert "manifest has neither an 'sdist' list nor 'wheel_only': true" in out
    assert "--wheel-only was given, but the manifest does not say wheel_only: true" in out


def test_a_manifest_with_both_an_sdist_list_and_wheel_only_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.manifest["wheel_only"] = True
    out = failing(release.write(), capsys)
    assert "manifest has both an 'sdist' list and 'wheel_only'; it needs exactly one" in out


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_wheel_only_must_be_the_boolean_true(tmp_path, capsys, value):
    release = Release(tmp_path).make_wheel_only()
    release.manifest["wheel_only"] = value
    out = failing(release.write(sdist=False), capsys)
    assert "manifest wheel_only must be true when present" in out


def test_the_wheel_only_flag_with_a_manifest_that_lists_an_sdist_fails(tmp_path, capsys):
    out = failing(Release(tmp_path).write(), capsys, "--wheel-only")
    assert "--wheel-only was given, but the manifest does not say wheel_only: true" in out


def test_a_wheel_only_manifest_refuses_a_directory_that_holds_an_sdist(tmp_path, capsys):
    release = Release(tmp_path).make_wheel_only()
    out = failing(release.write(), capsys)
    assert "the manifest is wheel_only, but the directory holds 1 sdist(s)" in out


def test_a_sdist_manifest_refuses_a_directory_with_no_sdist(tmp_path, capsys):
    out = failing(Release(tmp_path).write(sdist=False), capsys)
    assert "expected exactly one sdist, found 0" in out


def test_a_wheel_only_release_still_applies_every_wheel_rule(tmp_path, capsys):
    release = Release(tmp_path).make_wheel_only()
    release.wheel_files["orinyx_mcp/scratch.json"] = b"{}"
    assert "not in the manifest" in failing(release.write(sdist=False), capsys)


@pytest.mark.parametrize(
    "edit, text, code",
    [
        (lambda m: None, "wheel_only=false", 0),
        (lambda m: (m.pop("sdist"), m.update(wheel_only=True)), "wheel_only=true", 0),
        (lambda m: m.pop("sdist"), "neither", 1),
        (lambda m: m.update(wheel_only=True), "both", 1),
    ],
)
def test_print_shape_reads_only_the_manifest(tmp_path, capsys, edit, text, code):
    release = Release(tmp_path)
    edit(release.manifest)
    release.manifest_path.write_text(json.dumps(release.manifest))
    assert check_dist.main(["--manifest", str(release.manifest_path), "--print-shape"]) == code
    captured = capsys.readouterr()
    assert text in (captured.out if code == 0 else captured.err)
    assert (captured.out == "") == (code == 1)  # a failure never writes to stdout


def test_a_directory_is_required_unless_print_shape_is_given(tmp_path):
    release = Release(tmp_path).write()
    with pytest.raises(SystemExit):
        check_dist.main(["--manifest", str(release.manifest_path)])


def test_a_wheel_file_outside_the_package_fails_even_when_listed(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files["tests/test_x.py"] = b"x"
    release.manifest["wheel"] = sorted(release.wheel_files)
    out = failing(release.write(), capsys, source=False)
    assert "wheel holds a file outside orinyx_mcp/ and its dist-info: 'tests/test_x.py'" in out


def test_an_sdist_member_outside_its_top_directory_fails(tmp_path, capsys):
    release = Release(tmp_path).write()
    write_sdist(release.dist / f"{TOP}.tar.gz", release.sdist_files, top="elsewhere-1.0")
    assert "sdist member is outside orinyx_mcp-9.9.9/" in failing(release, capsys)


def test_an_unsafe_member_path_fails(tmp_path, capsys):
    release = Release(tmp_path)
    release.wheel_files["../escape.py"] = b"x"
    out = failing(release.write(), capsys, source=False)
    assert "wheel member has an unsafe path: '../escape.py'" in out


def test_a_symlink_member_in_the_sdist_fails(tmp_path, capsys):
    release = Release(tmp_path).write()
    with tarfile.open(release.dist / f"{TOP}.tar.gz", "w:gz") as tar:
        link = tarfile.TarInfo(f"{TOP}/README.md")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    assert "sdist member is not a regular file" in failing(release, capsys)


def test_a_missing_or_broken_manifest_fails_without_a_traceback(tmp_path, capsys):
    release = Release(tmp_path).write()
    release.manifest_path.write_text("{not json")
    assert "manifest cannot be read" in failing(release, capsys)


def test_a_corrupt_archive_fails_without_a_traceback(tmp_path, capsys):
    release = Release(tmp_path).write()
    (release.dist / f"{TOP}.tar.gz").write_bytes(b"not a gzip")
    assert "sdist cannot be read" in failing(release, capsys)


def test_a_missing_distribution_directory_fails(tmp_path, capsys):
    release = Release(tmp_path).write()
    release.dist = tmp_path / "nope"
    assert "is not a directory" in failing(release, capsys)


def test_the_committed_manifests_are_well_formed_and_deny_nothing_by_default():
    manifests = sorted((ROOT / "release" / "manifests").glob("*.json"))
    assert manifests
    for path in manifests:
        data = json.loads(path.read_text())
        assert path.stem == data["version"]
        assert data["deny_exemptions"] == [], "an exemption is recorded in its own change"
        # exactly one of an sdist list and an explicit wheel_only: true
        assert ("sdist" in data) != ("wheel_only" in data)
        assert data.get("wheel_only", True) is True
        assert check_dist.manifest_shape(data)[1] == []
        for archive in [a for a in ("sdist", "wheel") if a in data]:
            listed = data[archive]
            assert listed == sorted(listed)
            assert len(set(listed)) == len(listed)
            assert not any("*" in p or p.startswith("/") for p in listed)
            assert not any(check_dist.banner_present(p) for p in listed)
        assert all(
            p.startswith("orinyx_mcp/") or p.startswith(f"orinyx_mcp-{data['version']}.dist-info/")
            for p in data["wheel"]
        )


def test_the_release_tools_are_not_part_of_the_package():
    packaged = {p.name for p in (ROOT / "orinyx_mcp").iterdir()}
    assert "check_dist.py" not in packaged
    assert "e2e_install_check.py" not in packaged

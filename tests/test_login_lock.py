"""The lock that lets one process at a time renew a sign-in, and where it may live.

A refresh token works once, so every process that shares a sign-in (two terminals, a stdio
server left running) takes one lock before it touches the keychain. The lock is an empty file
under `~/.cache/orinyx/`. It holds no credential, but a lock that can be pointed somewhere
else, or shared with another user, is a way to interfere with a sign-in. So:

- the folder is owner-only, whether it is new or was found open;
- a folder that is a symbolic link, or that belongs to another user, is refused, and nothing
  is created through it;
- a lock file that is a symbolic link is refused, and whatever it points at is left alone;
- a lock file that is not a regular file, or that belongs to another user, is refused;
- a new lock file is owner-only;
- without `fcntl` there is no lock, and so no sign-in;
- on a platform with no native keychain there is no store: a refusal, never another backend.

The home directory is a temporary folder and the keychain a stand-in. POSIX only, as the
sign-in itself is.
"""

import os
import stat
import sys
import time
import types

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from orinyx_mcp import credentials
from orinyx_mcp.credentials import AuthError, CredentialStore, LoginRecord, SavedLogin

API = "https://api.example"
ACCESS = "ork_oat_" + "a"
REAL_NATIVE_KEYRING = credentials._native_keyring
REFUSED = "Cannot acquire a private login lock."


def record() -> LoginRecord:
    """A saved sign-in that is good for another fifteen minutes."""
    return LoginRecord(
        resource=API,
        client=OAuthClientInformationFull(
            client_id="client-a",
            redirect_uris=["http://127.0.0.1:9876/callback"],
            token_endpoint_auth_method="none",
        ),
        tokens=OAuthToken(
            access_token=ACCESS,
            refresh_token="ork_ort_" + "r",
            scope="verify:read",
            expires_in=3600,
        ),
        expires_at=time.time() + 900,
    )


def _keychain_must_stay_closed():
    raise AssertionError("the keychain was opened")


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A temporary home directory, with the process mask cleared so each mode asserted here is
    exactly the one the package asked for."""
    monkeypatch.setattr(credentials.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(credentials, "_native_keyring", _keychain_must_stay_closed)
    previous = os.umask(0)
    try:
        yield tmp_path
    finally:
        os.umask(previous)


def take_lock():
    with CredentialStore(API).locked():
        pass


def lock_file(home):
    """Where the lock file for this origin lives: found by taking the lock once."""
    take_lock()
    [path] = (home / ".cache" / "orinyx").iterdir()
    return path


def mode(path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_a_new_lock_folder_and_lock_file_are_owner_only(home):
    path = lock_file(home)
    assert mode(path.parent) == 0o700
    assert mode(path) == 0o600
    assert path.read_bytes() == b""  # a lock, never a place for a credential


def test_a_lock_folder_found_open_is_made_owner_only(home):
    folder = home / ".cache" / "orinyx"
    folder.mkdir(parents=True, mode=0o777)
    take_lock()
    assert mode(folder) == 0o700


def test_a_lock_folder_that_is_a_symbolic_link_is_refused_and_nothing_goes_through_it(home):
    elsewhere = home / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    (home / ".cache").mkdir()
    (home / ".cache" / "orinyx").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(AuthError, match=REFUSED):
        take_lock()
    assert list(elsewhere.iterdir()) == []
    assert mode(elsewhere) == 0o755


def test_a_lock_folder_that_belongs_to_another_user_is_refused_before_anything_is_created(
    home, monkeypatch
):
    """Giving a folder to another user needs root, so this process is told it is someone else."""
    folder = home / ".cache" / "orinyx"
    folder.mkdir(parents=True, mode=0o700)
    someone_else = os.getuid() + 1
    with monkeypatch.context() as patched:
        patched.setattr(os, "getuid", lambda: someone_else)
        with pytest.raises(AuthError, match=REFUSED):
            take_lock()
    assert list(folder.iterdir()) == []


def test_a_lock_file_that_is_a_symbolic_link_is_refused_and_its_target_is_left_alone(home):
    path = lock_file(home)
    path.unlink()
    target = home / "elsewhere.txt"
    target.write_text("untouched")
    path.symlink_to(target)
    with pytest.raises(AuthError, match=REFUSED):
        take_lock()
    assert path.is_symlink()
    assert target.read_text() == "untouched"


def test_a_lock_file_that_is_a_dangling_symbolic_link_creates_nothing(home):
    path = lock_file(home)
    path.unlink()
    target = home / "not-there.txt"
    path.symlink_to(target)
    with pytest.raises(AuthError, match=REFUSED):
        take_lock()
    assert path.is_symlink()
    assert not target.exists()


def test_a_lock_file_that_is_not_a_regular_file_is_refused(home):
    path = lock_file(home)
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(AuthError, match=REFUSED):
        take_lock()


def test_a_lock_file_that_belongs_to_another_user_is_refused(home, monkeypatch):
    """As above, the other owner is simulated: the lock file's status reports another user."""
    lock_file(home)
    real_fstat = os.fstat

    def someone_elses(descriptor):
        real = real_fstat(descriptor)
        return types.SimpleNamespace(st_mode=real.st_mode, st_uid=real.st_uid + 1)

    with monkeypatch.context() as patched:
        patched.setattr(os, "fstat", someone_elses)
        with pytest.raises(AuthError, match=REFUSED):
            take_lock()


def test_without_fcntl_there_is_no_lock_and_so_no_sign_in(home, monkeypatch):
    opened = []

    class Keychain:
        def get_password(self, service, account):
            opened.append(account)
            return record().model_dump_json()

    monkeypatch.setattr(credentials, "_native_keyring", Keychain)
    assert SavedLogin(CredentialStore(API))() == ACCESS  # with the lock, the saved token
    assert opened == [API]
    monkeypatch.setitem(sys.modules, "fcntl", None)  # from here on, `import fcntl` fails
    with pytest.raises(AuthError, match=REFUSED):
        take_lock()
    with pytest.raises(AuthError, match=REFUSED):
        SavedLogin(CredentialStore(API))()
    assert opened == [API]  # refused before the keychain was read again


@pytest.mark.parametrize("platform", ["win32", "cygwin", "freebsd14", "sunos5", "aix"])
def test_a_platform_without_a_native_keychain_has_no_store(platform, home, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(credentials, "_native_keyring", REAL_NATIVE_KEYRING)
    # First, and alone: if this ever stops refusing, the test ends here, before any call that
    # would reach a real keychain.
    with pytest.raises(AuthError, match="supported on macOS and desktop Linux"):
        credentials._native_keyring()
    store = CredentialStore(API)
    with pytest.raises(AuthError, match="Cannot read secure login storage"):
        store.load()
    with pytest.raises(AuthError, match="No plaintext fallback"):
        store.save(record())
    assert credentials.saved_login(API) is None

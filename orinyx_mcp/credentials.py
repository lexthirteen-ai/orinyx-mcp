"""Local OAuth credentials. Hosted serving never reads this store."""

import contextlib
import hashlib
import os
import stat
import sys
import time
from pathlib import Path

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import BaseModel, Field

DEFAULT_API_URL = "https://orinyx-api.fly.dev"
SCOPES = ("verify:read", "verify:write", "arena:read", "arena:write")


class AuthError(Exception):
    """A credential failure whose message is safe for the terminal."""


def resource_url(value: str) -> str:
    from urllib.parse import urlsplit

    import httpx

    try:
        parts = urlsplit(value)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if (
            not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path not in ("", "/")
            or (parts.scheme != "https" and not (parts.scheme == "http" and local))
        ):
            raise ValueError
        return str(httpx.URL(value)).rstrip("/")
    except (ValueError, httpx.InvalidURL):
        raise AuthError("Login requires an HTTPS API origin (HTTP only on loopback).") from None


class LoginRecord(BaseModel):
    resource: str
    client: OAuthClientInformationFull = Field(repr=False)
    tokens: OAuthToken | None = Field(default=None, repr=False)
    revocation_token: str | None = Field(default=None, repr=False)
    expires_at: float = Field(default=0, ge=0, allow_inf_nan=False)


def _native_keyring():
    # Do not load keyring config, entry points, or an alternate plaintext backend.
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
    elif sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring
    else:
        raise AuthError("Secure login storage is supported on macOS and desktop Linux.")
    return Keyring()


class CredentialStore:
    def __init__(self, resource: str):
        self.resource = resource_url(resource)

    def load(self) -> LoginRecord | None:
        try:
            raw = _native_keyring().get_password("orinyx-cli", self.resource)
            if raw is None:
                return None
            if len(raw) > 65536:
                raise ValueError
            record = LoginRecord.model_validate_json(raw)
            if record.resource != self.resource:
                raise ValueError
            from urllib.parse import urlsplit

            redirect = urlsplit(str((record.client.redirect_uris or [""])[0]))
            if (
                redirect.scheme != "http"
                or redirect.hostname != "127.0.0.1"
                or redirect.path != "/callback"
                or not redirect.port
                or redirect.username
                or redirect.query
                or redirect.fragment
            ):
                raise ValueError
            return record
        except Exception:
            raise AuthError(
                "Cannot read secure login storage. Unlock the OS keychain or use an API key."
            ) from None

    def save(self, record: LoginRecord) -> None:
        if record.resource != self.resource:
            raise AuthError("Login storage does not match the API resource.")
        try:
            _native_keyring().set_password("orinyx-cli", self.resource, record.model_dump_json())
        except Exception:
            raise AuthError(
                "Cannot save login in the OS keychain. No plaintext fallback is used."
            ) from None

    def delete(self) -> None:
        try:
            _native_keyring().delete_password("orinyx-cli", self.resource)
        except Exception:
            raise AuthError("Cannot remove the login from the OS keychain.") from None

    @contextlib.contextmanager
    def locked(self):
        """One refresh winner across CLI processes and long-running stdio servers."""
        try:
            import fcntl

            directory = Path.home() / ".cache" / "orinyx"
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = directory.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise OSError
            os.chmod(directory, 0o700)
            name = hashlib.sha256(self.resource.encode()).hexdigest() + ".lock"
            fd = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except (ImportError, OSError):
            raise AuthError("Cannot acquire a private login lock.") from None
        with os.fdopen(fd, "w") as lock:
            info = os.fstat(lock.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise AuthError("Cannot acquire a private login lock.")
            deadline = time.monotonic() + 20
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise AuthError(
                            "Another login operation is running. Try again shortly."
                        ) from None
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class SavedLogin:
    def __init__(self, store: CredentialStore):
        self.store = store

    def __call__(self) -> str:
        from orinyx_mcp.login import OAuthSession

        with self.store.locked():
            record = self.store.load()
            if record is None or record.tokens is None:
                raise AuthError("No saved login. Run orinyx login.")
            if record.expires_at <= time.time() + 60:
                # Persist the spent state BEFORE the exchange. A crash or lost response must
                # never replay a rotated token and revoke another process's fresh grant.
                previous = record.tokens
                record.revocation_token = previous.refresh_token
                record.tokens = None
                self.store.save(record)
                with OAuthSession(record.resource) as session:
                    record = session.refresh(record, previous)
                self.store.save(record)
            if record.tokens is None:
                raise AuthError("Refresh returned no credential. Run orinyx login again.")
            return record.tokens.access_token


def saved_login(url: str) -> SavedLogin | None:
    store = CredentialStore(url)
    try:
        record = store.load()
    except AuthError:
        return None
    return SavedLogin(store) if record and record.tokens else None

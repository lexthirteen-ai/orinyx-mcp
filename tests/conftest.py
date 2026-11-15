"""No database, no engine: every test here drives the package with fakes."""

import errno
import ipaddress
import os
import socket
import sys
from pathlib import Path

import pytest

# No test opens the OS keychain.
#
# The package loads its keychain backend from one of these two modules and from nowhere else
# (orinyx_mcp/credentials.py). For the whole test session neither can be imported: Python
# raises ImportError for a module name that sys.modules maps to None. A sign-in saved on the
# machine that runs the tests is therefore never read, refreshed or sent. A test that needs a
# sign-in store replaces `credentials._native_keyring` with a fake, as the `store` fixture in
# tests/test_login.py does.
KEYCHAIN_BACKENDS = ("keyring.backends.macOS", "keyring.backends.SecretService")
for _backend in KEYCHAIN_BACKENDS:
    sys.modules[_backend] = None

# A child process does not inherit that. It gets this directory first on its import path
# instead: the `keyring.py` in it refuses to be imported. The helpers that build a child's
# environment add the directory themselves; a fixture below adds it for a child that inherits
# this process's environment.
NO_KEYCHAIN = str(Path(__file__).resolve().parent / "no_keychain")


@pytest.fixture(autouse=True)
def _no_engine_env(monkeypatch):
    for name in ("ORINYX_API_URL", "ORINYX_API_KEY", "MCP_PUBLIC_URL", "ORINYX_HOP_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _children_cannot_import_keyring(monkeypatch):
    """A child process that inherits this environment finds tests/no_keychain first."""
    monkeypatch.setenv("PYTHONPATH", NO_KEYCHAIN, prepend=os.pathsep)


_LOCALHOST = ("localhost", b"localhost")
_REFUSED = "the tests reach this machine only"


def _ip(host):
    """The IP address `host` spells, or None when it is a name."""
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    try:
        return ipaddress.ip_address(str(host).partition("%")[0])
    except ValueError:
        return None


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch):
    """No test reaches another machine. A connection that is not loopback, or a lookup of any
    name but localhost, is refused where it is made, and the test then fails even if the code
    under test caught the refusal. The value is the list of refusals, for the one test that
    checks this guard."""
    refused: list[str] = []
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def remote(sock, address) -> bool:
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return False
        ip = _ip(address[0])
        if address[0] in _LOCALHOST or (ip is not None and ip.is_loopback):
            return False
        refused.append(f"connection to {address[0]}")
        return True

    def connect(sock, address):
        if remote(sock, address):
            raise ConnectionRefusedError(errno.ECONNREFUSED, _REFUSED)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        if remote(sock, address):
            return errno.ECONNREFUSED
        return real_connect_ex(sock, address)

    def getaddrinfo(*args, **kwargs):
        host = args[0] if args else kwargs.get("host")
        # An IP address is resolved without asking anyone. Any name but localhost is not.
        if host and host not in _LOCALHOST and _ip(host) is None:
            refused.append(f"lookup of {host}")
            raise socket.gaierror(socket.EAI_NONAME, _REFUSED)
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield refused
    assert not refused, f"this test tried to reach another machine: {refused}"

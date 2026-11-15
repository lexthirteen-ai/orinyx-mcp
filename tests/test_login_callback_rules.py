"""What the sign-in callback takes, and what it answers 400.

`orinyx login` listens on 127.0.0.1 for one request: the browser coming back from the sign-in
page with a `code`. Other things on the same machine can reach that port too (another page in
the browser, another local program), so the listener takes a request only when every part of
it is right, answers 400 to anything else and goes on waiting. `test_login.py` holds a wrong
`state`, a denial, a doubled `code`, a wrong issuer and a wrong path. This file holds the rest:

- `Host` is exactly `127.0.0.1:<port>`: no other name for this machine and no other site (a page
  that points its own name at 127.0.0.1 still sends that name here);
- the request target is a path, never a full URL;
- the request line is under 8192 characters;
- `state` is the whole value, not its beginning and not a longer one;
- `code` is present and not empty;
- the path is exactly `/callback`, and the method is GET.

Each request is written by hand over a connection to 127.0.0.1, so its request line and its
headers are exactly what the case says. All values are synthetic.
"""

import http.client

import pytest
from orinyx_mcp import login
from orinyx_mcp.credentials import AuthError

GOOD = "/callback?code=code-a&state=state-a"
HOST = "127.0.0.1:{port}"
# case -> (request target, Host header or None for no header)
REFUSED = {
    "another site's name in Host": (GOOD, "attacker.example"),
    "another site's name with this port": (GOOD, "attacker.example:{port}"),
    "localhost in Host": (GOOD, "localhost:{port}"),
    "the IPv6 loopback in Host": (GOOD, "[::1]:{port}"),
    "Host without the port": (GOOD, "127.0.0.1"),
    "Host with another port": (GOOD, "127.0.0.1:1"),
    "no Host header": (GOOD, None),
    "a full URL as the request target": ("http://127.0.0.1:{port}" + GOOD, HOST),
    "a request line over 8192 characters": (GOOD + "&pad=" + "x" * 8192, HOST),
    "the beginning of the state": ("/callback?code=code-a&state=state-", HOST),
    "the state with more after it": ("/callback?code=code-a&state=state-ab", HOST),
    "an empty code": ("/callback?code=&state=state-a", HOST),
    "no code": ("/callback?state=state-a", HOST),
    "a slash after the path": ("/callback/?code=code-a&state=state-a", HOST),
}


def _ask(callback, target, host, method="GET"):
    """Send one hand-written request to the listener; return the status it answers."""
    port = callback.server.server_port
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.putrequest(
            method, target.format(port=port), skip_host=True, skip_accept_encoding=True
        )
        if host is not None:
            connection.putheader("Host", host.format(port=port))
        if method != "GET":
            connection.putheader("Content-Length", "0")
        connection.endheaders()
        callback.server.handle_request()  # the request is already waiting on the socket
        return connection.getresponse().status
    finally:
        connection.close()


@pytest.fixture
def callback():
    listener = login.Callback("state-a", issuer="https://api.example")
    try:
        yield listener
    finally:
        listener.close()


def _assert_still_waiting(callback):
    assert callback.code is None and not callback.denied
    with pytest.raises(AuthError, match="timed out"):
        callback.wait(timeout=0)


def test_the_right_callback_is_taken(callback):
    assert _ask(callback, GOOD, HOST) == 200
    assert callback.wait(timeout=0) == "code-a"


@pytest.mark.parametrize("case", list(REFUSED))
def test_any_other_request_is_answered_400_and_the_listener_goes_on_waiting(case, callback):
    target, host = REFUSED[case]
    assert _ask(callback, target, host) == 400
    _assert_still_waiting(callback)
    # The same listener still takes the right callback afterwards: a refusal does not end it.
    assert _ask(callback, GOOD, HOST) == 200
    assert callback.wait(timeout=0) == "code-a"


def test_a_post_is_not_a_callback(callback):
    assert _ask(callback, GOOD, HOST, method="POST") == 501
    _assert_still_waiting(callback)

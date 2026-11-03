"""Trace context in a request's `_meta` costs linear time (CVE-2026-114603).

The mcp SDK wraps every inbound message in OpenTelemetry middleware, which extracts W3C trace
context from the message's `_meta`. opentelemetry-api 1.45.0 split `tracestate` with a regex
that is quadratic in a run of spaces, and the carrier here is the JSON-RPC body, so no HTTP
header limit stands in front of it: one signed-in request near the 4 MiB body cap could hold
the server's event loop for hours. 1.45.1 parses in linear time and discards an oversized
`tracestate`. This test pins that floor."""

import logging
import time

import pytest

pytest.importorskip("mcp")

from mcp.shared._otel import extract_trace_context  # noqa: E402

TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


def test_oversized_tracestate_in_meta_is_cheap(caplog):
    # 1 MiB of spaces with no comma: well over an hour on 1.45.0, milliseconds on 1.45.1.
    meta = {"traceparent": TRACEPARENT, "tracestate": "a=b" + " " * (1 << 20) + "x"}
    caplog.set_level(logging.CRITICAL)
    start = time.perf_counter()
    extract_trace_context(meta)
    assert time.perf_counter() - start < 1.0


def test_valid_trace_context_still_parents_the_span():
    ctx = extract_trace_context({"traceparent": TRACEPARENT, "tracestate": "vendor=value"})
    assert ctx is not None

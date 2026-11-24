"""Guest-visible responses of the requester-side proxy fixture used by the bridge."""

import pytest

from test_placement_bridge import fake_cred_proxy


REQUEST = b"GET /anthropic/v1/messages HTTP/1.1\r\n\r\n"
ORIGIN = "https://api.anthropic.com"


def interrupted(*args):
    raise OSError("private diagnostic sentinel")


def exchange(*, credentials=lambda name: "fixture-key", provider=interrupted, origin=ORIGIN,
             request=REQUEST, **load):
    writes = []
    closed = []
    fake_cred_proxy.handle(request, {"anthropic": origin}, credentials, provider,
                           send=writes.append, destroy=lambda: closed.append(True), **load)
    return b"".join(writes), bool(closed)


def assert_bad_gateway(reply, expected):
    wire, closed = reply
    headers, body = wire.split(b"\r\n\r\n", 1)
    assert headers.split(b"\r\n")[0] == b"HTTP/1.1 502 Bad Gateway"
    assert b"content-type: text/plain" in headers.split(b"\r\n")
    assert b"connection: close" not in headers.lower().split(b"\r\n")
    assert f"content-length: {len(body)}".encode() in headers.split(b"\r\n")
    assert body == b"sandbox credential proxy: " + expected + b" for anthropic\n"
    assert not closed


@pytest.mark.parametrize("credentials", [interrupted, lambda name: None], ids=["error", "missing"])
def test_missing_credential_response(credentials):
    assert_bad_gateway(exchange(credentials=credentials), b"no credential")


def test_provider_setup_error_response():
    assert_bad_gateway(exchange(), b"upstream error")
    assert_bad_gateway(exchange(origin="https://["), b"upstream error")


@pytest.mark.parametrize(
    ("status", "headers"),
    [
        (200, (("invalid name", "value"),)),
        (200, (("field", "line\r\nbreak"),)),
        (200, (("content-length", "+5"),)),
        (200, (("content-length", "5"), ("Content-Length", "5"))),
        (200, (("content-length", "5"), ("transfer-encoding", "chunked"))),
        (200, (("trailer", "x-check"),)),
        (200, (("trailer", "x-check"), ("transfer-encoding", "chunked, gzip"))),
        (101, (("trailer", "x-check"), ("transfer-encoding", "chunked"))),
        (204, (("trailer", "x-check"), ("transfer-encoding", "chunked"))),
        (304, (("trailer", "x-check"), ("transfer-encoding", "chunked"))),
    ],
)
def test_invalid_upstream_headers_get_a_complete_error_response(status, headers):
    def provider(*args):
        return fake_cred_proxy.UpstreamResponse(status, headers, pytest.fail)

    assert_bad_gateway(exchange(provider=provider), b"upstream error")


def test_upstream_body_error_closes_the_connection_after_headers():
    headers = (("content-length", "6"),)

    def provider(*args):
        return fake_cred_proxy.UpstreamResponse(200, headers, interrupted)

    wire, closed = exchange(provider=provider)
    assert wire == b"HTTP/1.1 200 OK\r\ncontent-length: 6\r\n\r\n"
    assert closed


def test_valid_chunked_reply_with_trailer_is_relayed():
    headers = (("transfer-encoding", "Chunked"), ("trailer", "x-check"))
    body = b"5\r\nmodel\r\n0\r\nx-check: ok\r\n\r\n"

    def provider(*args):
        return fake_cred_proxy.UpstreamResponse(200, headers, lambda: body)

    wire, closed = exchange(provider=provider)
    assert wire == (b"HTTP/1.1 200 OK\r\ntransfer-encoding: Chunked\r\ntrailer: x-check\r\n\r\n"
                    + body)
    assert not closed


def test_route_denial_preserves_the_403():
    wire, closed = exchange(request=REQUEST.replace(b"/anthropic/", b"/other/"))
    assert wire == (b"HTTP/1.1 403 Forbidden\r\ncontent-type: text/plain\r\ncontent-length: 40\r\n\r\n"
                    b"route not allowed by the sandbox policy\n")
    assert not closed


@pytest.mark.parametrize(
    ("load", "message"),
    [
        ({"total_in_flight": 128}, b"too many requests in flight"),
        ({"credentials_in_flight": 128}, b"too many requests waiting for a credential"),
    ],
)
def test_capacity_response_closes_the_connection(load, message):
    wire, closed = exchange(credentials=pytest.fail, **load)
    headers, body = wire.split(b"\r\n\r\n", 1)
    assert headers.split(b"\r\n")[0] == b"HTTP/1.1 503 Service Unavailable"
    assert b"connection: close" in headers.split(b"\r\n")
    assert body == b"sandbox credential proxy: " + message + b"\n"
    assert closed


def test_pipelining_limit_closes_without_a_response():
    assert exchange(credentials=pytest.fail, connection_in_flight=2) == (b"", True)

"""A behavioural fake of agent-toolkit's credential proxy for placement bridge tests.

Response behaviour follows agent-toolkit ``1e721c01`` (Consiliency/agent-toolkit#103).
The credential boundary design reference is ``9304a5b9``.

* a request for ``/<provider>/<path>`` goes to that provider's allowlisted origin with the
  real credential; any other route is refused;
* the guest's placeholder credential headers (``authorization``, ``x-api-key`` ...) never
  reach the provider;
* it never logs headers, credentials or bodies.

The fake intentionally masks credential bytes in upstream response bodies for test
safety. The provider is an in-process callable. Each call handles one request and
takes the current load as input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
import re
from urllib.parse import urlsplit

STRIPPED = {"authorization", "x-api-key", "api-key", "proxy-authorization", "cookie", "host",
            "connection"}

STATUS_PHRASES = {status.value: status.phrase for status in HTTPStatus}
MAX_REQUESTS_PER_CONNECTION = 2
MAX_REQUESTS = 128


def parse(raw: bytes) -> tuple[str, str, dict[str, str], bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, path, _version = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return method, path, headers, body


@dataclass(frozen=True)
class UpstreamResponse:
    """Provider headers followed by body bytes in their declared wire framing."""

    status: int
    headers: tuple[tuple[str, str], ...]
    read_body: Callable[[], bytes]


def upstream_head(response: UpstreamResponse) -> bytes:
    headers: dict[str, list[str]] = {}
    for name, value in response.headers:
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise ValueError("invalid header name")
        if not re.fullmatch(r"[\t\x20-\x7e\x80-\xff]*", value):
            raise ValueError("invalid header value")
        headers.setdefault(name.lower(), []).append(value)

    lengths = headers.get("content-length", [])
    encodings = headers.get("transfer-encoding", [])
    if lengths and (len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]) or encodings):
        raise ValueError("invalid content length")
    if "trailer" in headers:
        final_coding = ",".join(encodings).rsplit(",", 1)[-1].strip().lower()
        if final_coding != "chunked" or response.status < 200 or response.status in (204, 304):
            raise ValueError("invalid trailer framing")

    reason = STATUS_PHRASES.get(response.status, "")
    fields = "".join(f"{name}: {value}\r\n" for name, value in response.headers)
    return f"HTTP/1.1 {response.status} {reason}\r\n{fields}\r\n".encode("latin-1")


def text_response(status: HTTPStatus, message: str, *, close: bool = False) -> bytes:
    body = (message + "\n").encode()
    connection = "connection: close\r\n" if close else ""
    return (f"HTTP/1.1 {status.value} {status.phrase}\r\ncontent-type: text/plain\r\n".encode()
            + f"content-length: {len(body)}\r\n{connection}\r\n".encode() + body)


def handle(raw: bytes, routes: dict[str, str], credentials: Callable[[str], str | None],
           provider: Callable[[str, str, dict[str, str], bytes], UpstreamResponse],
           *, send: Callable[[bytes], None], destroy: Callable[[], None],
           connection_in_flight: int = 0, total_in_flight: int = 0,
           credentials_in_flight: int = 0) -> None:
    """Relay one response or drop the connection if a sent response is interrupted."""
    if connection_in_flight >= MAX_REQUESTS_PER_CONNECTION:
        destroy()
        return
    if total_in_flight >= MAX_REQUESTS:
        send(text_response(HTTPStatus.SERVICE_UNAVAILABLE,
                           "sandbox credential proxy: too many requests in flight", close=True))
        destroy()
        return

    method, path, headers, body = parse(raw)
    name = path.split("/", 2)[1] if path.startswith("/") else ""
    if name not in routes or method == "CONNECT":
        send(text_response(HTTPStatus.FORBIDDEN, "route not allowed by the sandbox policy"))
        return
    if credentials_in_flight >= MAX_REQUESTS:
        send(text_response(HTTPStatus.SERVICE_UNAVAILABLE,
                           "sandbox credential proxy: too many requests waiting for a credential", close=True))
        destroy()
        return

    try:
        secret = credentials(name)
    except Exception:
        secret = None
    if not secret:
        send(text_response(HTTPStatus.BAD_GATEWAY, f"sandbox credential proxy: no credential for {name}"))
        return

    try:
        origin = routes[name]
        endpoint = urlsplit(origin)
        if endpoint.scheme != "https" or not endpoint.hostname:
            raise ValueError("invalid upstream origin")
        upstream_path = "/" + path.split("/", 2)[2] if path.count("/") >= 2 else "/"
        forwarded = {k: v for k, v in headers.items() if k not in STRIPPED}
        forwarded["authorization"] = "Bearer " + secret
        response = provider(origin, upstream_path, forwarded, body)
        head = upstream_head(response)
    except Exception:
        send(text_response(HTTPStatus.BAD_GATEWAY, f"sandbox credential proxy: upstream error for {name}"))
        return

    try:
        send(head)
        answer = response.read_body()
        secret_bytes = secret.encode()
        send(answer.replace(secret_bytes, b"*" * len(secret_bytes)))
    except Exception:
        destroy()

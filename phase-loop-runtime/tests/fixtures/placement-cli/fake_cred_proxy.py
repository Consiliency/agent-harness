"""A behavioural fake of agent-toolkit's credential proxy (``harnesses/pi/sandbox/cred-proxy.mjs``
at Consiliency/agent-toolkit commit 9304a5b92c8c409473ca3d2182557b8592697476), for placement
bridge tests. It is defined by behaviour, not by the Node source:

* a request for ``/<provider>/<path>`` goes to that provider's allowlisted origin with the
  real credential; any other route is refused;
* the guest's placeholder credential headers (``authorization``, ``x-api-key`` ...) never
  reach the provider, and the real credential never travels back toward the guest;
* it never logs headers, credentials or bodies.

The guest side holds placeholders only. Here the "provider" is an in-process callable, so
no network is used.
"""

from __future__ import annotations

from typing import Callable

STRIPPED = {"authorization", "x-api-key", "api-key", "proxy-authorization", "cookie", "host",
            "connection"}


def parse(raw: bytes) -> tuple[str, str, dict[str, str], bytes]:
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    method, path, _version = lines[0].split(" ", 2)
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return method, path, headers, body


def handle(raw: bytes, routes: dict[str, str], credentials: Callable[[str], str],
           provider: Callable[[str, str, dict[str, str], bytes], bytes]) -> bytes:
    """One request from the guest, answered without ever echoing the credential."""
    method, path, headers, body = parse(raw)
    name = path.split("/", 2)[1] if path.startswith("/") else ""
    if name not in routes or method == "CONNECT":
        return b"HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"
    upstream_path = "/" + path.split("/", 2)[2] if path.count("/") >= 2 else "/"
    forwarded = {k: v for k, v in headers.items() if k not in STRIPPED}
    forwarded["authorization"] = "Bearer " + credentials(name)
    answer = provider(routes[name], upstream_path, forwarded, body)
    secret = credentials(name).encode()
    answer = answer.replace(secret, b"[redacted]")
    return (b"HTTP/1.1 200 OK\r\ncontent-length: " + str(len(answer)).encode()
            + b"\r\nconnection: close\r\n\r\n" + answer)

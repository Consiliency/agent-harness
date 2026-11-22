"""GROK SL-1: the jailed Grok seat adopts the ``grok-review`` allow-list offline
(IF-0-GROK-1 "Egress"; plans/artifacts/grok-jail-tool-surface-contract-v1.md section 9).

No allow-list file is added or edited. The positive control and the refusals run through
the real ``start_proxy`` and the real ``proxy.mjs``: first over a stand-in srt that hands the
proxy's ``filterRequest`` to the test (needs only node), then over the pinned srt with every
port-443 dial sent to a loopback fixture upstream (skips where the egress layer is absent).
No test contacts a vendor or runs ``grok``.
"""

from __future__ import annotations

import ast
import base64
import inspect
import json
from pathlib import Path
import socket
import types
import urllib.parse

import pytest

from phase_loop_runtime import (
    seat_admission, seat_egress_proxy, seat_jail, seat_route, seat_route_contract,
    seat_window,
)
from tests.test_grok_measure_egress import (  # the L2a harness, reused unedited
    CODEX_ALLOWLIST_DIGEST, GEMINI_ALLOWLIST_DIGEST, GROK_REVIEW_ALLOWLIST_DIGEST,
    INFERENCE_HOST, INFERENCE_PATH, _exchange, _http, _read_head, fake_srt,
    real_proxy_upstream,
)

__all__ = ["fake_srt", "real_proxy_upstream"]  # fixtures, used by name below

GROK_REVIEW = "grok-review"
EXPECTED_DIGESTS = {"codex": CODEX_ALLOWLIST_DIGEST, "gemini": GEMINI_ALLOWLIST_DIGEST,
                    GROK_REVIEW: GROK_REVIEW_ALLOWLIST_DIGEST}


def _hosts(allowlist_id: str) -> list[str]:
    document = seat_egress_proxy.allowlist(allowlist_id)
    hosts = {rule["host"] for rule in document["allow"]}
    hosts.update(host for host in document["measured_and_refused"] if "*" not in host)
    return sorted(hosts)


def _refused_urls() -> list[tuple[str, str, str]]:
    rows = [("unlisted", "POST", "https://seat-egress-unlisted.invalid" + INFERENCE_PATH),
            ("unlisted-path", "POST", f"https://{INFERENCE_HOST}/v1/responses"),
            ("unlisted-method", "GET", f"https://{INFERENCE_HOST}{INFERENCE_PATH}"),
            ("settings", "GET", f"https://{INFERENCE_HOST}/v1/settings"),
            ("sign-in", "POST", "https://auth.x.ai/oauth2/token")]
    for vendor in ("gemini", "codex"):
        rows.extend((vendor, "POST", f"https://{host}/") for host in _hosts(vendor))
    return rows


# --------------------------------------------------------------------------------------
# The allow-lists do not move, and nothing requires allowlist_id == leg.
# --------------------------------------------------------------------------------------

def test_every_allowlist_digest_equals_its_base_value():
    for allowlist_id, digest in EXPECTED_DIGESTS.items():
        assert seat_egress_proxy.allowlist_ref(allowlist_id).content_digest == digest


def test_no_allowlist_file_is_added_for_the_grok_leg():
    names = sorted(path.name for path in
                   seat_egress_proxy._data_path("codex-allowlist.json").parent
                   .glob("*-allowlist.json"))
    assert names == ["codex-allowlist.json", "gemini-allowlist.json",
                     "grok-review-allowlist.json"]
    with pytest.raises(seat_egress_proxy.EgressLayerUnavailable):
        seat_egress_proxy.allowlist("grok")


def test_the_admission_egress_rung_binds_grok_review_for_the_grok_leg(monkeypatch):
    """L7 takes the profile's id, never the leg: a ``grok`` profile naming ``grok-review``
    binds that allow-list's digest."""
    monkeypatch.setattr(seat_egress_proxy, "unavailable_code", lambda: None)
    profile = types.SimpleNamespace(leg="grok", vendor="grok", allowlist_id=GROK_REVIEW)
    verdict, digest = seat_admission._profile_egress("grok", profile, True)
    assert verdict is None
    assert digest == GROK_REVIEW_ALLOWLIST_DIGEST


def _names(node: ast.AST) -> set[str]:
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


@pytest.mark.parametrize("module", [seat_admission, seat_egress_proxy, seat_jail, seat_route,
                                    seat_route_contract, seat_window])
def test_no_consumer_compares_an_allowlist_id_with_a_leg_or_vendor(module):
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            names = _names(node)
            assert not ("allowlist_id" in names and names & {"leg", "vendor"}), (
                module.__name__, ast.unparse(node))


# --------------------------------------------------------------------------------------
# The real proxy.mjs over a stand-in srt (node only).
# --------------------------------------------------------------------------------------

def test_the_real_proxy_script_allows_only_the_inference_row(fake_srt):
    fake = fake_srt()
    refused = _refused_urls()
    with seat_egress_proxy.start_proxy(allowlist_id=GROK_REVIEW) as proxy:
        assert proxy.allowlist_id == GROK_REVIEW
        assert proxy.allowlist_digest == GROK_REVIEW_ALLOWLIST_DIGEST
        verdicts = fake.decide(
            [{"method": "POST", "url": f"https://{INFERENCE_HOST}{INFERENCE_PATH}"}]
            + [{"method": method, "url": url} for _label, method, url in refused])
    assert verdicts[0] == "allow"
    assert dict(zip((label + " " + url for label, _m, url in refused), verdicts[1:])) == {
        label + " " + url: "deny" for label, _m, url in refused}
    configured = json.loads(fake.config_copy.read_text(encoding="utf-8"))
    assert configured["allow"] == list(seat_egress_proxy.allowlist_ref(GROK_REVIEW).request_set)


# --------------------------------------------------------------------------------------
# The real proxy over the pinned srt, against a loopback fixture upstream.
# --------------------------------------------------------------------------------------

def test_an_allowed_inference_request_reaches_the_fixture_upstream(real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id=GROK_REVIEW) as proxy:
        assert proxy.allowlist_digest == GROK_REVIEW_ALLOWLIST_DIGEST
        status, reply = _exchange(proxy, INFERENCE_HOST,
                                  _http("POST", INFERENCE_HOST, INFERENCE_PATH))
    assert status.startswith(b"HTTP/1.1 200"), status
    assert reply.startswith(b"HTTP/1.1 200"), reply[:120]
    assert upstream.requests == [(INFERENCE_HOST, "POST", INFERENCE_PATH, INFERENCE_HOST)]


@pytest.mark.parametrize("label,host", [("unlisted", "seat-egress-unlisted.invalid")]
                         + [("gemini", host) for host in _hosts("gemini")]
                         + [("codex", host) for host in _hosts("codex")]
                         + [("sign-in", "auth.x.ai"), ("sign-in", "accounts.x.ai")])
def test_an_unlisted_or_other_vendor_host_is_refused(label, host, real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id=GROK_REVIEW) as proxy:
        status, reply = _exchange(proxy, host, _http("POST", host, "/"))
    assert status.startswith(b"HTTP/1.1 403"), (label, status)
    assert reply == b"" and upstream.connections == 0


def test_a_listed_host_on_an_unlisted_path_is_refused(real_proxy_upstream):
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id=GROK_REVIEW) as proxy:
        status, reply = _exchange(proxy, INFERENCE_HOST,
                                  _http("POST", INFERENCE_HOST, "/v1/responses"))
    assert status.startswith(b"HTTP/1.1 200"), status
    assert reply.startswith(b"HTTP/1.1 403"), reply[:120]
    assert upstream.requests == []


def _direct(proxy, request: bytes) -> bytes:
    raw = socket.socket(socket.AF_UNIX)
    raw.settimeout(20)
    raw.connect(proxy.socket)
    try:
        raw.sendall(request)
        return _read_head(raw).split(b"\r\n", 1)[0]
    finally:
        raw.close()


def test_a_direct_connection_is_refused(real_proxy_upstream):
    """A request that is not an authenticated tunnel never reaches the upstream: a plain
    origin-form request, and a tunnel without the proxy's session credential."""
    upstream = real_proxy_upstream
    with seat_egress_proxy.start_proxy(allowlist_id=GROK_REVIEW) as proxy:
        plain = _direct(proxy, (f"POST https://{INFERENCE_HOST}{INFERENCE_PATH} HTTP/1.1\r\n"
                                f"Host: {INFERENCE_HOST}\r\nContent-Length: 0\r\n\r\n").encode())
        token = urllib.parse.urlsplit(proxy.proxy_url).password
        wrong = base64.b64encode(("srt:" + "x" * len(token or "")).encode())
        unauthenticated = _direct(proxy, (
            f"CONNECT {INFERENCE_HOST}:443 HTTP/1.1\r\nHost: {INFERENCE_HOST}:443\r\n"
            "\r\n").encode())
        forged = _direct(proxy, (
            f"CONNECT {INFERENCE_HOST}:443 HTTP/1.1\r\nHost: {INFERENCE_HOST}:443\r\n"
            "Proxy-Authorization: Basic ").encode() + wrong + b"\r\n\r\n")
    for status in (plain, unauthenticated, forged):
        assert not status.startswith(b"HTTP/1.1 200"), status
    assert upstream.connections == 0 and upstream.requests == []



# --------------------------------------------------------------------------------------
# plans/evidence/seat-grok/containment.json: ids and digests only.
# --------------------------------------------------------------------------------------

_CONTAINMENT = (Path(__file__).resolve().parents[2] / "plans" / "evidence" / "seat-grok"
                / "containment.json")


def test_the_containment_record_holds_ids_and_current_digests():
    if not _CONTAINMENT.is_file():
        pytest.skip("plans/evidence/ is absent from this checkout")
    from phase_loop_runtime import seat_grok_credential

    record = json.loads(_CONTAINMENT.read_text(encoding="utf-8"))
    by_id = {item["evidence_id"]: item for item in record["evidence"]}
    assert set(by_id) == {"grok-refresh-detection", "grok-unlisted-refusal"}
    assert by_id["grok-refresh-detection"]["expected_code"] == \
        seat_grok_credential.REFRESHED_IN_JAIL
    refusal = by_id["grok-unlisted-refusal"]
    assert refusal["allowlist_id"] == GROK_REVIEW
    assert refusal["allowlist_sha256"] == GROK_REVIEW_ALLOWLIST_DIGEST
    assert refusal["unmoved_allowlist_sha256"] == {"codex": CODEX_ALLOWLIST_DIGEST,
                                                   "gemini": GEMINI_ALLOWLIST_DIGEST}
    assert record["seat_config_sha256"] == seat_grok_credential.SEAT_CONFIG_SHA256
    tests = Path(__file__).parent
    for item in record["evidence"]:
        assert item["provider_turns"] == 0
        for selector in item["proven_by"]:
            path, _, name = selector.partition("::")
            assert f"def {name}(" in (tests / Path(path).name).read_text(encoding="utf-8")

"""v13 PLACECLI SL-0: the packaged placement process protocol v1 and its strict codec.

Every negative enters through the production decoder (``decode_request`` or
``decode_response``), never a schema call of the test's own, and the packaged bytes are
compared with the frozen planning artifact itself, so a changed package copy cannot be
hidden by updating an expectation here.
"""

from __future__ import annotations

import copy
from hashlib import sha256
from importlib import resources
import json
from pathlib import Path

import pytest

from phase_loop_runtime import placement_process_contract as contract

REPO = Path(__file__).resolve().parents[2]
ARTIFACT = REPO / "plans/artifacts/v13-PLACECLI-contract-v1.schema.json"
#: The roadmap and binding pin of the protocol artifact (an input, never an output).
PINNED_SHA256 = "130a894df327ddca2eebf83c8b52e068b25176320af3e0a4e15319a315ba83ea"
PREVIOUS_SHA256 = "7bf7781dd30de55e7b30200d70f6b90b49a7c7a9b73804892408fa7667181105"
DIGEST = "sha256:" + "a" * 64
HEX = "b" * 64


def reserve_request(**changes):
    body = {
        "schema": "placement.reserve.request.v1", "request_id": "req-1", "workload": "pi-runner",
        "ttl_s": 600, "image_digest": DIGEST, "policy_vector": "full-remote-pi-runner",
        "providers": ["anthropic", "openai"], "deadline_ms": 900000,
        "caller_context": {"run": "r-1", "attempt": 2, "dry": False, "note": None},
    }
    body.update(changes)
    return body


def reservation(**changes):
    body = {
        "schema": "placement.reservation.v1", "reservation_id": "rsv-1", "workload": "pi-runner",
        "target": {"name": "ai", "kind": "openshell", "rank": 0}, "transport_id": "ai-openshell",
        "image_digest": DIGEST, "policy_vector": "full-remote-pi-runner", "policy_digest": DIGEST,
        "providers": ["anthropic"], "egress_sha256": DIGEST, "client": "agent-toolkit",
        "inventory": "agent-toolkit", "rank_policy": "agent_executor", "lease_id": "lease-1",
        "expires_at": "2026-11-09T18:00:00Z", "config_sha256": HEX,
        "bridge": {"kind": "forward_tcp_unix", "service_name": "pi-link",
                   "socket_path": "/run/user/1000/agent-harness-placement/agent-toolkit/rsv-1/s",
                   "directory_mode": "0700", "socket_mode": "0600", "lifetime": "reservation"},
    }
    body.update(changes)
    return body


def local_reservation(**changes):
    return reservation(target={"name": "local", "kind": "local", "rank": 1},
                       transport_id="local", policy_vector="minimal-without-app", lease_id=None,
                       bridge=None, **changes)


def release_request(**changes):
    body = {"schema": "placement.release.request.v1", "request_id": "rel-1",
            "reservation": reservation(), "deadline_ms": 30000, "caller_context": {}}
    body.update(changes)
    return body


def reap_request(**changes):
    body = {"schema": "placement.reap.request.v1", "request_id": "reap-1",
            "scope": "caller_inventory", "deadline_ms": 30000, "max_items": 10,
            "caller_context": {}}
    body.update(changes)
    return body


FLAGS = {"reserved": False, "create_settled": True, "ready": False, "exec_claimed": False,
         "fenced": True, "destruction_observed": True, "cleanup_pending": False,
         "barrier_confirmed": True, "expired": False}
HEADROOM = {"memory_available_bytes_minimum_floor": 4294967296,
            "memory_available_total_ram_fraction_minimum": 0.1,
            "load_per_cpu_percent_maximum_exclusive": 70,
            "io_pressure_full_avg10_percent_maximum_exclusive": 10,
            "memory_pressure_some_avg10_percent_maximum_exclusive": 10,
            "live_sandboxes_maximum_exclusive": 4, "observation_age_seconds_maximum": 5}


def reserve_response(**changes):
    body = {"schema": "placement.reserve.response.v1", "request_id": "req-1",
            "outcome": "admitted", "code": None, "reason": None, "reservation": reservation(),
            "trail": [{"target": "ai", "outcome": "admitted", "code": None, "reason": None}],
            "caller_context": {}}
    body.update(changes)
    return body


def release_response(**changes):
    body = {"schema": "placement.release.response.v1", "request_id": "rel-1",
            "reservation_id": "rsv-1", "state": "released", "code": None, "flags": dict(FLAGS),
            "caller_context": {}}
    body.update(changes)
    return body


def reap_response(**changes):
    body = {"schema": "placement.reap.response.v1", "request_id": "reap-1", "state": "complete",
            "inventories": [{"client": "agent-toolkit", "inventory": "agent-toolkit",
                             "examined": 0, "destroyed": 0, "pending": 0, "code": None}],
            "caller_context": {}}
    body.update(changes)
    return body


def version_response(**changes):
    body = {"schema": "placement.version.response.v1", "client": "agent-toolkit",
            "protocol_schema_sha256": PINNED_SHA256, "config_sha256": HEX,
            "local_headroom": dict(HEADROOM)}
    body.update(changes)
    return body


def raw(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def line(value) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


def refused(verb: str, data: bytes) -> str:
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_request(verb, data)
    assert str(caught.value) in contract.PROTOCOL_DIAGNOSTICS
    return caught.value.code


@pytest.fixture(autouse=True)
def no_ambient_depth_setting(monkeypatch):
    """The decoders read the nesting setting on every call; no ambient value reaches a test."""
    monkeypatch.delenv(contract.MAX_INPUT_DEPTH_ENV, raising=False)


def response_refused(verb: str, value) -> None:
    with pytest.raises(contract.ProtocolError):
        contract.decode_response(verb, line(value))


# -- the packaged bytes ---------------------------------------------------------------------

def test_the_packaged_schema_is_read_through_importlib_resources():
    packaged = resources.files("phase_loop_runtime").joinpath(
        "contracts/placement/process-v1.schema.json").read_bytes()
    assert packaged == contract.schema_bytes()
    assert contract.protocol_schema_sha256() == sha256(packaged).hexdigest()


@pytest.mark.skipif(not ARTIFACT.is_file(), reason="planning artifact absent in standalone clean-room")
def test_the_packaged_bytes_are_the_frozen_artifact_at_its_pin():
    frozen = ARTIFACT.read_bytes()
    # Equal to the artifact itself, and the artifact is at its roadmap pin: changing the
    # package copy and an expectation here together still fails one of the two.
    assert contract.schema_bytes() == frozen
    assert sha256(frozen).hexdigest() == PINNED_SHA256
    assert contract.protocol_schema_sha256() == PINNED_SHA256


def test_the_wire_identity_differs_from_the_pre_erratum_bytes():
    assert contract.protocol_schema_sha256() != PREVIOUS_SHA256
    document = json.loads(contract.schema_bytes())
    assert document["x-errata"]["entries"][0]["previous_sha256"] == PREVIOUS_SHA256


# -- valid examples for every message family -----------------------------------------------

@pytest.mark.parametrize("verb,body", [
    ("reserve", reserve_request()),
    ("reserve", reserve_request(workload="leg", policy_vector="minimal-with-app")),
    ("release", release_request()),
    ("release", release_request(reservation=local_reservation())),
    ("reap", reap_request()),
])
def test_valid_requests_decode_to_immutable_records(verb, body):
    record = contract.decode_request(verb, raw(body))
    assert record.to_json() == body
    with pytest.raises(Exception):
        record.request_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.caller_context["x"] = 1  # type: ignore[index]


@pytest.mark.parametrize("verb,body", [
    ("reserve", reserve_response()),
    ("reserve", reserve_response(outcome="at_capacity", code="sandbox_placement_at_capacity",
                                 reason="no_capacity", reservation=None,
                                 trail=[{"target": "ai", "outcome": "at_capacity",
                                         "code": "sandbox_placement_at_capacity",
                                         "reason": "no_capacity"}])),
    ("reserve", reserve_response(reservation=local_reservation(),
                                 trail=[{"target": "local", "outcome": "admitted", "code": None,
                                         "reason": None}])),
    ("release", release_response()),
    ("release", release_response(state="cleanup_pending", code="sandbox_placement_release_unconfirmed",
                                 flags={**FLAGS, "cleanup_pending": True, "barrier_confirmed": False})),
    ("release", release_response(state="unknown_reservation", code="sandbox_placement_refused",
                                 flags={**FLAGS, "reserved": False})),
    ("release", release_response(state="rejected", code="sandbox_placement_refused")),
    ("reap", reap_response()),
    ("version", version_response()),
])
def test_valid_responses_round_trip_byte_for_byte(verb, body):
    data = line(body)
    record = contract.decode_response(verb, data)
    assert contract.encode_response(record) == data
    assert contract.exit_class(record) in (0, 10, 20)


def test_the_exit_classes_follow_x_cli():
    decoded = {
        ("reserve", "admitted"): contract.decode_response("reserve", line(reserve_response())),
        ("reserve", "timeout"): contract.decode_response("reserve", line(reserve_response(
            outcome="timeout", code="sandbox_placement_operation_timeout", reservation=None,
            trail=[{"target": "ai", "outcome": "timeout",
                    "code": "sandbox_placement_operation_timeout", "reason": None}]))),
        ("release", "cleanup_pending"): contract.decode_response("release", line(release_response(
            state="cleanup_pending", code="sandbox_placement_release_unconfirmed",
            flags={**FLAGS, "cleanup_pending": True, "barrier_confirmed": False}))),
    }
    assert contract.exit_class(decoded[("reserve", "admitted")]) == 0
    assert contract.exit_class(decoded[("reserve", "timeout")]) == 20
    assert contract.exit_class(decoded[("release", "cleanup_pending")]) == 20
    assert contract.exit_class(contract.decode_response("version", line(version_response()))) == 0


# -- input rules -----------------------------------------------------------------------------

@pytest.mark.parametrize("data,code", [
    (b'{"schema":"placement.reap.request.v1","schema":"placement.reap.request.v1"}', "input_duplicate_key"),
    (raw(reap_request()) + b" {}", "input_trailing_data"),
    (raw(reap_request()) + b"x", "input_trailing_data"),
    (b"\xff\xfe{}", "input_not_utf8"),
    ("﻿".encode() + raw(reap_request()), "input_not_utf8"),
    (b'{"a":"\\ud800"}', "input_not_utf8"),
    (b'{"deadline_ms":NaN}', "input_non_finite_number"),
    (b'{"deadline_ms":Infinity}', "input_non_finite_number"),
    (b'{"deadline_ms":-Infinity}', "input_non_finite_number"),
    (b'{"deadline_ms":1e999}', "input_non_finite_number"),
    (b'{"deadline_ms":9007199254740992}', "input_unsafe_number"),
    (b'{"deadline_ms":-9007199254740992}', "input_unsafe_number"),
    (b"[]", "input_not_object"),
    (b"", "input_invalid_json"),
    (b"{", "input_invalid_json"),
    (b"[" * 40000 + b"]" * 40000, "input_too_large"),
    (b"[" * 30000 + b"]" * 30000, "input_invalid_json"),
])
def test_input_rule_breaches_refuse_before_schema(data, code):
    assert refused("reap", data) == code


def test_the_64_kib_bound_is_exact():
    body = raw(reap_request())
    padded = body + b" " * (contract.MAX_INPUT_BYTES - len(body))
    assert len(padded) == contract.MAX_INPUT_BYTES
    assert contract.decode_request("reap", padded).request_id == "reap-1"
    assert refused("reap", padded + b" ") == "input_too_large"


def nested(depth: int) -> bytes:
    """A JSON object whose arrays and objects nest exactly ``depth`` deep."""
    return b'{"a":' * (depth - 1) + b"{}" + b"}" * (depth - 1)


def test_the_nesting_bound_is_exact():
    limit = contract.MAX_INPUT_DEPTH
    assert refused("reap", nested(limit)) == "schema_invalid"  # past the input rules
    assert refused("reap", nested(limit + 1)) == "input_invalid_json"
    response = b'{"a":' * (limit - 1) + b"{}" + b"}" * (limit - 1)
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_response("reap", response + b"\n")
    assert caught.value.code == "schema_invalid"
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_response("reap", b'{"a":' + response + b"}\n")
    assert caught.value.code == "input_invalid_json"
    arrays = b"[" * limit + b"]" * limit  # inside one object: limit + 1 deep
    assert refused("reap", b'{"a":' + arrays[1:-1] + b"}") == "schema_invalid"
    assert refused("reap", b'{"a":' + arrays + b"}") == "input_invalid_json"
    assert refused("reap", b"[]" + b"[" * (limit + 1)) == "input_trailing_data"


def test_brackets_inside_strings_do_not_count_toward_the_nesting_bound():
    note = "[" * 100 + '\\"' + "{" * 100 + "\\"  # an escaped quote, then a final escaped backslash
    decoded = contract.decode_request("reap", raw(reap_request(caller_context={"note": note})))
    assert decoded.caller_context == {"note": note}
    closers = json.dumps("]" * 100 + '\\"' + "}" * 100 + "\\").encode()
    deep = b"[" * contract.MAX_INPUT_DEPTH + b"]" * contract.MAX_INPUT_DEPTH
    assert refused("reap", b'{"a":' + closers + b',"b":' + deep + b"}") == "input_invalid_json"
    assert refused("reap", b'{"a":' + closers + b',"b":' + deep[1:-1] + b"}") == "schema_invalid"


def test_the_nesting_bound_is_for_wire_messages_not_the_strict_object_parser():
    """``load_strict_object`` also parses client configurations, whose opaque ``launch``
    object has no depth bound, so it keeps accepting nesting the wire decoders refuse."""
    for depth in (contract.MAX_INPUT_DEPTH + 1, 200):
        assert isinstance(contract.load_strict_object(nested(depth)), dict)
        assert refused("reap", nested(depth)) == "input_invalid_json"
    with pytest.raises(contract.ProtocolError) as caught:  # beyond what can be decoded or walked
        contract.load_strict_object(b'{"a":' + b"[" * 30000 + b"]" * 30000 + b"}")
    assert caught.value.code == "input_invalid_json"


def deep_launch(depth: int) -> dict:
    launch: dict = {}
    for _ in range(depth):
        launch = {"x": launch}
    return launch


def test_a_deep_opaque_launch_object_is_still_an_accepted_client_configuration(tmp_path):
    from phase_loop_runtime import sandbox_policy

    root = tmp_path / "placement"
    root.mkdir(mode=0o700)
    for depth in (contract.MAX_INPUT_DEPTH, 200):
        launch = deep_launch(depth)
        path = root / "agent-toolkit.json"
        path.write_text(json.dumps({"schema": "placement.client-config.v1",
                                    "client": "agent-toolkit", "launch": launch}))
        path.chmod(0o600)
        config = sandbox_policy.load_placement_client_config(
            "agent-toolkit", config_root=root, seat_caps_sha256="0" * 64)
        assert config.launch == launch
        assert json.loads(config.canonical)["launch"] == launch
    # The same object on the wire is refused by the decoder's nesting safeguard.
    assert refused("reserve", raw(reserve_request(launch=deep_launch(contract.MAX_INPUT_DEPTH)))) \
        == "input_invalid_json"


def test_a_deep_value_takes_precedence_over_other_input_rules_on_the_wire():
    """The nesting check runs before decoding, so a deep value that also breaks another
    input rule reports ``input_invalid_json``; the strict object parser reports the other."""
    deep = b"[" * (contract.MAX_INPUT_DEPTH + 1) + b"]" * (contract.MAX_INPUT_DEPTH + 1)
    for first, code in ((b'"x":NaN', "input_non_finite_number"),
                        (b'"x":9007199254740992', "input_unsafe_number"),
                        (b'"x":{"k":1,"k":2}', "input_duplicate_key")):
        data = b"{" + first + b',"y":' + deep + b"}"
        assert refused("reap", data) == "input_invalid_json"
        with pytest.raises(contract.ProtocolError) as caught:
            contract.load_strict_object(data)
        assert caught.value.code == code


@pytest.mark.parametrize("data,code", [
    pytest.param(b'{"a":[1,2}', "input_invalid_json", id="mismatched-closer"),
    pytest.param(b'{"a":1]}', "input_invalid_json", id="extra-closer"),
    pytest.param(b"]", "input_invalid_json", id="lone-closer"),
    pytest.param(b'{"a":"\\x"}', "input_invalid_json", id="invalid-escape"),
    pytest.param(b'{"a":"\\u12"}', "input_invalid_json", id="short-unicode-escape"),
    pytest.param(b'{"a":"abc', "input_invalid_json", id="unterminated-string"),
    pytest.param(b'{"a":"\\"}', "input_invalid_json", id="escaped-final-quote"),
    pytest.param(b'{"a":tru}', "input_invalid_json", id="invalid-literal"),
    pytest.param(b'{"a":"\\\\"}', "schema_invalid", id="escaped-backslash"),
    pytest.param(b'{"a":"\\""}', "schema_invalid", id="escaped-quote"),
    pytest.param(b'{"a":"\\u005b]]]"}', "schema_invalid", id="unicode-escaped-bracket"),
    pytest.param(b'{"a":"]]]}}}"}', "schema_invalid", id="closers-in-string"),
    pytest.param(b"{}]", "input_trailing_data", id="trailing-closer"),
    pytest.param(b'{} "x"', "input_trailing_data", id="trailing-string"),
    pytest.param(b"{} 1", "input_trailing_data", id="trailing-number"),
    pytest.param(b'"[[[["', "input_not_object", id="top-level-string"),
    pytest.param(b"1", "input_not_object", id="top-level-number"),
])
def test_shallow_malformed_input_keeps_its_decoder_classification(data, code):
    assert refused("reap", data) == code
    if code == "schema_invalid":
        assert isinstance(contract.load_strict_object(data), dict)
    else:
        with pytest.raises(contract.ProtocolError) as caught:
            contract.load_strict_object(data)
        assert caught.value.code == code


# -- the nesting-limit setting ----------------------------------------------------------------

def refused_response(verb: str, data: bytes) -> str:
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_response(verb, data)
    assert str(caught.value) in contract.PROTOCOL_DIAGNOSTICS
    return caught.value.code


def nested_arrays(depth: int) -> bytes:
    """A JSON object holding arrays, nesting exactly ``depth`` deep in total."""
    return b'{"a":' + b"[" * (depth - 1) + b"]" * (depth - 1) + b"}"


def schema_depth(node, defs, seen=()) -> int:
    """The deepest array/object nesting a value valid under ``node`` can have."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        assert name not in seen, "a recursive definition has no depth bound"
        return schema_depth(defs[name], defs, (*seen, name))
    best = max((schema_depth(sub, defs, seen) for key in ("oneOf", "anyOf", "allOf")
                for sub in node.get(key, ())), default=0)
    kinds = node.get("type") if isinstance(node.get("type"), list) else [node.get("type")]
    if "object" in kinds or "properties" in node:
        assert node.get("additionalProperties", True) is not True, "an open object"
        extra = node.get("additionalProperties")
        members = [*node.get("properties", {}).values(), *([extra] if isinstance(extra, dict) else [])]
        best = max(best, 1 + max((schema_depth(m, defs, seen) for m in members), default=0))
    if "array" in kinds or "items" in node:
        items = node.get("items")
        best = max(best, 1 + (schema_depth(items, defs, seen) if isinstance(items, dict) else 0))
    return best


def test_the_nesting_setting_is_one_named_environment_variable_with_a_closed_range():
    assert contract.MAX_INPUT_DEPTH_ENV == "PHASE_LOOP_PLACEMENT_MAX_INPUT_DEPTH"
    assert contract.MAX_INPUT_DEPTH == 64
    assert contract.MAX_INPUT_DEPTH_SETTING_RANGE == (3, 256)
    assert contract.input_depth_limit() == 64  # unset: the default


def test_the_setting_minimum_is_the_deepest_schema_valid_message(monkeypatch):
    """No accepted setting can refuse a schema-valid request or response."""
    schema = json.loads(contract.schema_bytes())
    deepest = max(schema_depth(schema["$defs"][name], schema["$defs"]) for name in (
        "ReserveRequest", "ReleaseRequest", "ReapRequest", "ReserveResponse", "ReleaseResponse",
        "ReapResponse", "VersionResponse"))
    low = contract.MAX_INPUT_DEPTH_SETTING_RANGE[0]
    assert deepest == low == 3
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, str(low))
    assert contract.decode_request("release", raw(release_request())).to_json() == release_request()
    for verb, body in (("reserve", reserve_response()), ("release", release_response()),
                       ("reap", reap_response()), ("version", version_response())):
        assert contract.encode_response(contract.decode_response(verb, line(body))) == line(body)
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, str(low - 1))  # below the range
    assert refused("release", raw(release_request())) == "input_invalid_json"


@pytest.mark.parametrize("setting", [None, "3", "4", "17", "64", "255", "256"])
def test_a_selected_limit_is_exact_for_requests_and_responses(monkeypatch, setting):
    if setting is not None:
        monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, setting)
    limit = contract.MAX_INPUT_DEPTH if setting is None else int(setting)
    assert contract.input_depth_limit() == limit
    for make in (nested, nested_arrays):
        assert refused("reap", make(limit)) == "schema_invalid"  # at the limit: past the input rules
        assert refused("reap", make(limit + 1)) == "input_invalid_json"  # one over: refused
        assert refused_response("reap", make(limit) + b"\n") == "schema_invalid"
        assert refused_response("reap", make(limit + 1) + b"\n") == "input_invalid_json"


def test_the_largest_setting_still_decodes_input_at_the_limit_from_a_deep_caller(monkeypatch):
    """The maximum leaves recursion headroom: input exactly at it is decoded and walked, not
    refused through a ``RecursionError``, even from 200 frames down (on 3.12 and 3.14 the walk
    takes two frames per level, so a maximum of 512 would fail here at any caller depth)."""
    high = contract.MAX_INPUT_DEPTH_SETTING_RANGE[1]
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, str(high))

    def from_depth(frames: int) -> str:
        return from_depth(frames - 1) if frames else refused("reap", nested(high))

    assert from_depth(200) == "schema_invalid"
    assert refused("reap", nested_arrays(high)) == "schema_invalid"


INVALID_SETTINGS = [
    pytest.param("", id="empty"),
    pytest.param("abc", id="non-numeric"),
    pytest.param("64abc", id="numeric-prefix"),
    pytest.param("-1", id="negative"),
    pytest.param("-64", id="negative-default"),
    pytest.param("0", id="zero"),
    pytest.param("1", id="below-minimum-1"),
    pytest.param("2", id="below-minimum-2"),
    pytest.param("257", id="above-maximum"),
    pytest.param("999", id="three-digits-above"),
    pytest.param("1000", id="four-digits"),
    pytest.param("18446744073709551616", id="huge"),
    pytest.param(" 64", id="leading-space"),
    pytest.param("64 ", id="trailing-space"),
    pytest.param("\t64", id="leading-tab"),
    pytest.param("64\n", id="trailing-newline"),
    pytest.param("+64", id="leading-plus"),
    pytest.param("6_4", id="underscore"),
    pytest.param("064", id="leading-zero"),
    pytest.param("0x40", id="hex"),
    pytest.param("64.0", id="decimal-point"),
    pytest.param("1e2", id="exponent"),
    pytest.param("\u0666\u0664", id="arabic-indic-digits"),  # int() accepts these
    pytest.param("\uff16\uff14", id="fullwidth-digits"),
    pytest.param("1\u0664", id="mixed-script-digits"),  # an ASCII digit, then a non-ASCII one
]


@pytest.mark.parametrize("setting", INVALID_SETTINGS)
def test_an_invalid_setting_refuses_every_wire_input_and_never_falls_back(monkeypatch, setting):
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, setting)
    assert contract.input_depth_limit() is None
    # Valid messages, shallow ones and non-objects alike are refused, never decoded under 64.
    assert refused("reap", raw(reap_request())) == "input_invalid_json"
    assert refused("release", raw(release_request())) == "input_invalid_json"
    assert refused("reap", b"{}") == "input_invalid_json"
    assert refused("reap", b"1") == "input_invalid_json"
    assert refused_response("reap", line(reap_response())) == "input_invalid_json"
    assert refused_response("version", line(version_response())) == "input_invalid_json"
    # Checks that come before decoding keep their diagnostics; so does empty version input.
    assert refused("reap", b" " * (contract.MAX_INPUT_BYTES + 1)) == "input_too_large"
    assert refused("reap", b"\xff") == "input_not_utf8"
    assert refused_response("reap", line(reap_response())[:-1]) == "input_trailing_data"
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_request("bogus", raw(reap_request()))
    assert caught.value.code == "verb_unknown"
    assert contract.require_empty_version_input(b"") is None


@pytest.mark.parametrize("setting", ["3", "256", "", "garbage"])
def test_the_setting_never_applies_to_client_configurations(monkeypatch, tmp_path, setting):
    from phase_loop_runtime import sandbox_policy

    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, setting)
    for depth in (4, 257, 300):
        assert isinstance(contract.load_strict_object(nested(depth)), dict)
    root = tmp_path / "placement"
    root.mkdir(mode=0o700)
    launch = deep_launch(200)
    path = root / "agent-toolkit.json"
    path.write_text(json.dumps({"schema": "placement.client-config.v1",
                                "client": "agent-toolkit", "launch": launch}))
    path.chmod(0o600)
    config = sandbox_policy.load_placement_client_config(
        "agent-toolkit", config_root=root, seat_caps_sha256="0" * 64)
    assert config.launch == launch


@pytest.mark.parametrize("setting", [None, "256"])
def test_nesting_the_decoder_parses_but_the_walk_cannot_is_refused_not_raised(monkeypatch, setting):
    """1000 deep decodes on 3.12 and 3.14 alike but exhausts the recursive encodability walk;
    the strict parser refuses it as ``input_invalid_json`` instead of raising, whatever the
    setting, and the wire decoders refuse it before decoding."""
    if setting is not None:
        monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, setting)
    with pytest.raises(contract.ProtocolError) as caught:
        contract.load_strict_object(nested(1000))
    assert caught.value.code == "input_invalid_json"
    assert refused("reap", nested(1000)) == "input_invalid_json"


def test_the_setting_is_read_on_every_call(monkeypatch):
    assert refused("reap", nested(contract.MAX_INPUT_DEPTH + 1)) == "input_invalid_json"
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, "3")
    assert refused("reap", nested(4)) == "input_invalid_json"
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, "256")
    assert refused("reap", nested(contract.MAX_INPUT_DEPTH + 1)) == "schema_invalid"
    monkeypatch.setenv(contract.MAX_INPUT_DEPTH_ENV, "nonsense")
    assert refused("reap", raw(reap_request())) == "input_invalid_json"
    monkeypatch.delenv(contract.MAX_INPUT_DEPTH_ENV)
    assert contract.decode_request("reap", raw(reap_request())).max_items == 10
    assert refused("reap", nested(contract.MAX_INPUT_DEPTH + 1)) == "input_invalid_json"


def test_a_trailing_newline_is_whitespace_not_data():
    assert contract.decode_request("reap", raw(reap_request()) + b"\n").max_items == 10


def test_version_requires_empty_stdin():
    contract.require_empty_version_input(b"")
    with pytest.raises(contract.ProtocolError) as caught:
        contract.require_empty_version_input(b"{}")
    assert caught.value.code == "version_input_not_empty"


def test_an_unknown_verb_is_refused():
    assert refused("launch", raw(reap_request())) == "verb_unknown"
    assert refused("version", b"") == "verb_unknown"


# -- schema negatives, entered through the production decoder ------------------------------

def _without(body, key):
    body = copy.deepcopy(body)
    body.pop(key)
    return body


@pytest.mark.parametrize("mutate", [
    lambda b: {**b, "unknown": 1},
    lambda b: _without(b, "providers"),
    lambda b: {**b, "providers": []},
    lambda b: {**b, "providers": ["anthropic", "anthropic"]},
    lambda b: {**b, "providers": ["a"] * 17},
    lambda b: {**b, "providers": ["https://api.anthropic.com"]},
    lambda b: {**b, "providers": ["api.anthropic.com"]},
    lambda b: {**b, "providers": ["api.anthropic.com:443"]},
    lambda b: {**b, "providers": ["claude-3.5-sonnet"]},
    lambda b: {**b, "providers": ["anthropic/messages"]},
    lambda b: {**b, "providers": ["Anthropic"]},
    lambda b: {**b, "providers": [""]},
    lambda b: {**b, "workload": "shell"},
    lambda b: {**b, "policy_vector": "fork-era-network-shape"},
    lambda b: {**b, "policy_vector": "minimal-without-app"},  # pi-runner names the remote profile
    lambda b: {**b, "ttl_s": 0},
    lambda b: {**b, "ttl_s": 3601},
    lambda b: {**b, "ttl_s": 60.0},
    lambda b: {**b, "ttl_s": True},
    lambda b: {**b, "deadline_ms": 900001},
    lambda b: {**b, "image_digest": "a" * 64},
    lambda b: {**b, "image_digest": "sha256:" + "A" * 64},
    lambda b: {**b, "request_id": "-starts-with-dash"},
    lambda b: {**b, "request_id": "a" * 129},
    lambda b: {**b, "schema": "placement.reserve.request.v2"},
    lambda b: {**b, "caller_context": {"nested": {"x": 1}}},
    lambda b: {**b, "caller_context": {"list": [1]}},
    lambda b: {**b, "caller_context": {"f": 1.5}},
    lambda b: {**b, "caller_context": {"s": "x" * 513}},
    lambda b: {**b, "caller_context": {f"k{i}": i for i in range(17)}},
    lambda b: {**b, "caller_context": {"-bad": 1}},
    lambda b: {**b, "caller_context": {"big": 2 ** 53}},
    lambda b: {**b, "target": "ai"},
    lambda b: {**b, "owner": "someone"},
    lambda b: {**b, "egress": [{"host": "x", "port": 443}]},
    lambda b: _without(b, "caller_context"),
])
def test_reserve_negatives(mutate):
    assert refused("reserve", raw(mutate(reserve_request()))) in {"schema_invalid", "input_unsafe_number"}


@pytest.mark.parametrize("mutate", [
    lambda r: {**r, "providers": []},
    lambda r: {**r, "egress_sha256": "a" * 64},
    lambda r: {**r, "config_sha256": "sha256:" + "a" * 64},
    lambda r: {**r, "client": "agent-harness"},           # pi-runner is agent-toolkit's
    lambda r: {**r, "inventory": "agent-harness"},
    lambda r: {**r, "rank_policy": "seats_single_target"},
    lambda r: {**r, "bridge": None},                      # pi-runner on openshell has a bridge
    lambda r: {**r, "policy_vector": "minimal-with-app"},
    lambda r: {**r, "bridge": {**r["bridge"], "socket_mode": "0660"}},
    lambda r: {**r, "bridge": {**r["bridge"], "directory_mode": "0755"}},
    lambda r: {**r, "bridge": {**r["bridge"], "lifetime": "process"}},
    lambda r: {**r, "bridge": {**r["bridge"], "socket_path": "relative/s"}},
    lambda r: {**r, "target": {"name": "ai", "kind": "cloud", "rank": 0}},
    lambda r: {**r, "target": {"name": "ai", "kind": "openshell", "rank": 256}},
    lambda r: {**r, "expires_at": "tomorrow"},
    lambda r: {**r, "schema": "placement.reservation.v2"},
    lambda r: _without(r, "providers"),
])
def test_reservation_negatives_in_a_release_echo(mutate):
    assert refused("release", raw(release_request(reservation=mutate(reservation())))) == "schema_invalid"


@pytest.mark.parametrize("mutate", [
    lambda r: {**r, "bridge": reservation()["bridge"]},   # local has bridge null
    lambda r: {**r, "policy_vector": "full-remote-pi-runner"},
])
def test_local_pi_reservation_conditionals(mutate):
    assert refused("release", raw(release_request(reservation=mutate(local_reservation())))) == "schema_invalid"


def test_seat_reservations_are_agent_harness_and_single_target():
    seat = reservation(workload="qualification", client="agent-harness", inventory="agent-harness",
                       rank_policy="seats_single_target", bridge=None,
                       policy_vector="minimal-with-app")
    contract.decode_request("release", raw(release_request(reservation=seat)))
    for wrong in ({"client": "agent-toolkit"}, {"rank_policy": "agent_executor"},
                  {"bridge": reservation()["bridge"]}):
        assert refused("release", raw(release_request(reservation={**seat, **wrong}))) == "schema_invalid"
    leg = {**seat, "workload": "leg", "bridge": reservation()["bridge"]}
    contract.decode_request("release", raw(release_request(reservation=leg)))
    assert refused("release", raw(release_request(reservation={**leg, "bridge": None}))) == "schema_invalid"


@pytest.mark.parametrize("mutate", [
    lambda b: {**b, "scope": "all_inventories"},
    lambda b: {**b, "max_items": 0},
    lambda b: {**b, "max_items": 1001},
    lambda b: {**b, "deadline_ms": 30001},
    lambda b: {**b, "client": "agent-harness"},
])
def test_reap_negatives(mutate):
    assert refused("reap", raw(mutate(reap_request()))) == "schema_invalid"


# -- errata-1 obligation T1: the trail conditional --------------------------------------------

@pytest.mark.parametrize("code", ["sandbox_placement_at_capacity", "at_capacity"])
def test_t1_an_admitted_trail_entry_with_any_code_is_invalid(code):
    response_refused("reserve", reserve_response(
        trail=[{"target": "ai", "outcome": "admitted", "code": code, "reason": None}]))


def test_t1_a_non_admitted_trail_entry_needs_a_result_code():
    response_refused("reserve", reserve_response(
        outcome="refused", code="sandbox_placement_refused", reservation=None,
        trail=[{"target": "ai", "outcome": "refused", "code": None, "reason": None}]))
    response_refused("reserve", reserve_response(
        outcome="refused", code="sandbox_placement_refused", reservation=None,
        trail=[{"target": "ai", "outcome": "refused", "code": "seat_placement_waiting", "reason": None}]))
    contract.decode_response("reserve", line(reserve_response(
        outcome="refused", code="sandbox_placement_refused", reservation=None,
        trail=[{"target": "ai", "outcome": "refused", "code": "sandbox_placement_refused",
                "reason": None}])))


@pytest.mark.parametrize("mutate", [
    lambda b: {**b, "outcome": "admitted", "reservation": None},
    lambda b: {**b, "code": "sandbox_placement_refused"},
    lambda b: {**b, "trail": []},
    lambda b: {**b, "trail": b["trail"] * 17},
    lambda b: {**b, "outcome": "refused", "code": None, "reservation": None},
    lambda b: {**b, "outcome": "refused", "code": "sandbox_placement_refused"},
    lambda b: {**b, "reason": "bored"},
])
def test_reserve_response_conditionals(mutate):
    response_refused("reserve", mutate(reserve_response()))


@pytest.mark.parametrize("mutate", [
    lambda b: {**b, "state": "released", "flags": {**FLAGS, "cleanup_pending": True}},
    lambda b: {**b, "state": "released", "code": "sandbox_placement_refused"},
    lambda b: {**b, "state": "cleanup_pending", "code": "sandbox_placement_release_unconfirmed"},
    lambda b: {**b, "state": "unknown_reservation", "code": "sandbox_placement_release_unconfirmed"},
    lambda b: {**b, "state": "unknown_reservation", "code": "sandbox_placement_refused",
               "flags": {**FLAGS, "reserved": True}},
    lambda b: {**b, "state": "rejected", "code": "sandbox_placement_release_unconfirmed"},
    lambda b: {**b, "state": "rejected", "code": "at_capacity"},
    lambda b: {**b, "state": "gone"},
])
def test_release_response_conditionals(mutate):
    response_refused("release", mutate(release_response()))


def test_reap_and_version_response_conditionals():
    response_refused("reap", reap_response(inventories=[]))
    response_refused("reap", reap_response(inventories=reap_response()["inventories"] * 2))
    response_refused("reap", reap_response(inventories=[{**reap_response()["inventories"][0],
                                                         "inventory": "agent-harness"}]))
    response_refused("version", version_response(local_headroom={**HEADROOM, "extra": 1}))
    response_refused("version", version_response(protocol_schema_sha256="sha256:" + "a" * 64))
    response_refused("version", {k: v for k, v in version_response().items() if k != "local_headroom"})


def test_encode_refuses_a_record_that_breaks_the_schema():
    record = contract.decode_response("reserve", line(reserve_response()))
    from dataclasses import replace

    with pytest.raises(contract.ProtocolError) as caught:
        contract.encode_response(replace(record, code="sandbox_placement_refused"))
    assert caught.value.code == "response_invalid"


def test_a_diagnostic_never_carries_an_input_value():
    secret = "sk-ant-THIS-MUST-NOT-ECHO"
    with pytest.raises(contract.ProtocolError) as caught:
        contract.decode_request("reserve", raw(reserve_request(providers=[secret])))
    assert secret not in str(caught.value) and secret not in repr(caught.value.args)
    assert caught.value.__cause__ is None

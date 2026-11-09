"""Public codec witnesses against the independently pinned canonical corpus."""
from hashlib import sha256
import json
import math
import struct

import pytest

from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle
from phase_loop_runtime.supervised_envelope_v2 import canonicalize_v2, decode_v2, parse_v2

CORPUS = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.canonical.vectors.json"))


@pytest.mark.parametrize("case", CORPUS["domain"], ids=lambda case: case["id"])
def test_published_number_domain(case):
    raw = case["token"].encode()
    if case["accept"]:
        assert canonicalize_v2(parse_v2(raw).value) == case["canonical"].encode()
    else:
        with pytest.raises(ContractError, match="record_json_invalid"):
            parse_v2(raw)


@pytest.mark.parametrize("case", CORPUS["documents"], ids=lambda case: case["id"])
def test_published_documents(case):
    raw = bytes.fromhex(case["raw_hex"]) if "raw_hex" in case else case["raw"].encode()
    if case.get("reject"):
        with pytest.raises(ContractError, match="record_json_invalid"):
            parse_v2(raw)
    else:
        result = canonicalize_v2(parse_v2(raw).value)
        assert result == case["canonical"].encode()
        assert sha256(result).hexdigest() == case["sha256"]


@pytest.mark.parametrize("case", CORPUS["numbers"], ids=lambda case: case["id"])
def test_published_binary64_primitives(case):
    value = struct.unpack(">d", bytes.fromhex(case["bits"]))[0]
    if not math.isfinite(value) or (value.is_integer() and abs(value) > 9007199254740991):
        with pytest.raises(ContractError):
            canonicalize_v2(value)
    else:
        assert canonicalize_v2(value).decode() == case["canonical"]


@pytest.mark.parametrize("value", [9007199254740992, float("inf"), float("nan"), "\ud800", {1: "key"}, object()])
def test_in_memory_domain(value):
    with pytest.raises(ContractError) as caught:
        canonicalize_v2(value)
    assert caught.value.code == "record_json_invalid" and caught.value.__context__ is None


def test_decoding_keeps_raw_and_public_identity_separate():
    cases = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.vectors.json"))["cases"]
    envelope = cases[0]["input"]["envelope"]
    raw = json.dumps(envelope).encode()
    decoded = decode_v2(raw, bundle=load_contract_bundle(version="v2"))
    assert decoded.raw is raw
    assert decoded.public_digest == envelope["envelope_digest"]
    assert decoded.raw_digest == sha256(raw).hexdigest()
    with pytest.raises(TypeError):
        decoded.value["caller_context"]["changed"] = True

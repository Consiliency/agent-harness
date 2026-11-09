"""Tree commitment and held-capture boundary witnesses."""
from hashlib import sha256
import json

import pytest

from phase_loop_runtime.supervised_capture_v2 import _tree_manifest
from phase_loop_runtime.supervised_contracts import load_contract_bundle
from phase_loop_runtime.supervised_envelope_v2 import canonicalize_v2
from phase_loop_runtime.supervised_launch import _Refusal

CORPUS = json.loads(load_contract_bundle(version="v2").resource_bytes("conformance/envelope.v2.canonical.vectors.json"))


@pytest.mark.parametrize("case", CORPUS["tree_captures"], ids=lambda case: case["id"])
def test_published_tree_commitment(case):
    if case.get("unbindable"):
        with pytest.raises((_Refusal, ValueError, UnicodeError)):
            _tree_manifest(case["capture"])
    else:
        rows = _tree_manifest(case["capture"])
        assert rows == case["manifest"]
        assert sha256(canonicalize_v2(rows)).hexdigest() == case["sha256"]


@pytest.mark.parametrize("case", CORPUS["tree_alternates"], ids=lambda case: case["id"])
def test_tree_alternate_is_not_the_capture(case):
    source = next(row for row in CORPUS["tree_captures"] if row["id"] == case["of"])
    assert sha256(canonicalize_v2(_tree_manifest(source["capture"]))).hexdigest() != case["sha256"]

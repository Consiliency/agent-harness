"""Public-parser regression controls for agent-harness#825."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture(scope="module")
def verifier(record_testsuite_property):
    path = Path(__file__).resolve().parents[1] / "scripts/verify_harden_evidence.py"
    name = "harden_json_depth_825_subject"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    record_testsuite_property("json_depth_825_source", str(path))
    record_testsuite_property("json_depth_825_source_sha256", hashlib.sha256(path.read_bytes()).hexdigest())
    record_testsuite_property("json_depth_825_python", sys.version)
    record_testsuite_property("json_depth_825_executable", sys.executable)
    yield module
    sys.modules.pop(name, None)


@pytest.fixture(params=["strict_json_loads", "parse_canonical_json"])
def parser(request, verifier):
    return getattr(verifier, request.param)


def _nested_json(kind, depth):
    prefixes, suffixes = [], []
    for index in range(depth):
        array = kind == "array" or (kind == "mixed" and index % 2 == 0)
        prefixes.append(b"[" if array else b'{"a":')
        suffixes.append(b"]" if array else b"}")
    return b"".join(prefixes) + b"0" + b"".join(reversed(suffixes)) + b"\n"


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


@pytest.mark.parametrize("value", [[], {}, [{}], {"a": []}, None, True, 0, ""])
def test_empty_containers_and_scalars_are_accepted(parser, value):
    assert parser(_canonical(value), "empty or scalar control") == value


@pytest.mark.parametrize("kind", ["array", "object", "mixed"])
@pytest.mark.parametrize("depth", [64, 512])
def test_in_limit_nesting_is_accepted(parser, kind, depth):
    value = parser(_nested_json(kind, depth), "in-limit nesting")
    for _ in range(depth):
        value = value[0] if isinstance(value, list) else value["a"]
    assert value == 0


@pytest.mark.parametrize("kind", ["array", "object", "mixed"])
@pytest.mark.parametrize("depth", [513, 1024, 2048])
def test_over_limit_nesting_is_rejected(verifier, parser, kind, depth):
    with pytest.raises(verifier.EvidenceError):
        parser(_nested_json(kind, depth), "over-limit nesting")


@pytest.mark.parametrize("shape", ["two-deep-siblings", "600-empty-siblings"])
def test_wide_shallow_documents_are_accepted(parser, shape):
    if shape == "two-deep-siblings":
        chain = _nested_json("array", 511).rstrip(b"\n")
        raw = b"[" + chain + b"," + chain + b"]\n"
        value = parser(raw, "1023 containers at depth 512")
        assert len(value) == 2
        for child in value:
            for _ in range(511):
                child = child[0]
            assert child == 0
    else:
        value = parser(b"[" + b",".join([b"[]"] * 600) + b"]\n", "600 shallow siblings")
        assert value == [[] for _ in range(600)]


@pytest.mark.parametrize("first", [b"[]", b"{}"], ids=["closed-array", "closed-object"])
@pytest.mark.parametrize("chain_depth", [511, 512])
def test_closed_sibling_preserves_outer_depth(verifier, parser, first, chain_depth):
    raw = b"[" + first + b"," + _nested_json("array", chain_depth).rstrip(b"\n") + b"]\n"
    if chain_depth == 511:
        value = parser(raw, "closed sibling then depth 512")
        assert value[0] == json.loads(first)
        child = value[1]
        for _ in range(chain_depth):
            child = child[0]
        assert child == 0
    else:
        with pytest.raises(verifier.EvidenceError):
            parser(raw, "closed sibling then depth 513")


@pytest.mark.parametrize("slashes", range(7))
def test_quoted_brackets_and_escape_parity_are_data(parser, slashes):
    text = "[{" * 2048 + "\\" * slashes + '"' + "\\" * slashes + "[]{}"
    expected = [text, {text: text}]
    assert parser(_canonical(expected), "quoted data") == expected


@pytest.mark.parametrize("escape", [br"\u0022", br"\u005c", br"\u005b"])
def test_unicode_spellings_preserve_strict_and_canonical_rules(verifier, escape):
    raw = b'["' + escape + b"[" * 2048 + b'"]\n'
    expected = json.loads(raw)
    assert verifier.strict_json_loads(raw, "Unicode escape") == expected
    with pytest.raises(verifier.EvidenceError):
        verifier.parse_canonical_json(raw, "noncanonical Unicode spelling")
    canonical = _canonical(expected)
    assert verifier.strict_json_loads(canonical, "canonical Unicode data") == expected
    assert verifier.parse_canonical_json(canonical, "canonical Unicode data") == expected


@pytest.mark.parametrize("chain_depth", [511, 512])
def test_quoted_prefix_preserves_suffix_depth(verifier, parser, chain_depth):
    prefix = _canonical("[]" * 2048 + '\\"' + "\\" * 3).rstrip(b"\n")
    raw = b"[" + prefix + b"," + _nested_json("mixed", chain_depth).rstrip(b"\n") + b"]\n"
    if chain_depth == 511:
        value = parser(raw, "in-limit suffix after quoted prefix")
        assert value[0] == json.loads(prefix)
        child = value[1]
        for _ in range(chain_depth):
            child = child[0] if isinstance(child, list) else child["a"]
        assert child == 0
    else:
        with pytest.raises(verifier.EvidenceError):
            parser(raw, "over-limit suffix after quoted prefix")


@pytest.mark.parametrize("depth", [512, 513])
def test_noncanonical_whitespace_does_not_change_strict_depth(verifier, depth):
    raw = b" " + _nested_json("array", depth)
    if depth == 512:
        child = verifier.strict_json_loads(raw, "strict whitespace positive")
        for _ in range(depth):
            child = child[0]
        assert child == 0
    else:
        with pytest.raises(verifier.EvidenceError):
            verifier.strict_json_loads(raw, "strict whitespace over-limit")


@pytest.mark.parametrize(
    "raw",
    [b"", b"[[0]\n", b"[}\n", b'{"a":0]\n', b'["open]\n', br'["bad\x"]', b'"\xff"\n'],
    ids=["empty", "unbalanced", "mismatched", "object-close", "unterminated", "invalid-escape", "invalid-utf8"],
)
def test_malformed_documents_still_fail(verifier, parser, raw):
    with pytest.raises(verifier.EvidenceError):
        parser(raw, "malformed JSON")


@pytest.mark.parametrize(
    "raw",
    [b'{"a":1,"a":2}\n', b"[NaN]\n", b"[Infinity]\n", b"[-Infinity]\n", b"[1e9999]\n"],
    ids=["duplicate-key", "nan", "infinity", "negative-infinity", "float-overflow"],
)
def test_existing_duplicate_and_numeric_rejections(verifier, parser, raw):
    with pytest.raises(verifier.EvidenceError):
        parser(raw, "existing JSON constraints")


@pytest.mark.parametrize("limit", ["bytes", "integer-digits"])
def test_existing_size_limits_remain_enforced(verifier, parser, limit):
    raw = (b'["' + b"x" * (2 * 1024 * 1024) + b'"]\n') if limit == "bytes" else (b"[" + b"1" * 4097 + b"]\n")
    with pytest.raises(verifier.EvidenceError):
        parser(raw, "existing JSON size limit")


@pytest.mark.parametrize("raw", [b' { "a": 1 }\n', b'{"a":1}', b'{"b":2,"a":1}\n'])
def test_noncanonical_input_remains_strict_only(verifier, raw):
    expected = json.loads(raw)
    assert verifier.strict_json_loads(raw, "valid noncanonical JSON") == expected
    with pytest.raises(verifier.EvidenceError):
        verifier.parse_canonical_json(raw, "noncanonical JSON")
    assert verifier.parse_canonical_json(_canonical(expected), "canonical control") == expected


class _DecoderCalls:
    def __init__(self):
        self.calls = 0

    def loads(self, *args, **kwargs):
        self.calls += 1
        return json.loads(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


@pytest.mark.parametrize("kind", ["array", "object", "mixed"])
@pytest.mark.parametrize("depth", [512, 513, 1024, 2048])
def test_depth_limit_precedes_decoder_entry(verifier, parser, monkeypatch, kind, depth):
    proxy = _DecoderCalls()
    rejected = False
    with monkeypatch.context() as local:
        local.setattr(verifier, "json", proxy)
        try:
            parser(_nested_json(kind, depth), "decoder entry control")
        except verifier.EvidenceError:
            rejected = True
    assert verifier.json is json
    if depth == 512:
        assert proxy.calls == 1
        assert not rejected
    else:
        assert proxy.calls == 0, "JSON-DEPTH-825::rejected-before-decoder"
        assert rejected


@pytest.mark.parametrize("first", [b"[]", b"{}"], ids=["closed-array", "closed-object"])
@pytest.mark.parametrize("chain_depth", [511, 512])
def test_closed_sibling_depth_precedes_decoder_entry(verifier, parser, monkeypatch, first, chain_depth):
    raw = b"[" + first + b"," + _nested_json("array", chain_depth).rstrip(b"\n") + b"]\n"
    proxy = _DecoderCalls()
    rejected = False
    with monkeypatch.context() as local:
        local.setattr(verifier, "json", proxy)
        try:
            parser(raw, "decoder after closed sibling")
        except verifier.EvidenceError:
            rejected = True
    assert verifier.json is json
    if chain_depth == 511:
        assert proxy.calls == 1
        assert not rejected
    else:
        assert proxy.calls == 0, "JSON-DEPTH-825::closed-sibling-before-decoder"
        assert rejected


def test_unterminated_over_limit_prefix_never_enters_decoder(verifier, parser, monkeypatch):
    proxy = _DecoderCalls()
    rejected = False
    with monkeypatch.context() as local:
        local.setattr(verifier, "json", proxy)
        try:
            parser(b"[" * 513, "unterminated over-limit prefix")
        except verifier.EvidenceError:
            rejected = True
    assert verifier.json is json
    assert proxy.calls == 0, "JSON-DEPTH-825::unterminated-before-decoder"
    assert rejected

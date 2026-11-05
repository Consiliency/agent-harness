"""Structural corpus intake; expected runtime diagnostics remain unresolved."""
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

import pytest

from phase_loop_runtime.supervised_contracts import ContractError, load_contract_bundle, validate_record

ENVELOPE = "admitted_launch_envelope.v1"
STATUS = "supervised_run_status.v1"
FILES = {ENVELOPE: "conformance/envelope.vectors.json", STATUS: "conformance/run-status.vectors.json"}
SCHEMAS = {ENVELOPE: "admitted-launch-envelope.schema.json", STATUS: "run-status.schema.json"}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


@lru_cache(maxsize=2)
def corpus(family):
    return json.loads(load_contract_bundle().resource_bytes(FILES[family]))["cases"]


def pointer(value, path):
    for token in path.removeprefix("/").split("/") if path else []:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def envelope_digest(envelope):
    value = {k: v for k, v in envelope.items() if k != "envelope_digest"}
    # This helper is for the published ASCII/integer corpus only, not a JCS API.
    def domain(v):
        if isinstance(v, dict):
            assert all(isinstance(k, str) and k.isascii() for k in v)
            for child in v.values():
                domain(child)
        elif isinstance(v, list):
            for child in v:
                domain(child)
        elif isinstance(v, str):
            assert v.isascii()
        else:
            assert v is None or type(v) in (int, bool)
    domain(value)
    return sha256(encoded(value)).hexdigest()


def expand(family, case_id):
    cases = {c["id"]: c for c in corpus(family)}
    case = cases[case_id]
    value = deepcopy(case["input"] if case["role"] == "control" else cases[case["control"]]["input"])
    for operation in case.get("patch", []):
        parent_path, _, leaf = operation["path"].rpartition("/")
        parent = pointer(value, parent_path)
        key = leaf.replace("~1", "/").replace("~0", "~")
        if isinstance(parent, list):
            key = len(parent) if key == "-" else int(key)
        before = deepcopy(parent)
        if operation["op"] == "remove":
            del parent[key]
            expected = deepcopy(before)
            del expected[key]
            assert parent == expected and len(parent) == len(before) - 1
        elif operation["op"] == "add" and isinstance(parent, list):
            parent.insert(key, deepcopy(operation["value"]))
            assert parent[key] == operation["value"] and len(parent) == len(before) + 1
            assert parent[:key] + parent[key + 1:] == before
        else:
            assert operation["op"] in ("add", "replace")
            if operation["op"] == "replace":
                assert key in parent if isinstance(parent, dict) else 0 <= key < len(parent)
            parent[key] = deepcopy(operation["value"])
            assert parent[key] == operation["value"]
        assert parent != before
    if case.get("rehash"):
        previous = value["envelope"]["envelope_digest"]
        value["envelope"]["envelope_digest"] = envelope_digest(value["envelope"])
        assert value["envelope"]["envelope_digest"] != previous
        assert value["envelope"]["envelope_digest"] == envelope_digest(value["envelope"])
    if case_id == "S-digest-not-rehashed":
        assert value["envelope"]["envelope_digest"] != envelope_digest(value["envelope"])
        assert value["envelope"]["envelope_digest"] == cases[case["control"]]["input"]["envelope"]["envelope_digest"]
    return value


def components(family, value):
    if family == ENVELOPE:
        yield None, value["envelope"]
        return
    for attempt in value.get("journal", {}).get("attempts", []):
        for segment in attempt["segments"]:
            for line in segment["lines"]:
                if isinstance(line, dict):
                    yield "journal_line", line
    if "projection" in value:
        yield "projection", value["projection"]
    if "row" in value:
        yield "reader_view", value
    if "request" in value:
        yield "page_request", value["request"]
        yield "page", value["page"]


CASE_IDS = [(family, case["id"]) for family in FILES for case in corpus(family)]


@pytest.mark.parametrize("family,case_id", CASE_IDS, ids=[c for _, c in CASE_IDS])
def test_published_schema_only(family, case_id):
    bundle = load_contract_bundle()
    value = expand(family, case_id)
    parts = list(components(family, value))
    assert parts
    for definition, record in parts:
        assert validate_record(bundle, family, encoded(record), definition=definition) is None
    # Preserve exact raw segments, including malformed lines and tail flags.
    for attempt in value.get("journal", {}).get("attempts", []):
        for segment in attempt["segments"]:
            lines = [encoded(line) if isinstance(line, dict) else line.encode() for line in segment["lines"]]
            raw = b"\n".join(lines) + (b"\n" if segment["final_newline"] else b"")
            assert raw.endswith(b"\n") is segment["final_newline"]
            assert len(lines) == len(segment["lines"])
            for original, captured in zip(segment["lines"], lines):
                if isinstance(original, str):
                    assert captured == original.encode()
    if family == ENVELOPE and case_id.startswith("E-"):
        assert value["envelope"]["envelope_digest"] == envelope_digest(value["envelope"])


def test_inventory_matches_frozen_cases():
    artifact = (Path(__file__).resolve().parents[2] / "plans/artifacts/v12-SCHEMA-inputs.md").read_text()
    published = {(family, c["id"]) for family in FILES for c in corpus(family)}
    frozen = {(ENVELOPE if f == "envelope" else STATUS, c)
              for f, c in re.findall(r"^\| (envelope|status) \| `([^`]+)`", artifact, re.M)}
    assert published == frozen
    assert len(corpus(ENVELOPE)) == 16 and len(corpus(STATUS)) == 35


def test_equal_proposal_independent_attempt_evidence():
    bundle = load_contract_bundle()
    positive = expand(STATUS, "V-two-attempts")
    negative = expand(STATUS, "S-evidence-copied")
    def terminals(value):
        return [a["segments"][-1]["lines"][-1] for a in value["journal"]["attempts"]]
    first, second = terminals(positive)
    bindings = [line["body"]["result_binding"] for line in (first, second)]
    assert bindings[0]["proposal_bytes_digest"] == bindings[1]["proposal_bytes_digest"]
    assert bindings[0]["evidence_envelope_digest"] != bindings[1]["evidence_envelope_digest"]
    for key in ("envelope_digest", "run_id", "attempt_id"):
        assert first["attempt"][key] != second["attempt"][key]
        assert all(line["attempt"][key] == line["body"]["result_binding"][key] for line in (first, second))
    copied = terminals(negative)
    assert copied[0]["body"]["result_binding"]["evidence_envelope_digest"] == copied[1]["body"]["result_binding"]["evidence_envelope_digest"]
    assert next(c for c in corpus(STATUS) if c["id"] == "S-evidence-copied")["expected"] == ["attempt_evidence_copied"]
    for value in (positive, negative):
        for definition, record in components(STATUS, value):
            validate_record(bundle, STATUS, encoded(record), definition=definition)


def examples():
    result = {}
    for family in FILES:
        for case in corpus(family):
            if case["role"] == "control":
                for definition, record in components(family, case["input"]):
                    result.setdefault((family, definition), record)
    return result


@pytest.mark.parametrize("family,definition", list(examples()))
def test_definition_structural_negative(family, definition):
    bundle = load_contract_bundle()
    value = deepcopy(examples()[family, definition])
    validate_record(bundle, family, encoded(value), definition=definition)
    value["not_in_contract"] = True
    with pytest.raises(ContractError, match="record_schema_invalid"):
        validate_record(bundle, family, encoded(value), definition=definition)


def sha256_positions():
    """All schema-declared sha256 references, including nullable/array branches."""
    bundle = load_contract_bundle()
    positions = []
    def walk(family, value, path):
        if isinstance(value, dict):
            if value.get("$ref") == "#/$defs/sha256":
                positions.append((family, path))
            for k, child in value.items():
                walk(family, child, path + "/" + k.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(family, child, path + "/" + str(i))
    for family, name in SCHEMAS.items():
        walk(family, json.loads(bundle.resource_bytes(name)), "")
    return positions


def schema_target(path):
    # Replace each reference position using a minimal record for its containing
    # definition; schema reachability is separately exercised by corpus records.
    parts = path.split("/")
    return parts[2] if parts[1] == "$defs" else None


@lru_cache(maxsize=2)
def nested_records(all_refs=False):
    """Witnesses for each declared reference through the public entry points."""
    bundle = load_contract_bundle()
    witnessed = {}
    def walk(family, definition, root, value, schema, schema_path, value_path, full):
        if not isinstance(schema, dict):
            return
        if "$ref" in schema:
            if all_refs and value is not None:
                witnessed.setdefault((family, schema_path), (definition, root, value_path))
            if schema["$ref"] == "#/$defs/sha256":
                if isinstance(value, str):
                    witnessed.setdefault((family, schema_path), (definition, root, value_path))
                return
            target_path = schema["$ref"][1:]
            walk(family, definition, root, value, pointer(full, target_path), target_path, value_path, full)
        for keyword in ("anyOf", "oneOf"):
            for i, child in enumerate(schema.get(keyword, [])):
                walk(family, definition, root, value, child, schema_path + f"/{keyword}/{i}", value_path, full)
        if isinstance(value, dict):
            for key, child in schema.get("properties", {}).items():
                if key in value:
                    walk(family, definition, root, value[key], child, schema_path + "/properties/" + key, value_path + "/" + key, full)
        if isinstance(value, list) and "items" in schema:
            for i, child in enumerate(value):
                walk(family, definition, root, child, schema["items"], schema_path + "/items", value_path + "/" + str(i), full)
    for family in FILES:
        schema = json.loads(bundle.resource_bytes(SCHEMAS[family]))
        for case in corpus(family):
            for definition, record in components(family, expand(family, case["id"])):
                start = "/$defs/" + definition if definition else ""
                walk(family, definition, record, record, pointer(schema, start), start, "", schema)
                if definition == "journal_line":
                    walk(family, None, record, record, schema, "", "", schema)
    return witnessed


POSITIONS = sha256_positions()


@pytest.mark.parametrize("family,path", POSITIONS, ids=[f.split('.')[0] + p for f, p in POSITIONS])
def test_every_sha256_position(family, path):
    bundle = load_contract_bundle()
    witnesses = nested_records()
    assert (family, path) in witnesses, path
    definition, record, instance_path = witnesses[family, path]
    validate_record(bundle, family, encoded(record), definition=definition)
    for bad in ("a" * 63, "a" * 65, "A" * 64, "a" * 64 + "\n", "a" * 64 + "\r", "a" * 64 + "\u2028"):
        value = deepcopy(record)
        parent, _, key = instance_path.rpartition("/")
        target = pointer(value, parent)
        target[int(key) if isinstance(target, list) else key] = bad
        with pytest.raises(ContractError, match="record_schema_invalid"):
            validate_record(bundle, family, encoded(value), definition=definition)


def all_reference_positions():
    result = []
    def walk(family, value, path):
        if isinstance(value, dict):
            if "$ref" in value:
                result.append((family, path))
            for key, child in value.items():
                walk(family, child, path + "/" + key)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(family, child, path + "/" + str(i))
    bundle = load_contract_bundle()
    for family, name in SCHEMAS.items():
        walk(family, json.loads(bundle.resource_bytes(name)), "")
    return result


@pytest.mark.parametrize("family,path", all_reference_positions(), ids=[f.split('.')[0] + p for f, p in all_reference_positions()])
def test_nested_reference_negative(family, path):
    bundle = load_contract_bundle()
    definition, record, instance_path = nested_records(True)[family, path]
    value = deepcopy(record)
    if not instance_path:
        value = False
    else:
        parent, _, key = instance_path.rpartition("/")
        target = pointer(value, parent)
        target[int(key) if isinstance(target, list) else key] = False
    with pytest.raises(ContractError, match="record_schema_invalid"):
        validate_record(bundle, family, encoded(value), definition=definition)


def semantic_inventory():
    bundle = load_contract_bundle()
    rows = []
    for family, name in SCHEMAS.items():
        schema = json.loads(bundle.resource_bytes(name))
        prefix = "envelope" if family == ENVELOPE else "status"
        owner = "ENVELOPE/WORKER" if family == ENVELOPE else "JOURNAL/WORKER"
        def row(identity, source, vectors=()):
            return {"id": identity, "source_pointer": source, "vector_ids": sorted(vectors),
                    "owner": owner, "status": "upstream_phase_unmet", "required_proof": "production paths and per-guard mutations at CLOSEOUT"}
        for code in schema["x-semantic-rules"]:
            rows.append(row(prefix + ":" + code, name + "#/x-semantic-rules/" + code,
                            [c["id"] for c in corpus(family) if code in c["expected"]]))
        def journal(value, path):
            if isinstance(value, dict):
                children = value.items()
            elif isinstance(value, list):
                children = enumerate(value)
            else:
                return
            for key, child in children:
                child_path = path + "/" + str(key)
                rows.append(row("journal:" + child_path, name + "#" + child_path))
                journal(child, child_path)
        journal(schema.get("x-journal-rules", {}), "/x-journal-rules")
    return rows

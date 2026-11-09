"""Verify immutable earlier receipts while their consumers continue evolving."""
from hashlib import sha256
import json
from pathlib import Path
import re

SEALS = {
    "SCHEMA": "2a8077d504d2f1d5a34b84fccec3062242c96de9c05a1d65944a824ee0be58b4",
    "ENVELOPE": "b65f0f6ec562c344da46d1c153c471db8955f45bed84b129cfe3e737e9b00b46",
    "JOURNAL": "a65626471966ef4fb412ac7063a3a9da8da6ca0d3f375e402418827a57768ae3",
    "WORKER": "978bbecfd4fedca8689a34b146396d9799a91b84d095069e536e5521650f7a26",
}
RETIRED_NODES = {"WORKER": frozenset({
    "tests/test_supervised_worker_cli.py::test_isolated_cli_before_root[argv0-codec_unavailable]",
})}


def verify_historical_receipt(path: Path, *, record=None, producer_nodes, mutation_controls=None):
    """Check the sealed record and the continued existence of its producers.

    Callers collect only the receipt's named producer files. They supply actual
    current node IDs, never a count or an inventory taken from the receipt itself.
    """
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == SEALS[path.stem]
    blocks = re.findall(rb"```json\n(.*?)\n```", raw, re.S)
    assert len(blocks) == 1
    historical = json.loads(blocks[0])
    if record is not None:
        assert record == historical
    hashes = historical.get("source_hashes")
    if hashes is not None:
        assert historical["runner_stamp"]["source_tree_digest"] == sha256(
            json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if "producer_outcomes" in historical:
        outcomes = historical["producer_outcomes"]
        assert outcomes and all(value == "passed" for value in outcomes.values())
        nodes = set(outcomes)
        if "producer_nodes" in historical:
            assert nodes == set(historical["producer_nodes"])
    else:
        rows = [row for group in ("intake_results", "schema_results", "mutation_results")
                for row in historical.get(group, [])]
        assert rows and all(row["outcome"] == "passed" for row in rows)
        nodes = {row["test_node_id"] for row in rows}
    normalize = lambda node: node.removeprefix("phase-loop-runtime/")
    required = {normalize(node) for node in nodes} - RETIRED_NODES.get(path.stem, frozenset())
    assert required <= {normalize(node) for node in producer_nodes}
    if mutation_controls is not None:
        recorded = historical.get("mutation_controls", historical.get("mutation_outcomes", {}))
        if isinstance(recorded, dict) and all(isinstance(value, list) for value in recorded.values()):
            assert recorded.keys() <= mutation_controls.keys()
            for family, controls in recorded.items():
                assert set(controls) <= set(mutation_controls[family])
        else:
            assert set(recorded) <= set(mutation_controls)
    return historical

"""Byte pins for the GROK jail contract and its standalone revision."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "plans/manifest.json"
PLAN = "plans/phase-plan-v1-seats-GROK.md"


@pytest.mark.skipif(not MANIFEST.is_file(), reason="planning artifacts absent in clean-room")
def test_grok_jail_contract_byte_pins():
    entries = json.loads(MANIFEST.read_bytes())["plans"]
    entry, = (row for row in entries if row["file"] == PLAN)
    plan_text = (REPO / PLAN).read_text(encoding="utf-8")
    for artifact in (
        "plans/artifacts/grok-jail-tool-surface-contract-v1.md",
        "plans/artifacts/grok-jail-tool-surface-contract-v1-erratum-r8.md",
    ):
        digest = sha256((REPO / artifact).read_bytes()).hexdigest()
        assert entry["frozen_inputs"][artifact]["sha256"] == digest
        assert f"`{artifact}` at sha256\n  `{digest}`" in plan_text

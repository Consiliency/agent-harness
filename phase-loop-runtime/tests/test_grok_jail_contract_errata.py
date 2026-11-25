"""Byte pins for the GROK jail contract, errata, and image provenance."""

import json
import re
from hashlib import sha256
from pathlib import Path

import pytest
import rfc8785

from phase_loop_runtime.grok_roll.catalog import verify_entry_signature

REPO = Path(__file__).resolve().parents[2]
MANIFEST = REPO / "plans/manifest.json"
PLAN = "plans/phase-plan-v1-seats-GROK.md"
CONTRACT = "plans/artifacts/grok-jail-tool-surface-contract-v1.md"
R8 = "plans/artifacts/grok-jail-tool-surface-contract-v1-erratum-r8.md"
MANAGED_ERRATUM = "plans/artifacts/grok-jail-tool-surface-contract-v1-managed-subject-erratum.md"
RECEIPT = "plans/evidence/seat-grok/image-provenance-1.0.92.json"

pytestmark = pytest.mark.skipif(not MANIFEST.is_file(), reason="planning artifacts absent in clean-room")


def test_grok_jail_contract_byte_pins():
    entries = json.loads(MANIFEST.read_bytes())["plans"]
    entry, = (row for row in entries if row["file"] == PLAN)
    plan_text = (REPO / PLAN).read_text(encoding="utf-8")
    erratum_text = (REPO / MANAGED_ERRATUM).read_text(encoding="utf-8")
    for artifact in (CONTRACT, R8, MANAGED_ERRATUM, RECEIPT):
        digest = sha256((REPO / artifact).read_bytes()).hexdigest()
        assert entry["frozen_inputs"][artifact]["sha256"] == digest
        assert f"`{artifact}` at sha256\n  `{digest}`" in plan_text
        if artifact != MANAGED_ERRATUM:
            assert f"`{artifact}` at sha256\n`{digest}`" in erratum_text

    assert entry["frozen_inputs"][CONTRACT]["sha256"] == (
        "f2fc6c88471dd88f52168136cec0f770fa7c286cd1ce71a1fd8b341878ea8b66"
    )
    assert entry["frozen_inputs"][R8]["sha256"] == (
        "6fbad698480d1ba3391888bd2a31350a954051c684b5489047f488a7c8468490"
    )


def test_grok_image_provenance_receipt():
    raw = (REPO / RECEIPT).read_bytes()
    receipt = json.loads(raw)
    assert set(receipt) == {
        "schema", "package", "version", "tarball_integrity", "registry_keyid",
        "registry_signature", "member", "binary_bytes", "binary_sha256",
    }
    assert rfc8785.dumps(receipt) == raw
    assert receipt["schema"] == "grok_image_provenance.v1"
    assert receipt["package"] == "@xai-official/grok-linux-x64"
    assert receipt["version"] == "1.0.92"
    assert receipt["member"] == "package/bin/grok.br"
    assert type(receipt["binary_bytes"]) is int and receipt["binary_bytes"] > 0
    assert receipt["binary_sha256"] == (
        "add4d201dbf2c0bd6077a36feb55a76939de30bae48dbb06f16b2307d38ceacb"
    )
    assert re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", receipt["tarball_integrity"])
    assert verify_entry_signature(receipt)
    assert sha256(raw).hexdigest() == (
        "398f019cc3709a745bb6d8173e0b7d78ae0441f999ac19bb513f22e779f43c36"
    )

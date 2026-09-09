"""Consiliency/agent-harness#789 Workstream D, Lane D4 — the operator surface.

``phase-loop fabpub-rotate-partition`` drives ``rotate_blocked_partition`` from an
OPERATOR-SUPPLIED attestation document.  These tests run the real ceremony
through ``cli.main`` over the D1 fixtures (imported, never copied) and pin:

* the verb's success contract (``PartitionRotationResult.v1``, pointer flip,
  idempotent re-run, generation-0 bytes untouched);
* every refusal is exit 1 with the verb's stderr prefix and leaves NO durable
  rotation state — a missing / non-JSON / non-object attestation, a document
  taken from inside the authority's ceremony directory (fable r9 O3), and a
  ceremony refusal (an undisposed blocked key);
* the two carried loader/provenance refusals D4 lands: receipt bytes that are
  not JSON are a typed ``LegacyCutoverConflict`` from ``load_partition_receipt``
  (fable r10 O2), and a sealed inventory missing behind a receipt that names
  completed keys is named as missing by ``sealed_partition_effects``
  (fable r12 O2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phase_loop_runtime.cli import main
from test_fabpub_partition_rotation_789d import (
    GENERATIONS_DIR,
    OBSERVED_LANDED,
    ROTATED_KEY,
    ROTATION_CEREMONY_DIR,
    ROTATION_ID,
    TERMINAL_KEY,
    _attestation,
    _block_key,
    _bootstrap,
    _ceremony_dir,
    _complete_key,
    _generation_of,
    _journal_path,
    _live,
    _release_all,
    _requires_fabpub,
    _store_bytes,
)

pytestmark = [_requires_fabpub]

VERB = "fabpub-rotate-partition"
PREFIX = f"phase-loop {VERB}: "


def _blocked(tmp_path, monkeypatch):
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    carried_key = p.service._dedup_key(p.request)
    _block_key(p, carried_key)
    _release_all(p)
    attestation = _attestation(
        p, dispositions={carried_key: OBSERVED_LANDED}, observed_head=p.request.head_sha
    )
    return fx, p, attestation


def _write(path: Path, document) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _run(p, attestation_path, *, cutover_id=ROTATION_ID, as_json=False, extra=()):
    argv = [
        VERB,
        "--worktree",
        str(p.repo),
        "--attestation",
        str(attestation_path),
        "--cutover-id",
        cutover_id,
        *extra,
    ]
    if as_json:
        argv.append("--json")
    return main(argv)


def _assert_no_durable_rotation(p, *, cutover_id=ROTATION_ID) -> None:
    assert not (p.container / GENERATIONS_DIR).exists(), "generation debris after a refusal"
    assert not any(p.container.glob(f"{GENERATIONS_DIR}.tmp.*")), "staging debris after a refusal"
    assert not _journal_path(p, cutover_id).exists(), "a refused verb wrote a rotation journal"
    assert not (_ceremony_dir(p) / f"{cutover_id}.inventory.json").exists(), "a refused verb sealed an inventory"
    assert _generation_of(p.container) == 0


@pytest.mark.parametrize("as_json", [False, True])
def test_rotate_partition_cli_rotates_and_is_idempotent(tmp_path, monkeypatch, capsys, as_json):
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    attestation_path = _write(tmp_path / "operator" / "attestation.json", attestation)

    assert _run(p, attestation_path, as_json=as_json) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert result["schema"] == "PartitionRotationResult.v1"
    assert result["state"] == "ACTIVE"
    assert result["cutover_id"] == ROTATION_ID
    assert result["generation"] == 1
    assert result["predecessor_generation"] == 0
    assert result["canonical_repository_identity"] == p.identity
    assert result["store_root"] == str(p.container / GENERATIONS_DIR / "1")
    assert result["predecessor_store_root"] == str(p.container)
    assert result["receipt_schema"] == "LegacyRepositoryPartitionReceipt.v3"
    assert result["adjudicated_effect_keys"] == sorted(attestation["effects"])
    assert result["restart_required"] is True
    assert _generation_of(p.container) == 1
    assert _store_bytes(p.container) == gen0, "generation-0 bytes changed through the verb"
    live = _live()
    receipt = live.load_partition_receipt(p.container / GENERATIONS_DIR / "1")
    assert receipt is not None and receipt.attestation_sha256 == result["attestation_sha256"]

    # The same command again is the idempotent resume: same generation, no
    # second successor, and the answer is the same document.
    assert _run(p, attestation_path, as_json=as_json) == 0
    again = json.loads(capsys.readouterr().out)
    assert again == result
    assert not (p.container / GENERATIONS_DIR / "2").exists()


@pytest.mark.parametrize(
    "shape",
    ["missing", "not_json", "not_object"],
)
def test_rotate_partition_cli_refuses_an_unreadable_attestation(tmp_path, monkeypatch, capsys, shape):
    fx, p, _attestation_doc = _blocked(tmp_path, monkeypatch)
    path = tmp_path / "operator" / "attestation.json"
    path.parent.mkdir(parents=True)
    if shape == "not_json":
        path.write_text("{not json", encoding="utf-8")
    elif shape == "not_object":
        path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    assert _run(p, path) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith(PREFIX), captured.err
    expected = {
        "missing": "does not exist",
        "not_json": "is not JSON",
        "not_object": "is not a JSON object",
    }[shape]
    assert expected in captured.err
    _assert_no_durable_rotation(p)


def test_rotate_partition_cli_refuses_an_attestation_from_the_ceremony_directory(tmp_path, monkeypatch, capsys):
    """fable r9 O3: the resume's attestation is operator-supplied, never the copy
    a sealed rotation inventory embeds.  A document under the authority's
    ceremony directory is refused BEFORE it is read — even a valid one."""
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    inside = _write(
        p.authority / ROTATION_CEREMONY_DIR / p.identity / f"{ROTATION_ID}.attestation.json",
        attestation,
    )
    live = _live()
    reads: list = []
    real = Path.read_text

    def _spy(self, *args, **kwargs):
        reads.append(Path(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _spy)
    assert _run(p, inside) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith(PREFIX) and "operator-supplied" in captured.err, captured.err
    assert "rotation ceremony directory" in captured.err
    assert inside.resolve() not in [r.resolve() for r in reads], "the ceremony-directory document was read"
    monkeypatch.setattr(Path, "read_text", real)
    assert not _journal_path(p).exists() and _generation_of(p.container) == 0
    assert live.load_partition_receipt(p.container) is not None


def test_rotate_partition_cli_ceremony_refusal_is_exit_one_without_writes(tmp_path, monkeypatch, capsys):
    """A ceremony refusal (here: a blocked key the attestation leaves undisposed,
    plan m1) surfaces as exit 1 with the ceremony's message and no durable
    state — the verb adds nothing to the ceremony's fail-closed set."""
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    _block_key(p, ROTATED_KEY)
    _release_all(p)
    # ``attestation`` covers only the first key; ROTATED_KEY stays undisposed.
    path = _write(tmp_path / "operator" / "partial.json", attestation)
    assert _run(p, path) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith(PREFIX), captured.err
    _assert_no_durable_rotation(p)


def test_rotate_partition_cli_wrong_schema_document_is_a_ceremony_refusal(tmp_path, monkeypatch, capsys):
    """A sealed INVENTORY presented as the attestation (the circular resume
    fable r9 O3 names) is refused by the ceremony's schema check when it is
    copied outside the ceremony directory: the verb never accepts it."""
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    operator_copy = _write(
        tmp_path / "operator" / "attestation.json", attestation
    )
    assert _run(p, operator_copy) == 0
    capsys.readouterr()
    sealed = _ceremony_dir(p) / f"{ROTATION_ID}.inventory.json"
    assert sealed.is_file()
    relocated = tmp_path / "operator" / "inventory-copy.json"
    relocated.write_bytes(sealed.read_bytes())
    assert _run(p, relocated) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith(PREFIX), captured.err
    assert "attestation must carry schema 'PartitionRotationAttestation.v1'" in captured.err
    assert _generation_of(p.container) == 1 and not (p.container / GENERATIONS_DIR / "2").exists()


def test_load_partition_receipt_refuses_non_json_receipt_bytes_typed(tmp_path, monkeypatch):
    """fable r10 O2, closed at the loader: receipt bytes that are not JSON (or
    not an object) raise ``LegacyCutoverConflict``, the type every fail-closed
    ``except`` around ``load_partition_receipt`` already handles — never a
    bare ``ValueError``."""
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    receipt_path = p.container / "partition-receipt.json"
    original = receipt_path.read_bytes()
    try:
        receipt_path.write_bytes(b"{not json")
        with pytest.raises(live.LegacyCutoverConflict, match="are not JSON"):
            live.load_partition_receipt(p.container)
        receipt_path.write_bytes(b"[1, 2, 3]")
        with pytest.raises(live.LegacyCutoverConflict, match="is not a JSON object"):
            live.load_partition_receipt(p.container)
    finally:
        receipt_path.write_bytes(original)
    assert live.load_partition_receipt(p.container) is not None


def test_sealed_partition_effects_names_a_missing_inventory(tmp_path, monkeypatch):
    """fable r12 O2: an inventory missing AFTER the receipt authenticated, behind
    a receipt that names completed keys, is named as missing (typed) instead of
    surfacing as a key-set disagreement over an empty map; a receipt naming no
    keys keeps its empty map."""
    live = _live()
    fx = _bootstrap(tmp_path, monkeypatch)
    p = fx.alpha
    _complete_key(p, TERMINAL_KEY)
    _release_all(p)
    _block_key(p, ROTATED_KEY)
    _release_all(p)
    attestation = _attestation(p)
    outcome = live.rotate_blocked_partition(
        p.repo, cutover_id=ROTATION_ID, attestation=attestation, authority_root=p.authority
    )
    assert outcome.state == "ACTIVE"
    receipt = outcome.receipt
    assert TERMINAL_KEY in receipt.legacy_completed_effect_keys
    inventory = Path(receipt.global_journal_path).parent / f"{receipt.cutover_id}.inventory.json"
    assert inventory.is_file()
    carried = live.sealed_partition_effects(receipt)
    assert TERMINAL_KEY in carried
    saved = inventory.read_bytes()
    try:
        inventory.unlink()
        with pytest.raises(live.LegacyCutoverConflict, match="is missing; the partition receipt names 1 completed effect key"):
            live.sealed_partition_effects(receipt)
    finally:
        inventory.write_bytes(saved)
    assert live.sealed_partition_effects(receipt) == carried
    bare = fx.beta
    bare_receipt = live.load_partition_receipt(bare.container)
    assert bare_receipt is not None and bare_receipt.legacy_completed_effect_keys == ()
    bare_inventory = Path(bare_receipt.global_journal_path).parent / f"{bare_receipt.cutover_id}.inventory.json"
    saved = bare_inventory.read_bytes()
    try:
        bare_inventory.unlink()
        assert live.sealed_partition_effects(bare_receipt) == {}
    finally:
        bare_inventory.write_bytes(saved)

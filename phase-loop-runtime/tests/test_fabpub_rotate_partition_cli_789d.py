"""Consiliency/agent-harness#789 Workstream D, Lane D4 — the operator surface.

``phase-loop fabpub-rotate-partition`` drives ``rotate_blocked_partition`` from an
OPERATOR-SUPPLIED attestation document.  These tests run the real ceremony
through ``cli.main`` over the D1 fixtures (imported, never copied) and pin:

* the verb's success contract (``PartitionRotationResult.v1``, pointer flip,
  idempotent re-run, generation-0 bytes untouched);
* every refusal is exit 1 with the verb's stderr prefix; a refusal BEFORE the
  ceremony's first journal row leaves NO durable rotation state — a missing /
  non-JSON / non-object attestation, a document taken from inside the
  authority's ceremony directory (fable r9 O3), and a ceremony refusal (an
  undisposed blocked key);
* a refusal AFTER durable progress (codex r1 F1: predecessor writers that do
  not drain, refused behind the DRAINING journal row) keeps that cutover id's
  journal, refuses a different cutover id as "still in progress", and resumes
  to ACTIVE under the same id — generation-0 bytes untouched throughout;
* the two carried loader/provenance refusals D4 lands: receipt bytes that are
  not JSON are a typed ``LegacyCutoverConflict`` from ``load_partition_receipt``
  (fable r10 O2), and a sealed inventory missing behind a receipt that names
  completed keys is named as missing by ``sealed_partition_effects``
  (fable r12 O2);
* the docs' post-flip "Recovery" rule (codex r2 F2, r3 F1/F2, r4 F1; fable r4
  F1/F2): a re-run never recreates or rewrites a file the ceremony did not
  write at the step it resumes — a damaged successor receipt, sealed
  inventory, or generation-0 digested store file, and a missing writer latch
  after the ``ACTIVE`` row, are each refused on every re-run until restored
  from outside, and the same command then finishes; a crash after the
  ``ACTIVE`` row owes only the latch activation.
"""

from __future__ import annotations

import builtins
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
    _journal_states,
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


@pytest.mark.parametrize("authority_spelling", ["default", "absolute", "tilde"])
def test_rotate_partition_cli_refuses_an_attestation_from_the_ceremony_directory(
    tmp_path, monkeypatch, capsys, authority_spelling
):
    """fable r9 O3: the resume's attestation is operator-supplied, never the copy
    a sealed rotation inventory embeds.  A document under the authority's
    ceremony directory is refused BEFORE it is read — even a valid one — under
    every spelling of the authority root: the environment default, an explicit
    absolute ``--authority-root``, and a literal ``~`` the shell did not expand
    (fable r1 F1: the guard once resolved that spelling cwd-relative while the
    ceremony expanded it, so the document inside was read and rotated from)."""
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    extra: tuple = ()
    if authority_spelling == "absolute":
        extra = ("--authority-root", str(p.authority))
    elif authority_spelling == "tilde":
        monkeypatch.setenv("HOME", str(p.authority.parent))
        extra = ("--authority-root", f"~/{p.authority.name}")
        assert Path(f"~/{p.authority.name}").expanduser() == p.authority
    inside = _write(
        p.authority / ROTATION_CEREMONY_DIR / p.identity / f"{ROTATION_ID}.attestation.json",
        attestation,
    )
    live = _live()
    reads: list = []
    real_text, real_bytes, real_open, real_builtin_open = (
        Path.read_text, Path.read_bytes, Path.open, builtins.open
    )

    def _spy_text(self, *args, **kwargs):
        reads.append(Path(self))
        return real_text(self, *args, **kwargs)

    def _spy_bytes(self, *args, **kwargs):
        reads.append(Path(self))
        return real_bytes(self, *args, **kwargs)

    def _spy_open(self, *args, **kwargs):
        reads.append(Path(self))
        return real_open(self, *args, **kwargs)

    def _spy_builtin_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)):
            reads.append(Path(file))
        return real_builtin_open(file, *args, **kwargs)

    # Every read seam the loader could take (grok r1: a `read_text`-only spy
    # stays green if the loader switches to `read_bytes` / `open`).
    monkeypatch.setattr(Path, "read_text", _spy_text)
    monkeypatch.setattr(Path, "read_bytes", _spy_bytes)
    monkeypatch.setattr(Path, "open", _spy_open)
    monkeypatch.setattr(builtins, "open", _spy_builtin_open)
    assert _run(p, inside, extra=extra) == 1
    monkeypatch.setattr(builtins, "open", real_builtin_open)
    monkeypatch.setattr(Path, "open", real_open)
    monkeypatch.setattr(Path, "read_bytes", real_bytes)
    monkeypatch.setattr(Path, "read_text", real_text)
    captured = capsys.readouterr()
    assert captured.err.startswith(PREFIX) and "operator-supplied" in captured.err, captured.err
    assert "rotation ceremony directory" in captured.err
    assert inside.resolve() not in [r.resolve() for r in reads], "the ceremony-directory document was read"
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


def test_rotate_partition_cli_post_journal_refusal_keeps_a_resumable_journal(tmp_path, monkeypatch, capsys):
    """codex r1 F1: a refusal AFTER the ceremony's first durable step is NOT
    "no durable rotation state".  Predecessor writers that never drain are
    refused behind the DRAINING journal row: that row persists for the cutover
    id, a DIFFERENT cutover id is refused as still in progress, and the SAME id
    resumes to ACTIVE once the writers are gone.  Generation-0 bytes and the
    writer latch (back to ACTIVE, nonce preserved) are untouched by the refusal.
    The drain seam is ``WriterGenerationLatch.await_quiescent`` (the D1 idiom)."""
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    nonce_before = latch.read().generation
    real_await = live.WriterGenerationLatch.await_quiescent

    def _never_drains(self, *, worktree, timeout=60.0):
        raise live.WriterGenerationBlocked(
            "DRAINING did not reach zero before INVENTORY_SEALED: 1 held generation lease(s)"
        )

    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", _never_drains)
    assert _run(p, path) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith(PREFIX), captured.err
    assert "predecessor writers did not drain" in captured.err, captured.err
    # Durable progress: the DRAINING row is the ceremony's first journal write
    # and it survives the refusal — this is what the docs must not deny.
    assert _journal_states(p) == ["DRAINING"]
    assert not (_ceremony_dir(p) / f"{ROTATION_ID}.inventory.json").exists()
    assert not (p.container / GENERATIONS_DIR).exists()
    assert _generation_of(p.container) == 0
    assert _store_bytes(p.container) == gen0, "the refusal changed generation 0"
    after = latch.read()
    assert after.generation_state == "ACTIVE" and after.generation == nonce_before, (
        "the refusal did not resume the writer latch with its nonce preserved"
    )

    # A different cutover id must not start over the in-progress journal.
    other = f"{ROTATION_ID}-other"
    assert _run(p, path, cutover_id=other) == 1
    captured = capsys.readouterr()
    assert "is still in progress" in captured.err and ROTATION_ID in captured.err, captured.err
    assert not _journal_path(p, other).exists()
    assert _journal_states(p) == ["DRAINING"]

    # Once the predecessor writers are gone, the SAME id resumes to ACTIVE.
    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", real_await)
    assert _run(p, path) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "ACTIVE" and result["generation"] == 1
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert _generation_of(p.container) == 1
    assert _store_bytes(p.container) == gen0


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


def test_rotate_partition_cli_post_flip_damaged_successor_receipt_is_refused_not_repaired(tmp_path, monkeypatch, capsys):
    """Docs "Recovery" (codex r2 F2): the ONE post-flip state a re-run does not
    resume.  The ceremony authenticates the successor through the real loader
    immediately before the flip, so a successor that later "carries no receipt"
    is damage done AFTER the flip by something other than the ceremony.  The verb
    refuses that partition on every re-run — the resolver's own ``generation 1
    carries no partition receipt`` fires before the ceremony's resume branch —
    leaving the journal at ARMED and the latch un-activated, and only
    restoring the receipt bytes from outside the ceremony lets the same command
    finish.  It never regenerates the receipt.
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    with live.crash_at_rotation_step("after_pointer_flip"):
        with pytest.raises(live._RotationCrash):
            _run(p, path)
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED"]
    assert _generation_of(p.container) == 1
    successor_receipt = p.container / GENERATIONS_DIR / "1" / live.RECEIPT_FILENAME
    saved = successor_receipt.read_bytes()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    before = latch.read()
    assert before.generation_state != "ACTIVE"

    successor_receipt.unlink()
    assert _run(p, path) == 1
    err = capsys.readouterr().err
    assert err.startswith(PREFIX)
    assert "generation 1 carries no partition receipt" in err
    assert not successor_receipt.exists(), "the verb regenerated a successor receipt it never authenticated"
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED"]
    assert _generation_of(p.container) == 1
    after = latch.read()
    assert after.generation_state == before.generation_state and after.generation == before.generation
    assert _store_bytes(p.container) == gen0

    successor_receipt.write_bytes(saved)
    assert _run(p, path) == 0
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == gen0


def test_rotate_partition_cli_changed_bytes_refusal_resumes_the_latch_and_takes_a_reattestation(tmp_path, monkeypatch, capsys):
    """Docs "Refusals after durable progress", the changed-bytes arm (fable r2
    O1: unpinned before this test — ``resume_active`` at the changed-bytes site
    could be deleted with every rotation test green).  A predecessor whose
    digested bytes moved between attestation and drain is refused behind the
    ``DRAINING`` row with the latch resumed to ACTIVE (nonce preserved); the
    stale attestation is refused zero-write on the re-run; a re-written
    attestation over the current bytes resumes the same cutover id to ACTIVE.
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    nonce_before = latch.read().generation
    evidence = p.container / "evidence.jsonl"
    real_await = live.WriterGenerationLatch.await_quiescent

    def _last_writer_lands(self, *, worktree, timeout=60.0):
        # A writer that landed under the predecessor lock's shadow: the drain
        # completes, but the digested bytes are no longer the attested bytes.
        # The row re-states the last evidence row (same key, same state), so
        # adjudication is unchanged and only the digest moves.
        last = evidence.read_text(encoding="utf-8").splitlines()[-1]
        with evidence.open("a", encoding="utf-8") as handle:
            handle.write(last + "\n")
        return real_await(self, worktree=worktree, timeout=timeout)

    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", _last_writer_lands)
    assert _run(p, path) == 1
    err = capsys.readouterr().err
    assert err.startswith(PREFIX)
    assert "changed between attestation and drain; re-attest over the current bytes" in err
    monkeypatch.setattr(live.WriterGenerationLatch, "await_quiescent", real_await)
    assert _journal_states(p) == ["DRAINING"]
    assert not (_ceremony_dir(p) / f"{ROTATION_ID}.inventory.json").exists()
    assert _generation_of(p.container) == 0
    moved = _store_bytes(p.container)
    after = latch.read()
    assert after.generation_state == "ACTIVE" and after.generation == nonce_before

    # The stale attestation is a validation refusal on the re-run: zero-write.
    assert _run(p, path) == 1
    err = capsys.readouterr().err
    assert "predecessor_store_digests do not match" in err
    assert _journal_states(p) == ["DRAINING"]
    assert latch.read().generation_state == "ACTIVE"

    # Re-attest over the current bytes: the same cutover id resumes to ACTIVE.
    reattested = _write(tmp_path / "operator" / "attestation-2.json", _attestation(p))
    assert _run(p, reattested) == 0
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert _generation_of(p.container) == 1
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == moved


def test_rotate_partition_cli_post_flip_damaged_sealed_inventory_refusal_names_the_damaged_link(tmp_path, monkeypatch, capsys):
    """Docs "Recovery" (codex r3 F1): a post-flip ``does not authenticate`` is
    NOT a statement about the receipt file.  The successor authenticates through
    a chain — its receipt, the ceremony journal, the sealed inventory, the
    container receipt — so damage to the sealed inventory after the flip refuses
    the same way while ``generations/1/partition-receipt.json`` is byte-for-byte
    intact.  The refusal names the damaged link; restoring the receipt cannot
    repair it, restoring the sealed bytes lets the same command finish.
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    with live.crash_at_rotation_step("after_pointer_flip"):
        with pytest.raises(live._RotationCrash):
            _run(p, path)
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED"]
    successor_receipt = p.container / GENERATIONS_DIR / "1" / live.RECEIPT_FILENAME
    receipt_bytes = successor_receipt.read_bytes()
    inventory = _ceremony_dir(p) / f"{ROTATION_ID}.inventory.json"
    sealed_bytes = inventory.read_bytes()
    journal_bytes = _journal_path(p).read_bytes()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    before = latch.read()
    assert before.generation_state != "ACTIVE"

    damaged = json.loads(sealed_bytes)
    damaged["inventory_sha256"] = "0" * 64
    inventory.write_text(json.dumps(damaged), encoding="utf-8")
    assert _run(p, path) == 1
    err = capsys.readouterr().err
    assert err.startswith(PREFIX)
    assert "active generation 1" in err and "does not authenticate" in err
    assert "the sealed rotation inventory digest drifted" in err, err
    assert successor_receipt.read_bytes() == receipt_bytes, "the receipt was never the damaged link"
    assert inventory.read_text(encoding="utf-8") == json.dumps(damaged), "the verb rewrote the sealed inventory"
    assert _journal_path(p).read_bytes() == journal_bytes
    assert _generation_of(p.container) == 1
    after = latch.read()
    assert after.generation_state == before.generation_state and after.generation == before.generation
    assert _store_bytes(p.container) == gen0

    # Re-writing the (intact) receipt changes nothing: the receipt is not the link.
    successor_receipt.write_bytes(receipt_bytes)
    assert _run(p, path) == 1
    assert "the sealed rotation inventory digest drifted" in capsys.readouterr().err

    inventory.write_bytes(sealed_bytes)
    assert _run(p, path) == 0
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == gen0


def test_rotate_partition_cli_crash_after_the_active_row_owes_only_the_latch_activation(tmp_path, monkeypatch, capsys):
    """Docs "Recovery" (codex r3 F2): the finish step appends the ``ACTIVE``
    journal row BEFORE it activates the writer latch, so a crash or refusal
    after the row leaves the journal complete with the latch activation still
    owed — distinct from the authentication refusals that withhold the row.
    The same command resumes it: no second ``ACTIVE`` row, the latch becomes
    ACTIVE, generation 0's bytes untouched.
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    with live.crash_at_rotation_step("after_journal_active"):
        with pytest.raises(live._RotationCrash):
            _run(p, path)
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert _generation_of(p.container) == 1
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    assert latch.read().generation_state != "ACTIVE", "the crash landed after the activation"
    journal_bytes = _journal_path(p).read_bytes()

    assert _run(p, path, as_json=True) == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    assert result["state"] == "ACTIVE" and result["generation"] == 1
    assert _journal_path(p).read_bytes() == journal_bytes, "the resume appended a second ACTIVE row"
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == gen0


def test_rotate_partition_cli_post_flip_predecessor_drift_is_refused_until_restored(tmp_path, monkeypatch, capsys):
    """Generation 0's digested store files are a link of the successor's chain.

    Docs "Recovery": a byte added to generation 0's ``evidence.jsonl`` after the
    flip is refused on every re-run through the loader's predecessor-digest
    check (before the resume branch), the journal and latch are untouched, and
    restoring the bytes lets the same command finish (fable r4 F1).
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    with live.crash_at_rotation_step("after_pointer_flip"):
        with pytest.raises(live._RotationCrash):
            _run(p, path)
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED"]
    journal_bytes = _journal_path(p).read_bytes()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    before = latch.read()

    evidence = p.container / "evidence.jsonl"
    evidence_bytes = evidence.read_bytes()
    evidence.write_bytes(evidence_bytes + b"\n")

    for _ in range(2):
        assert _run(p, path) == 1
        err = capsys.readouterr().err
        assert err.startswith(PREFIX)
        assert "predecessor generation 0" in err and "drifted since rotation" in err, err
        assert "evidence.jsonl" in err, err
    assert evidence.read_bytes() == evidence_bytes + b"\n", "the re-run rewrote generation 0"
    assert _journal_path(p).read_bytes() == journal_bytes
    assert latch.read() == before
    assert _generation_of(p.container) == 1

    evidence.write_bytes(evidence_bytes)
    assert _run(p, path) == 0
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == gen0


def test_rotate_partition_cli_missing_latch_after_the_active_row_is_refused_until_restored(tmp_path, monkeypatch, capsys):
    """A missing writer latch after the ``ACTIVE`` row is never recreated.

    Docs "Recovery" (codex r4 F1, fable r4 F2): the finish refuses ``has no
    writer generation latch`` on every re-run, the journal keeps its single
    ``ACTIVE`` row byte-for-byte, and restoring the latch file lets the same
    command activate it.
    """
    fx, p, attestation = _blocked(tmp_path, monkeypatch)
    gen0 = _store_bytes(p.container)
    path = _write(tmp_path / "operator" / "attestation.json", attestation)
    live = _live()
    with live.crash_at_rotation_step("after_journal_active"):
        with pytest.raises(live._RotationCrash):
            _run(p, path)
    capsys.readouterr()
    assert _journal_states(p) == ["DRAINING", "INVENTORY_SEALED", "ARMED", "ACTIVE"]
    journal_bytes = _journal_path(p).read_bytes()
    latch = live.WriterGenerationLatch.for_store_root(p.container)
    assert latch.read().generation_state == "DRAINING"
    latch_bytes = latch.path.read_bytes()
    latch.path.unlink()

    for _ in range(2):
        assert _run(p, path) == 1
        err = capsys.readouterr().err
        assert err.startswith(PREFIX)
        assert "has no writer generation latch" in err, err
        assert not latch.path.exists(), "the re-run recreated the writer latch"
    assert _journal_path(p).read_bytes() == journal_bytes
    assert _generation_of(p.container) == 1

    latch.path.write_bytes(latch_bytes)
    assert _run(p, path, as_json=True) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "ACTIVE" and result["generation"] == 1
    assert _journal_path(p).read_bytes() == journal_bytes
    assert latch.read().generation_state == "ACTIVE"
    assert _store_bytes(p.container) == gen0

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from phase_loop_runtime.cli import main
from phase_loop_runtime.convergence.broker import live


def _git_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    (path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def _probe(tmp_path: Path, repo: Path, *, history: Path | None = None) -> dict:
    return live.probe_zero_history_bootstrap(
        cutover_id="bootstrap-test",
        authority_root=tmp_path / "authority",
        worktrees=(repo,),
        legacy_roots=(tmp_path / "legacy",),
        historical_evidence_roots=(history,) if history else (),
        search_roots=(tmp_path,),
    )


def test_zero_history_bootstrap_requires_confirmation_without_mutation(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)

    with pytest.raises(live.LegacyCutoverConflict, match="explicit confirmation"):
        live.bootstrap_zero_history_authority(inventory)

    assert not (tmp_path / "authority").exists()
    assert not live.repository_namespace_root(repo).exists()


def test_zero_history_bootstrap_reprobes_then_activates_and_retries(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    history = tmp_path / "historical"
    history.mkdir()
    (history / "admissions.jsonl").write_text(
        json.dumps({"epoch": 1, "request": {}, "sequence": 1}) + "\n",
        encoding="utf-8",
    )
    (history / "evidence.jsonl").write_text(
        json.dumps({"idempotency_key": "old", "state": "completed"}) + "\n",
        encoding="utf-8",
    )
    inventory = _probe(tmp_path, repo, history=history)

    first = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )
    second = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert first == second
    assert first["state"] == "ACTIVE"
    assert live.global_active_authority_exists(
        authority_root=tmp_path / "authority"
    )
    snapshot = live.repository_snapshot(repo)
    receipt = live.load_partition_receipt(snapshot.store_root)
    assert receipt is not None and receipt.zero_source
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"
    assert not (tmp_path / "legacy" / "RETIRED").exists()
    assert not (tmp_path / "legacy" / "legacy-archive").exists()
    assert history.exists()

    with (history / "evidence.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"state": "late"}) + "\n")
    with pytest.raises(live.LegacyCutoverConflict, match="historical evidence bytes changed"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)


def test_zero_history_bootstrap_supports_existing_empty_legacy_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    (tmp_path / "legacy").mkdir()
    inventory = _probe(tmp_path, repo)

    first = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )
    second = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert first == second
    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is not None
    assert (tmp_path / "legacy" / "fabpub-global-cutover" / "root.lock").exists()


def test_zero_history_bootstrap_refuses_probe_apply_drift(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    history = tmp_path / "historical"
    history.mkdir()
    evidence = history / "evidence.jsonl"
    evidence.write_text(json.dumps({"state": "completed"}) + "\n", encoding="utf-8")
    inventory = _probe(tmp_path, repo, history=history)
    evidence.write_text(json.dumps({"state": "changed"}) + "\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="changed between probe and apply"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert live.load_partition_receipt(live.repository_snapshot(repo).store_root) is None


def test_zero_history_bootstrap_revalidates_after_drain_before_active(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_record = live._record_bootstrap_state

    def inject_allocator_after_drain(journal, cutover_id, state):
        original_record(journal, cutover_id, state)
        if state == "DRAINING":
            legacy = tmp_path / "legacy"
            legacy.mkdir(exist_ok=True)
            (legacy / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(live, "_record_bootstrap_state", inject_allocator_after_drain)

    with pytest.raises(live.LegacyCutoverConflict, match="allocator state appeared"):
        live.bootstrap_zero_history_authority(
            inventory, confirmed_zero_history=True
        )

    journal = tmp_path / "authority" / "bootstrap-test.bootstrap-journal.jsonl"
    assert live._bootstrap_journal_states(journal, "bootstrap-test") == ("DRAINING",)
    assert not (tmp_path / "authority" / "ACTIVE_BOOTSTRAP").exists()


def test_zero_history_bootstrap_resumes_interrupted_onboarding(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_write = live.LegacyRepositoryPartitionReceipt.write

    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.LegacyRepositoryPartitionReceipt,
            "write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert not (snapshot.store_root / live.RECEIPT_FILENAME).exists()
    assert (snapshot.namespace_root / "zero-legacy-onboarding").exists()
    assert live.LegacyRepositoryPartitionReceipt.write is original_write

    result = live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )

    assert result["state"] == "ACTIVE"
    assert live.load_partition_receipt(snapshot.store_root) is not None
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "ACTIVE"


def test_barrier_resumes_interrupted_onboarding_under_bootstrap_id(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    with monkeypatch.context() as patcher:
        patcher.setattr(
            live.LegacyRepositoryPartitionReceipt,
            "write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("crash")),
        )
        with pytest.raises(RuntimeError, match="crash"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )

    report = live.fabpub_activation_barrier([repo])

    receipt = live.load_partition_receipt(live.repository_snapshot(repo).store_root)
    assert receipt is not None and receipt.cutover_id == inventory["cutover_id"]
    assert len(report["leases"]) == 1
    live.release_barrier_leases(report)
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"


def test_bootstrap_resumes_after_atomic_receipt_temp_is_stranded(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_replace = live.os.replace

    def interrupt_receipt_replace(source, target):
        if Path(target).name == live.RECEIPT_FILENAME:
            raise RuntimeError("process interrupted before receipt replace")
        return original_replace(source, target)

    with monkeypatch.context() as patcher:
        patcher.setattr(live.os, "replace", interrupt_receipt_replace)
        with pytest.raises(RuntimeError, match="interrupted"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert list(snapshot.store_root.glob(".partition-receipt.json.*.tmp"))
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"
    assert live.load_partition_receipt(snapshot.store_root) is not None


def test_bootstrap_resumes_after_atomic_authority_temp_is_stranded(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_replace = live.os.replace

    def interrupt_authority_replace(source, target):
        if Path(target).name == "bootstrap-test.bootstrap-inventory.json":
            raise RuntimeError("process interrupted before authority replace")
        return original_replace(source, target)

    with monkeypatch.context() as patcher:
        patcher.setattr(live.os, "replace", interrupt_authority_replace)
        with pytest.raises(RuntimeError, match="interrupted"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    authority = tmp_path / "authority"
    assert list(authority.glob(".bootstrap-test.bootstrap-inventory.json.*.tmp"))
    assert live.bootstrap_zero_history_authority(
        inventory, confirmed_zero_history=True
    )["state"] == "ACTIVE"


def test_cutover_id_cannot_escape_authority_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")

    with pytest.raises(live.LegacyCutoverConflict, match="cutover_id"):
        live.probe_zero_history_bootstrap(
            cutover_id="../escaped",
            authority_root=tmp_path / "authority",
            worktrees=(repo,),
        )

    assert not (tmp_path / "escaped.bootstrap-inventory.json").exists()
    assert not (tmp_path / "authority").exists()


def test_active_bootstrap_rejects_non_prefix_journal(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    journal = tmp_path / "authority" / "bootstrap-test.bootstrap-journal.jsonl"
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"cutover_id": "bootstrap-test", "state": "ACTIVE"}) + "\n")

    with pytest.raises(live.LegacyCutoverConflict, match="exact monotonic state prefix"):
        live.global_active_authority_exists(authority_root=tmp_path / "authority")


def test_multi_root_traditional_authority_uses_claimed_primary_journal(
    tmp_path: Path,
) -> None:
    roots = (tmp_path / "a", tmp_path / "b")
    cutover_id = "multi-root"
    primary = roots[0] / "fabpub-global-cutover"
    primary.mkdir(parents=True)
    (primary / f"{cutover_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": cutover_id, "state": "ACTIVE"}) + "\n",
        encoding="utf-8",
    )
    root_set_sha256 = live._root_set_digest(roots)
    for root in roots:
        authority = root / "fabpub-global-cutover"
        authority.mkdir(parents=True, exist_ok=True)
        (authority / "ACTIVE_CUTOVER").write_text(
            json.dumps(
                {
                    "cutover_id": cutover_id,
                    "primary_authority": str(primary),
                    "root_set_sha256": root_set_sha256,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    assert live.global_active_authority_exists(roots)


def test_unrelated_bootstrap_cannot_activate_traditional_receipt(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    root = tmp_path / "traditional"
    authority = root / "fabpub-global-cutover"
    authority.mkdir(parents=True)
    collision_id = inventory["cutover_id"]
    (authority / "ACTIVE_CUTOVER").write_text(collision_id + "\n", encoding="utf-8")
    (authority / f"{collision_id}.journal.jsonl").write_text(
        json.dumps({"cutover_id": collision_id, "state": "ARMED"}) + "\n",
        encoding="utf-8",
    )
    receipt = SimpleNamespace(
        legacy_root_inventory=(str(root),),
        zero_source=False,
        global_journal_path=str(authority / f"{collision_id}.journal.jsonl"),
        cutover_id=collision_id,
    )

    assert not live._receipt_active_authority_exists(
        receipt, authority_root=tmp_path / "authority"
    )


def test_bootstrap_resume_rejects_same_id_receipt_without_inventory_binding(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    authority = tmp_path / "authority"
    authority.mkdir()
    live._atomic_write_json(
        authority / "bootstrap-test.bootstrap-inventory.json", inventory
    )

    traditional_root = tmp_path / "traditional"
    traditional_authority = traditional_root / "fabpub-global-cutover"
    traditional_authority.mkdir(parents=True)
    (traditional_authority / "ACTIVE_CUTOVER").write_text(
        "bootstrap-test\n", encoding="utf-8"
    )
    (traditional_authority / "bootstrap-test.journal.jsonl").write_text(
        "".join(
            json.dumps({"cutover_id": "bootstrap-test", "state": state}) + "\n"
            for state in ("ARMED", "ACTIVE")
        ),
        encoding="utf-8",
    )
    receipt = live.onboard_zero_legacy_repository(
        repo,
        cutover_id="bootstrap-test",
        roots=(traditional_root,),
        authority_root=authority,
    )
    assert live._receipt_bootstrap_claim(receipt) is None

    with pytest.raises(live.LegacyCutoverConflict, match="not owned by bootstrap"):
        live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)

    assert not (authority / "ACTIVE_BOOTSTRAP").exists()


def test_direct_zero_source_onboarding_requires_global_active(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    legacy_root = tmp_path / "legacy"
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority"))
    monkeypatch.setenv("PHASE_LOOP_FABPUB_LEGACY_ROOTS", str(legacy_root))

    with pytest.raises(live.LegacyCutoverConflict, match="global ACTIVE"):
        live.onboard_zero_legacy_repository(repo)

    assert not live.repository_namespace_root(repo).exists()
    assert not legacy_root.exists()


def test_onboarding_rejects_unattested_canonical_state_before_latch_mutation(
    tmp_path: Path,
) -> None:
    known = _git_repo(tmp_path / "known")
    fresh = _git_repo(tmp_path / "fresh")
    inventory = _probe(tmp_path, known)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    snapshot = live.repository_snapshot(fresh)
    snapshot.store_root.mkdir(parents=True)
    (snapshot.store_root / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="unattested canonical"):
        live.onboard_zero_legacy_repository(
            fresh, authority_root=tmp_path / "authority"
        )

    assert not (snapshot.namespace_root / "writer-generation.json").exists()


def test_post_write_zero_source_failure_never_receives_a_barrier_lease(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    original_proof = live._prove_zero_source

    def fail_after_write(snapshot, roots, boundary):
        result = original_proof(snapshot, roots, boundary)
        if boundary == "after_receipt_write":
            raise live.LegacyCutoverConflict("late source after receipt write")
        return result

    with monkeypatch.context() as patcher:
        patcher.setattr(live, "_prove_zero_source", fail_after_write)
        with pytest.raises(live.LegacyCutoverConflict, match="late source"):
            live.bootstrap_zero_history_authority(
                inventory, confirmed_zero_history=True
            )

    snapshot = live.repository_snapshot(repo)
    assert live.load_partition_receipt(snapshot.store_root) is not None
    assert live.WriterGenerationLatch.open(repo).read().generation_state == "DRAINING"
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )
    with pytest.raises(live.LegacyCutoverConflict, match="ACTIVE writer generation"):
        live.fabpub_activation_barrier([repo])


def test_existing_receipt_barrier_revalidates_global_authority(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.setenv(
        "PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority")
    )
    legacy_root = tmp_path / "legacy"
    legacy_root.mkdir(exist_ok=True)
    (legacy_root / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="allocator state appeared"):
        live.fabpub_activation_barrier([repo])

    assert live.WriterGenerationLatch.open(repo).held_leases() == ()


def test_receipt_discovers_custom_bootstrap_authority_in_fresh_process(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "repo")
    inventory = _probe(tmp_path, repo)
    live.bootstrap_zero_history_authority(inventory, confirmed_zero_history=True)
    monkeypatch.delenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "unused-default-state"))

    report = live.fabpub_activation_barrier([repo])

    assert report["repositories"] == [str(repo)]
    live.release_barrier_leases(report)


def test_manifest_activation_barrier_completes_active_transition(
    tmp_path: Path, monkeypatch
) -> None:
    manifest = tmp_path / "cutover.json"
    manifest.write_text(
        json.dumps({"cutover_id": "legacy-cutover", "rows": []}), encoding="utf-8"
    )
    monkeypatch.setenv(live.FABPUB_CUTOVER_MANIFEST_ENV, str(manifest))

    class Transaction:
        cutover_id = "legacy-cutover"
        state = "ARMED"

        def activate(self):
            self.state = "ACTIVE"
            return self

    transaction = Transaction()
    monkeypatch.setattr(live, "run_legacy_broker_cutover", lambda _manifest: transaction)

    report = live.fabpub_activation_barrier([])

    assert report["cutover"] == {"cutover_id": "legacy-cutover", "state": "ACTIVE"}


@pytest.mark.parametrize("as_json", [False, True])
def test_fabpub_bootstrap_cli_probe_and_apply(
    tmp_path: Path, monkeypatch, capsys, as_json: bool
) -> None:
    repo = _git_repo(tmp_path / "repo")
    authority = tmp_path / "authority"
    inventory = tmp_path / "probe.json"
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(authority))
    output_args = ["--json"] if as_json else []

    assert main(
        [
            "fabpub-bootstrap",
            "--probe",
            "--inventory",
            str(inventory),
            "--cutover-id",
            "cli-test",
            "--worktree",
            str(repo),
            "--legacy-root",
            str(tmp_path / "legacy"),
            "--search-root",
            str(tmp_path),
            *output_args,
        ]
    ) == 0
    probe_report = json.loads(capsys.readouterr().out)
    assert probe_report["schema"] == "ZeroHistoryBootstrapProbeResult.v1"

    assert main(
        [
            "fabpub-bootstrap",
            "--apply",
            "--inventory",
            str(inventory),
            "--confirm-zero-history",
            *output_args,
        ]
    ) == 0
    apply_report = json.loads(capsys.readouterr().out)
    assert apply_report["state"] == "ACTIVE"

from __future__ import annotations

import json
import subprocess
from pathlib import Path

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


def test_direct_zero_source_onboarding_requires_global_active(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "repo")
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(tmp_path / "authority"))

    with pytest.raises(live.LegacyCutoverConflict, match="global ACTIVE"):
        live.onboard_zero_legacy_repository(repo)

    assert not live.repository_namespace_root(repo).exists()


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
    legacy_root.mkdir()
    (legacy_root / "admissions.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(live.LegacyCutoverConflict, match="allocator state appeared"):
        live.fabpub_activation_barrier([repo])

    assert live.WriterGenerationLatch.open(repo).held_leases() == ()


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


def test_fabpub_bootstrap_cli_probe_and_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = _git_repo(tmp_path / "repo")
    authority = tmp_path / "authority"
    inventory = tmp_path / "probe.json"
    monkeypatch.setenv("PHASE_LOOP_FABPUB_AUTHORITY_ROOT", str(authority))

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
            "--json",
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
            "--json",
        ]
    ) == 0
    apply_report = json.loads(capsys.readouterr().out)
    assert apply_report["state"] == "ACTIVE"
